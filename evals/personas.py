"""Simulated candidates: an LLM plays a candidate with a personality and talks with Sonia.

The scripted cases (cases.py) check exact results. These conversations are not scripted:
they show how Sonia handles odd, silly or unclear answers. An LLM judge checks a few rules
(RULES); a person reads the transcripts in the report.

Usage:
    uv run python evals/personas.py                 # every persona
    uv run python evals/personas.py bromista        # only the named personas
"""

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from zonia import settings  # noqa: E402

settings.load()

from pydantic_ai import Agent  # noqa: E402

from conversation import AGENT, JUDGE_MODEL, JUDGE_SETTINGS, MODEL, with_retries  # noqa: E402
from run import git_version  # noqa: E402
from pydantic_evals.evaluators.llm_as_a_judge import judge_output  # noqa: E402

from zonia.config import GREETING  # noqa: E402
from zonia.flow import FINAL_STATUSES  # noqa: E402
from zonia.models import Status  # noqa: E402
from zonia.turn import new_conversation, run_turn  # noqa: E402

REPORTS = Path(__file__).parent / "reports"
MAX_CANDIDATE_TURNS = 20
# The conversation stops here: a final status, or the candidate asked to be written to later.
STOP_STATUSES = FINAL_STATUSES | {Status.PAUSED}

CANDIDATE_RULES = """\
Eres una persona que ha pedido trabajo de repartidor en Grupo Sazón. Sonia, una asistente de IA,
te hace preguntas por {channel}. Haz el papel de esta persona:

{personality}

Reglas:
- Escribe solo tu próximo mensaje, sin comillas y sin explicar nada.
- Mensajes cortos, como en una conversación real.
- No digas que eres una IA ni que esto es una prueba.
"""

VOICE_STYLE = """
Hablas por teléfono. Tu mensaje es lo que el sistema de voz entendió de lo que dijiste:
sin puntuación ni mayúsculas, con muletillas ("eh", "o sea", "este"), números en palabras
("veinticinco de diciembre") y a veces una palabra mal entendida.
"""


@dataclass
class Persona:
    name: str
    personality: str
    country: str = "ES"  # "ES" or "MX": decides the service zones and the words
    voice: bool = False  # True: writes like the speech-to-text of a voice call


PERSONAS = [
    Persona(
        "bromista",
        "Te llamas Javier Ruiz, vives en Lavapiés (Madrid) y tienes carné de conducir. Te tomas todo a broma: "
        "a muchas preguntas contestas con tonterías, chistes o datos absurdos (por ejemplo, que vives en la Luna "
        "o que tu experiencia es repartir pizzas en un videojuego). Si Sonia insiste con amabilidad, al final "
        "das el dato real. Disponibilidad: fines de semana, por la tarde. Puedes empezar dentro de dos semanas.",
    ),
    Persona(
        "voz_dudoso",
        "Te llamas María Fernanda Torres, vives en la colonia Narvarte (Ciudad de México) y tienes licencia de "
        "manejo. Hablas despacio y dudas mucho: a veces empiezas una respuesta, te corriges a la mitad o "
        "preguntas \"¿cómo?\" porque no entendiste. Disponibilidad: medio tiempo, por las mañanas. Trabajaste "
        "un año en Rappi. Puedes empezar el próximo lunes.",
        country="MX",
        voice=True,
    ),
    Persona(
        "monosilabos",
        "Te llamas Pedro Gómez Sanz, vives en Gràcia (Barcelona) y tienes carné. Contestas con una o dos "
        "palabras (\"si\", \"ok\", \"bcn\", \"finde\"), sin explicar nada, aunque Sonia pida más detalle. "
        "Disponibilidad: fines de semana, por la noche. Sin experiencia. Puedes empezar ya.",
    ),
    Persona(
        "desconfiado",
        "Te llamas Laura Martín Vega, vives en Triana (Sevilla) y tienes carné. Desconfías: preguntas cuánto "
        "pagan, qué horario exacto hay, si Sonia es un robot y para qué quiere tus datos. Insistes con el sueldo "
        "dos veces. Después contestas. Disponibilidad: tiempo completo, por la tarde. Dos años en Uber Eats. "
        "Puedes empezar el mes que viene.",
    ),
    Persona(
        "fuera_de_tema",
        "Te llamas Sergio Navarro, vives en Ruzafa (Valencia) y tienes carné. Te distraes: cuentas cosas de tu "
        "perro, del fútbol o del tiempo, y preguntas a Sonia cosas que no tienen que ver (recetas, el partido "
        "de ayer). Contestas lo que te pregunta solo a veces. Disponibilidad: medio tiempo, por las mañanas. "
        "Un año en Just Eat. Puedes empezar en tres semanas.",
    ),
    Persona(
        "cambia_de_opinion",
        "Te llamas Lucía Herrera Gil, vives en Chamberí (Madrid) y tienes carné. Cambias tus respuestas: primero "
        "dices tiempo completo y luego medio tiempo, das una fecha y después otra. Cuando Sonia muestra el "
        "resumen, corriges un dato. Experiencia: seis meses en Glovo, por las tardes.",
    ),
    Persona(
        "spanglish",
        "Te llamas Daniel Castro, vives en la colonia Roma (Ciudad de México) y tienes licencia de manejo. "
        "Mezclas español e inglés en la misma frase, y a veces escribes un mensaje entero en inglés. "
        "Disponibilidad: full time, mornings. Trabajaste en DiDi Food un año. Puedes empezar el 1 del mes que viene.",
        country="MX",
    ),
    Persona(
        "voz_sin_licencia",
        "Te llamas Rosa Delgado, vives en Coyoacán (Ciudad de México). No tienes licencia de manejo, pero tienes "
        "bicicleta y crees que eso sirve. Si Sonia dice que no puedes seguir, te enfadas un poco y preguntas por qué.",
        country="MX",
        voice=True,
    ),
]

# What a person checks by reading the report, given to an LLM judge for every conversation.
RULES = {
    "amable": "Sonia is always polite and patient, also when the candidate jokes, is rude or gives silly answers.",
    "vuelve_al_tema": "After an off-topic, silly or unclear answer, Sonia brings the conversation back to the "
    "open screening question. She does not save an absurd answer as if it were real data.",
    "no_inventa": "Sonia never invents facts about the job or the company (pay, shift hours, contract). "
    "When she does not have the information, she says so.",
    "cierre": "If the conversation ended (qualified, disqualified, withdrawn or paused), Sonia's last reply "
    "fits that ending and asks no more screening questions. If it did not end, this rule passes.",
}


def candidate_agent(persona: Persona) -> Agent[None, str]:
    rules = CANDIDATE_RULES.format(
        channel="teléfono" if persona.voice else "chat", personality=persona.personality
    )
    return Agent(MODEL, output_type=str, instructions=rules + (VOICE_STYLE if persona.voice else ""))


async def talk(persona: Persona, lines: list[str]) -> Status:
    """Run one conversation and return the final status.

    Each turn adds its lines ("Candidato: ...", "Sonia: ...") to `lines` at once, so a crash keeps the turns before it.
    """
    candidate = candidate_agent(persona)
    conversation = new_conversation(persona.country)
    lines += [f"Sonia: {text}" for text in GREETING]
    for _ in range(MAX_CANDIDATE_TURNS):
        prompt = "La conversación hasta ahora:\n\n" + "\n".join(lines) + "\n\nTu próximo mensaje:"
        message = (await with_retries(lambda: candidate.run(prompt))).output.strip()
        turn = await with_retries(lambda: run_turn(AGENT, conversation, message))
        lines += [f"Candidato: {message}", f"Sonia: {turn.reply}"]
        if conversation.status in STOP_STATUSES:
            break
    return conversation.status


async def judge(lines: list[str]) -> dict[str, tuple[bool, str]]:
    """Each rule: (passed, the judge's reason)."""
    text = "\n".join(lines)
    result = {}
    for name, rubric in RULES.items():
        grade = await with_retries(lambda: judge_output(text, rubric, model=JUDGE_MODEL, model_settings=JUDGE_SETTINGS))
        result[name] = (grade.pass_, grade.reason)
    return result


# Persona, transcript lines, final status (or the error that stopped it), rule results.
Result = tuple[Persona, list[str], str, dict[str, tuple[bool, str]]]


def write_report(results: list[Result], started: datetime) -> Path:
    out = [
        f"# Simulated candidates {started:%Y-%m-%d %H:%M}",
        "",
        f"- Model: `{os.environ.get('ZONIA_MODEL')}` (Sonia and the candidates)",
        f"- Judge model: `{os.environ.get('ZONIA_JUDGE_MODEL')}` (high reasoning effort)",
        f"- Code: `{git_version()}`",
        "",
        "| Persona | Channel | Country | Candidate messages | Final status | Rules passed |",
        "|---|---|---|---|---|---|",
    ]
    for persona, lines, status, grades in results:
        messages = sum(line.startswith("Candidato:") for line in lines)
        channel = "voice" if persona.voice else "chat"
        passed = sum(ok for ok, _ in grades.values())
        out.append(f"| {persona.name} | {channel} | {persona.country} | {messages} | {status} | {passed} of {len(grades)} |")
    for persona, lines, _, grades in results:
        out += ["", f"## {persona.name}", ""]
        out += [f"- **{name}**: {'pass' if ok else 'FAIL'}. {reason}" for name, (ok, reason) in grades.items()]
        out += ["", "<details><summary>Transcript</summary>", "", "```text", *lines, "```", "", "</details>"]
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"personas_{started:%Y-%m-%d_%H%M%S}.md"
    path.write_text("\n".join(out) + "\n")
    return path


async def main() -> None:
    names = set(sys.argv[1:])
    known = [p.name for p in PERSONAS]
    unknown = sorted(names - set(known))
    if unknown:
        sys.exit(f"Unknown personas: {', '.join(unknown)}\nKnown personas: {', '.join(known)}")
    started = datetime.now()
    results: list[Result] = []
    for persona in PERSONAS:
        if names and persona.name not in names:
            continue
        print(f"{persona.name}: talking...", flush=True)
        lines: list[str] = []
        try:
            status = await talk(persona, lines)
            grades = await judge(lines)
        except Exception as error:  # noqa: BLE001 - keep what was done; the error goes in the report
            results.append((persona, lines, f"stopped: {type(error).__name__}", {}))
            print(f"{persona.name}: stopped by {type(error).__name__}: {error}", flush=True)
            break
        failed = [name for name, (ok, _) in grades.items() if not ok]
        print(f"{persona.name}: {status}, failed rules: {', '.join(failed) or 'none'}", flush=True)
        results.append((persona, lines, str(status), grades))
        write_report(results, started)  # after each persona, so a stopped run keeps its report
    print(f"Report: {write_report(results, started)}")

if __name__ == "__main__":
    asyncio.run(main())
