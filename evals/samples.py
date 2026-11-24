"""Write the sample conversations for the deliverables, played against the real LLM.

Each sample is one scripted conversation. The file shows the conversation, the data Sonia
extracted, the final status and the summary. Output: deliverables/sample-conversations/.

Usage:
    uv run python evals/samples.py               # every sample
    uv run python evals/samples.py no_licence    # only the named samples
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from zonia import settings  # noqa: E402

settings.load()

from cases import ANA, ANA_START, CASES  # noqa: E402
from conversation import Script, Transcript, converse  # noqa: E402
from zonia.flow import render_summary  # noqa: E402
from zonia.models import Stage  # noqa: E402

OUT = Path(__file__).parent.parent / "deliverables" / "sample-conversations"

# The eval scripts, by case name. Two of them stop in the middle, so here they go on to the end.
SCRIPTS = {case.name: case.inputs for case in CASES}
SAMPLES = {
    "full_run_qualified": ("A candidate gives every answer and qualifies", SCRIPTS["full_run_qualified"]),
    "asks_the_salary": (
        "The candidate asks about pay, which is not in the job facts",
        Script(messages=[*ANA[:2], "Antes de seguir, ¿cuánto se paga?", *ANA[2:], "Sí, todo correcto"]),
    ),
    "switches_to_english": (
        "The candidate switches to English in the middle",
        Script(
            messages=[
                *ANA[:2],
                "Sorry, can we continue in English? Full-time, mornings",
                "2 years with Glovo",
                f"I can start on {ANA_START:%B} {ANA_START.day}, {ANA_START.year}",
                "Yes, everything is correct",
            ]
        ),
    ),
    "no_licence": ("The candidate has no driving licence", SCRIPTS["no_licence"]),
    "zone_outside_the_list": ("The candidate lives outside the service zones", SCRIPTS["zone_outside_the_list"]),
    "mexico_uses_its_words": ("A candidate in Mexico: Sonia uses the Mexican words", SCRIPTS["mexico_uses_its_words"]),
    "withdraws_mid_conversation": ("The candidate withdraws in the middle", SCRIPTS["withdraws_mid_conversation"]),
}


def sample_file(name: str, title: str, script: Script, transcript: Transcript) -> str:
    language = transcript.turns[-1].language if transcript.turns else "es"
    # As in the recruiter dashboard: a summary only once the conversation reached closing.
    if transcript.stage == Stage.CLOSING:
        summary = render_summary(transcript.fields, language, script.country)
    else:
        summary = "No summary: the conversation ended before the closing stage. The extracted data is above."
    fields = transcript.fields.model_dump_json(indent=2, exclude_none=True)
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- Country: {script.country}",
            f"- Final status: **{transcript.status.value}**",
            f"- Final stage: {transcript.stage.value}",
            "",
            "## Conversation",
            "",
            "```text",
            transcript.text(),
            "```",
            "",
            "## Extracted data",
            "",
            "```json",
            fields,
            "```",
            "",
            "## Summary",
            "",
            summary,
            "",
        ]
    )


def index_file(rows: list[tuple[str, str, Transcript]], started: datetime) -> str:
    out = [
        "# Sample conversations",
        "",
        f"Played against the real LLM (`{os.environ.get('ZONIA_MODEL')}`) on {started:%Y-%m-%d}.",
        "The candidate's messages are scripted. Sonia's replies are what the model wrote.",
        "",
        "| Sample | What it shows | Final status |",
        "|---|---|---|",
    ]
    out += [f"| [{name}]({name}.md) | {title} | {t.status.value} |" for name, title, t in rows]
    return "\n".join([*out, ""])


async def main() -> None:
    names = sys.argv[1:] or list(SAMPLES)
    unknown = sorted(set(names) - set(SAMPLES))
    if unknown:
        sys.exit(f"Unknown samples: {', '.join(unknown)}\nKnown samples: {', '.join(SAMPLES)}")
    started = datetime.now()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in names:
        title, script = SAMPLES[name]
        transcript = await converse(script)
        (OUT / f"{name}.md").write_text(sample_file(name, title, script, transcript))
        print(f"{name}: {transcript.status.value}")
        rows.append((name, title, transcript))
    if len(names) == len(SAMPLES):
        (OUT / "README.md").write_text(index_file(rows, started))


if __name__ == "__main__":
    asyncio.run(main())
