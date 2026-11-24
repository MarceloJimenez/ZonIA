"""Run the eval set against the real LLM and save a report in evals/reports/.

Usage:
    uv run python evals/run.py               # every case
    uv run python evals/run.py no_licence    # only the named cases
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from zonia import settings  # noqa: E402

settings.load()

from pydantic_evals import Dataset  # noqa: E402

from cases import DATASET  # noqa: E402
from conversation import converse  # noqa: E402

REPORTS = Path(__file__).parent / "reports"


def git_version() -> str:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    # Changes in src/ or evals/ change the result. The reports themselves do not.
    status = ["git", "status", "--porcelain", "src", "evals", ":(exclude)evals/reports"]
    dirty = subprocess.run(status, capture_output=True, text=True).stdout.strip()
    return f"{commit} + uncommitted changes in src/ or evals/" if dirty else commit


def failed_checks(case) -> list[str]:
    lines = []
    for result in case.assertions.values():
        if result.value is not True:
            lines.append(f"- **{result.name}**: {result.reason}")
    for failure in case.evaluator_failures:
        lines.append(f"- **{failure.name}** could not run: {failure.error_message}")
    return lines


def write_report(report, started: datetime) -> Path:
    passed = sum(all(a.value is True for a in c.assertions.values()) and not c.evaluator_failures for c in report.cases)
    out = [
        f"# Eval run {started:%Y-%m-%d %H:%M}",
        "",
        f"- Model: `{os.environ.get('ZONIA_MODEL')}` (agent)",
        f"- Judge model: `{os.environ.get('ZONIA_JUDGE_MODEL')}` (high reasoning effort)",
        f"- Code: `{git_version()}`",
        f"- Cases passed: **{passed} of {len(report.cases) + len(report.failures)}**",
        "",
        "```",
        report.render(width=140, include_durations=False),
        "```",
        "",
    ]
    for failure in report.failures:
        out += [f"## {failure.name}: the conversation crashed", "", f"`{failure.error_message}`", ""]
    for case in report.cases:
        problems = failed_checks(case)
        out += [f"## {case.name}: {'FAIL' if problems else 'pass'}", ""]
        out += [*problems, ""] if problems else []
        out += ["<details><summary>Transcript</summary>", "", "```text", case.output.text(), "```", "", "</details>", ""]
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{started:%Y-%m-%d_%H%M%S}.md"
    path.write_text("\n".join(out))
    return path


def main() -> None:
    names = set(sys.argv[1:])
    dataset = DATASET
    known = [c.name for c in DATASET.cases]
    unknown = sorted(names - set(known))
    if unknown:
        sys.exit(f"Unknown cases: {', '.join(unknown)}\nKnown cases: {', '.join(known)}")
    if names:
        dataset = Dataset(name=DATASET.name, cases=[c for c in DATASET.cases if c.name in names], evaluators=DATASET.evaluators)
    started = datetime.now()
    report = dataset.evaluate_sync(converse, max_concurrency=1)
    report.print(include_durations=False)
    print(f"Report: {write_report(report, started)}")


if __name__ == "__main__":
    main()
