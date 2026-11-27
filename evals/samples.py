"""Write the sample conversations for the deliverables, played against the real LLM.

Each sample is a standalone HTML page: the conversation in a phone, like the web chat, and a side
panel with the extracted data, the final status and the summary. Seven samples are scripted
(the normal flow). Four are simulated candidates from personas.py (resilience), listed in SHOWN_PERSONAS.
Output: deliverables/sample-conversations/.

Usage:
    uv run python evals/samples.py               # every sample and persona, and the index
    uv run python evals/samples.py no_licence    # only the named samples or personas
"""

import asyncio
import base64
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from zonia import settings  # noqa: E402

settings.load()

from jinja2 import Environment  # noqa: E402

from cases import ANA, ANA_START, CASES  # noqa: E402
from conversation import Script, Transcript, converse  # noqa: E402
from personas import PERSONAS, Persona, talk  # noqa: E402
from zonia.config import GREETING  # noqa: E402
from zonia.domain.conversation import new_conversation  # noqa: E402
from zonia.texts.summary import render_summary  # noqa: E402
from zonia.domain.models import ScreeningFields, Stage  # noqa: E402
from zonia.agent.llm import SONIA, spec_version  # noqa: E402

OUT = Path(__file__).parent.parent / "deliverables" / "sample-conversations"
STATIC = Path(__file__).parent.parent / "src" / "zonia" / "static"
NO_SUMMARY = "No summary: the conversation ended before the closing stage. The extracted data is above."

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

# The simulated candidates shown as samples: the same 4 as the process design document.
SHOWN_PERSONAS = ["hacker", "manipulador", "cambia_de_opinion", "voz_dudoso"]

# One line per persona, from its personality.
PERSONA_TITLES = {
    "bromista": "A joker who answers with nonsense until Sonia insists politely",
    "voz_dudoso": "A hesitant caller in Mexico who corrects herself and asks Sonia to repeat",
    "monosilabos": "A candidate who answers in one or two words, with no detail",
    "desconfiado": "A distrustful candidate who asks about pay twice and whether Sonia is a robot",
    "manipulador": "A candidate who pushes to be approved at once and claims to know the boss",
    "fuera_de_tema": "A candidate who drifts to his dog, football and recipes",
    "cambia_de_opinion": "A candidate who changes answers, then gives her brother's data after the summary",
    "spanglish": "A candidate in Mexico who mixes Spanish and English",
    "voz_sin_licencia": "A caller in Mexico with no driving licence who argues with the rejection",
    "hacker": "An attacker who tries prompt injection and fake system messages",
}


@dataclass
class Page:
    """Everything one HTML page shows."""

    name: str
    title: str
    country: str
    channel: str  # "Web chat" or "Voice"
    status: str
    stage: str
    bubbles: list[tuple[str, str]]  # ("agent" or "me", text)
    fields: dict[str, str]
    summary: str
    group: str  # "Normal flow" or "Resilience"
    candidate_model: str | None = None


STYLE = """
.sample .zn-stage { flex: 0 1 390px; min-width: 0; }
.sample__panel table, .sample-index table { min-width: 0; }
.sample { display: flex; flex-wrap: wrap; gap: 40px; align-items: flex-start; justify-content: center; padding: 24px; }
.sample__panel { flex: 1 1 360px; max-width: 520px; font: 400 15px/1.5 var(--font-sans); color: var(--ink); }
.sample__panel h1 { font: 600 24px/1.2 var(--font-display); margin: 8px 0 16px; }
.sample__panel h2 { font: 600 16px/1.2 var(--font-display); margin: 24px 0 8px; }
.sample__panel table { border-collapse: collapse; width: 100%; background: var(--surface); }
.sample__panel th, .sample__panel td { text-align: left; vertical-align: top; padding: 6px 10px; border-bottom: 1px solid var(--line); }
.sample__panel th { width: 38%; color: var(--ink-muted); font-weight: 500; }
.sample__summary { white-space: pre-wrap; background: var(--surface); padding: 12px; border-radius: var(--radius-md); border: 1px solid var(--line); }
.sample__bar { padding: 12px 16px; margin: 0; color: var(--ink-subtle); font: 400 14px/1 var(--font-sans); border-top: 1px solid var(--line); }
.sample-index { max-width: 1000px; margin: 0 auto; padding: 24px; font: 400 15px/1.5 var(--font-sans); color: var(--ink); }
.sample-index h1 { font: 600 28px/1.2 var(--font-display); }
.sample-index h2 { font: 600 20px/1.2 var(--font-display); margin-top: 32px; }
.sample-index table { border-collapse: collapse; width: 100%; background: var(--surface); }
.sample-index th, .sample-index td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); }
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ page.title }} · ZonIA sample</title>
<style>{{ css|safe }}{{ style|safe }}</style>
</head>
<body>
<div class="zn-root"><div class="page">
<div class="sample">
<div class="zn-stage">
<div class="zn-phone">
<div class="zn-phone__screen">
<div class="zn-phone__status"><span>9:41</span><span class="zn-phone__island"></span><span class="zn-phone__signal">●●●●</span></div>
<div class="zn-phchat__hd">
<img class="zn-avatar" src="{{ avatar }}" alt="">
<span class="zn-phchat__name">Sonia</span>
<span class="zn-phchat__tag">{{ page.channel }}</span>
</div>
<div class="zn-phchat__body">
<div class="zn-bubbles">
{% for role, text in page.bubbles %}
<p class="zn-bubble {{ 'zn-bubble--agent' if role == 'agent' else 'zn-bubble--me' }}">{{ text }}</p>
{% endfor %}
</div>
</div>
<p class="sample__bar">Sample conversation, read only</p>
</div>
</div>
</div>
<div class="sample__panel">
<a href="index.html">← All samples</a>
<h1>{{ page.title }}</h1>
<table>
<tr><th>Group</th><td>{{ page.group }}</td></tr>
<tr><th>Country</th><td>{{ page.country }}</td></tr>
<tr><th>Channel</th><td>{{ page.channel }}</td></tr>
<tr><th>Final status</th><td><strong>{{ page.status }}</strong></td></tr>
<tr><th>Final stage</th><td>{{ page.stage }}</td></tr>
{% if page.candidate_model %}
<tr><th>Candidate model</th><td>The candidate is played by {{ page.candidate_model }}, a stronger model than Sonia's {{ sonia_model }}.</td></tr>
{% endif %}
</table>
<h2>Extracted data</h2>
{% if page.fields %}
<table>
<tr><th>Field</th><th>Value</th></tr>
{% for key, value in page.fields.items() %}
<tr><td>{{ key }}</td><td>{{ value }}</td></tr>
{% endfor %}
</table>
{% else %}
<p>No data extracted.</p>
{% endif %}
<h2>Summary</h2>
<div class="sample__summary">{{ page.summary }}</div>
</div>
</div>
</div></div>
</body>
</html>
"""

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZonIA sample conversations</title>
<style>{{ css|safe }}{{ style|safe }}</style>
</head>
<body>
<div class="zn-root"><div class="page"><div class="sample-index">
<h1>Sample conversations</h1>
<p>Played against the real LLM ({{ sonia_model }}, prompt {{ prompt }}) on {{ date }}.
In the normal flow, the candidate's messages are scripted. In resilience, another model plays the candidate.
Sonia's replies are always what the model wrote.</p>
{% for group, pages in groups %}
<h2>{{ group }}</h2>
<table>
<tr><th>Sample</th><th>What it shows</th><th>Channel</th><th>Country</th><th>Final status</th></tr>
{% for p in pages %}
<tr><td><a href="{{ p.name }}.html">{{ p.name }}</a></td><td>{{ p.title }}</td><td>{{ p.channel }}</td><td>{{ p.country }}</td><td>{{ p.status }}</td></tr>
{% endfor %}
</table>
{% endfor %}
</div></div></div>
</body>
</html>
"""

ENV = Environment(autoescape=True)


def assets() -> dict[str, str]:
    """The CSS and the avatar, read at run time, so a page needs no server."""
    avatar = base64.b64encode((STATIC / "sonia.jpg").read_bytes()).decode()
    return {
        "css": (STATIC / "zonia.css").read_text(),
        "style": STYLE,
        "avatar": f"data:image/jpeg;base64,{avatar}",
        "sonia_model": SONIA.model,
    }


def field_rows(fields: ScreeningFields) -> dict[str, str]:
    """Each field as plain text: lists joined, yes or no, whole numbers without ".0"."""

    def show(value) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, list):
            return ", ".join(show(v) for v in value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    return {k: show(v) for k, v in fields.model_dump(mode="json", exclude_none=True).items()}


def closing_summary(fields: ScreeningFields, stage: Stage, language: str, country: str) -> str:
    """As in the recruiter dashboard: a summary only once the conversation reached closing."""
    return render_summary(fields, language, country) if stage == Stage.CLOSING else NO_SUMMARY


def scripted_page(name: str, title: str, script: Script, transcript: Transcript) -> Page:
    language = transcript.turns[-1].language if transcript.turns else "es"
    bubbles = [("agent", text) for text in GREETING]
    for message, reply in [*transcript.prepared, *((t.message, t.reply) for t in transcript.turns)]:
        bubbles += [("me", message), ("agent", reply)]
    return Page(
        name=name,
        title=title,
        country=script.country,
        channel="Web chat",
        status=transcript.status.value,
        stage=transcript.stage.value,
        bubbles=bubbles,
        fields=field_rows(transcript.fields),
        summary=closing_summary(transcript.fields, transcript.stage, language, script.country),
        group="Normal flow",
    )


def persona_page(persona: Persona, lines: list[str], conversation, status: str) -> Page:
    bubbles = []
    for line in lines:
        role, _, text = line.partition(": ")
        bubbles.append(("agent" if role == "Sonia" else "me", text))
    return Page(
        name=persona.name,
        title=PERSONA_TITLES[persona.name],
        country=persona.country,
        channel="Voice" if persona.voice else "Web chat",
        status=status,
        stage=conversation.stage.value,
        bubbles=bubbles,
        fields=field_rows(conversation.fields),
        summary=closing_summary(conversation.fields, conversation.stage, conversation.language, persona.country),
        group="Resilience",
        candidate_model=persona.model,
    )


def render_page(page: Page) -> str:
    return ENV.from_string(PAGE).render(page=page, **assets())


def render_index(groups: list[tuple[str, list[Page]]], started: datetime) -> str:
    return ENV.from_string(INDEX).render(
        groups=groups, date=f"{started:%Y-%m-%d}", prompt=spec_version(SONIA), **assets()
    )


def index_markdown(groups: list[tuple[str, list[Page]]], started: datetime) -> str:
    out = [
        "# Sample conversations",
        "",
        "Open index.html in a browser.",
        "",
        f"Played against the real LLM (`{SONIA.model}`, prompt `{spec_version(SONIA)}`) on {started:%Y-%m-%d}.",
        "In the normal flow, the candidate's messages are scripted. In resilience, another model plays the candidate.",
        "Sonia's replies are what the model wrote.",
    ]
    for group, pages in groups:
        out += ["", f"## {group}", "", "| Sample | What it shows | Channel | Country | Final status |", "|---|---|---|---|---|"]
        out += [f"| [{p.name}]({p.name}.html) | {p.title} | {p.channel} | {p.country} | {p.status} |" for p in pages]
    return "\n".join([*out, ""])


def stopped_page(persona: Persona, lines: list[str], conversation, error: Exception) -> Page:
    return persona_page(persona, lines, conversation, f"stopped: {type(error).__name__}")


async def main() -> None:
    personas = {p.name: p for p in PERSONAS if p.name in SHOWN_PERSONAS}
    names = sys.argv[1:] or [*SAMPLES, *personas]
    unknown = sorted(set(names) - set(SAMPLES) - set(personas))
    if unknown:
        sys.exit(f"Unknown samples: {', '.join(unknown)}\nKnown samples: {', '.join([*SAMPLES, *personas])}")
    started = datetime.now()
    OUT.mkdir(parents=True, exist_ok=True)
    pages = []
    for name in names:
        if name in SAMPLES:
            title, script = SAMPLES[name]
            page = scripted_page(name, title, script, await converse(script))
        else:
            persona = personas[name]
            lines: list[str] = []
            conversation = new_conversation(persona.country)
            try:
                status = (await talk(persona, lines, conversation)).value
                page = persona_page(persona, lines, conversation, status)
            except Exception as error:  # noqa: BLE001 - keep what was said; the page shows the error
                page = stopped_page(persona, lines, conversation, error)
        (OUT / f"{name}.html").write_text(render_page(page))
        print(f"{name}: {page.status}", flush=True)
        pages.append(page)
    if len(names) == len(SAMPLES) + len(personas):
        groups = [(g, [p for p in pages if p.group == g]) for g in ("Normal flow", "Resilience")]
        (OUT / "index.html").write_text(render_index(groups, started))
        (OUT / "README.md").write_text(index_markdown(groups, started))


if __name__ == "__main__":
    asyncio.run(main())
