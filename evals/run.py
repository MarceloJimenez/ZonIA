"""Run the eval set against the real LLM and save a report in evals/reports/.

Usage:
    uv run python evals/run.py               # every case
    uv run python evals/run.py no_licence    # only the named cases
"""

import hashlib
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from zonia import settings  # noqa: E402

settings.load()

from pydantic_evals import Dataset  # noqa: E402

from cases import DATASET  # noqa: E402
from conversation import JUDGE, converse  # noqa: E402
from zonia.agent.llm import SONIA, describe  # noqa: E402

REPORTS = Path(__file__).parent / "reports"


EVALS = Path(__file__).parent
# Changes in src/ or evals/ change the result. The reports themselves do not.
CODE_PATHS = ["src", "evals", ":(exclude)evals/reports"]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=EVALS.parent).stdout


def git_version(report: Path) -> str:
    """The commit the run used. With uncommitted changes in src/ or evals/, also the file that keeps them:
    the diff is saved next to the report, with the same name and .patch, so the run can be repeated."""
    commit = _git("rev-parse", "--short", "HEAD").strip()
    if not _git("status", "--porcelain", *CODE_PATHS).strip():
        return commit
    diff = _git("diff", "--binary", "HEAD", "--", *CODE_PATHS)
    for new_file in _git("ls-files", "--others", "--exclude-standard", "--", *CODE_PATHS).splitlines():
        diff += _git("diff", "--binary", "--no-index", "--", "/dev/null", new_file)
    patch = report.with_suffix(".patch")
    patch.write_text(diff)
    return f"{commit} + uncommitted changes in {patch.name}"


def data_version(files: list[str], cases: int, total: int) -> str:
    """Which eval data the run used: a short hash of the files that hold the cases and the checks,
    how many cases ran, and the day the relative dates (for example "start tomorrow") start from."""
    digest = hashlib.sha256(b"".join((EVALS / f).read_bytes() for f in files)).hexdigest()[:12]
    names = ", ".join(f"evals/{f}" for f in files)
    return f"`{digest}` (hash of {names}), {cases} of {total} cases, dates relative to {date.today().isoformat()}"


def failed_checks(case) -> list[str]:
    lines = []
    for result in case.assertions.values():
        if result.value is not True:
            lines.append(f"- **{result.name}**: {result.reason}")
    for failure in case.evaluator_failures:
        lines.append(f"- **{failure.name}** could not run: {failure.error_message}")
    return lines


def write_report(report, started: datetime) -> Path:
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{started:%Y-%m-%d_%H%M%S}.md"
    cases = len(report.cases) + len(report.failures)
    passed = sum(all(a.value is True for a in c.assertions.values()) and not c.evaluator_failures for c in report.cases)
    out = [
        f"# Eval run {started:%Y-%m-%d %H:%M}",
        "",
        f"- Agent: {describe(SONIA)}",
        f"- Judge: {describe(JUDGE)}",
        f"- Code: `{git_version(path)}`",
        f"- Data: {data_version(['cases.py', 'evaluators.py'], cases, len(DATASET.cases))}",
        f"- Cases passed: **{passed} of {cases}**",
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
