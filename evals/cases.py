"""The eval set: scripted conversations and what each one must show.

Each case comes from a check first done by hand while building the agent.
"""

from datetime import date, timedelta

from pydantic_evals import Case, Dataset

from conversation import Script, Transcript
from evaluators import FieldsExtracted, FinalState, IntentAt, Judge, LlmCalls, StatusAt, SummaryAt
from zonia.flow import MONTHS_ES
from zonia.models import Intent, Stage, Status

NO_REPEATED_QUESTION = Judge(
    "no repeated question",
    "Sonia never asks the candidate for information the candidate already gave, earlier in the "
    "conversation or in the same message. Asking again for something not answered yet is fine. "
    "Showing a summary of the data and asking to confirm it is not a repeated question. "
    "Naming a requirement to explain why the candidate cannot continue is not a question.",
)
SAYS_DISQUALIFIED = Judge(
    "follows directive",
    "Sonia's last reply tells the candidate kindly that they cannot continue because the job "
    "requires a driving licence, and it asks no further screening questions. It speaks to the "
    "candidate directly (\"tú\"), never about \"el candidato\" in the third person.",
)
SAYS_OUTSIDE_ZONE = Judge(
    "follows directive",
    "Sonia's last reply tells the candidate kindly that they cannot continue because they live "
    "outside the zones where the company has service, and it asks no further screening questions. "
    "It speaks to the candidate directly (\"tú\"), never about \"el candidato\" in the third person.",
)
SAYS_WITHDRAWN = Judge(
    "follows directive",
    "Sonia's last reply thanks the candidate and says goodbye. It does not ask screening "
    "questions and does not try to convince the candidate to stay.",
)
SAYS_PAUSED = Judge(
    "follows directive",
    "Sonia's last reply confirms that she will write again later and says goodbye. "
    "It does not ask screening questions.",
)
SAYS_QUALIFIED = Judge(
    "follows directive",
    "Sonia's last reply thanks the candidate and says the selection team will review the "
    "application and contact them. It asks no further questions.",
)



def in_days(days: int) -> date:
    """A start date relative to today, so the cases never fall into the past."""
    return date.today() + timedelta(days=days)


def spoken(d: date) -> str:
    """The date as a candidate writes it: "1 de diciembre de 2026"."""
    return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"


ANA_START = in_days(30)
LUIS_START = in_days(55)
CARLOS_START = in_days(45)

ANA = [
    "Hola, soy Ana López",
    "Sí, tengo carnet y vivo en Chamberí, Madrid",
    "Tiempo completo, por las mañanas",
    "Tengo 2 años de experiencia en Glovo",
    f"Puedo empezar el {spoken(ANA_START)}",
]
ANA_FIELDS = {
    "full_name": "Ana López",
    "driver_license": True,
    "city_zone": "Chamberí",
    "service_zone": "Comunidad de Madrid",
    "availability": ["full-time"],
    "schedule": ["morning"],
    "experience_years": 2,
    "experience_platform": "Glovo",
    "start_date": ANA_START,
}

CASES = [
    # --- Intent ---
    Case(
        name="intent_continue",
        inputs=Script(messages=["Sí, empecemos"]),
        evaluators=(IntentAt(0, Intent.CONTINUE), FinalState(Status.ACTIVE)),
    ),
    Case(
        name="not_now_in_first_message",
        inputs=Script(messages=["Ahora no puedo, escríbeme mañana"]),
        evaluators=(IntentAt(0, Intent.NOT_NOW), FinalState(Status.PAUSED), SAYS_PAUSED),
    ),
    Case(
        name="not_interested_in_first_message",
        inputs=Script(messages=["No me interesa"]),
        evaluators=(IntentAt(0, Intent.NOT_INTERESTED), FinalState(Status.WITHDRAWN), SAYS_WITHDRAWN),
    ),
    # --- Endings ---
    Case(
        name="withdraws_mid_conversation",
        inputs=Script(messages=["Hola, soy Marta Ruiz", "Lo he pensado y no me interesa, gracias"]),
        evaluators=(FinalState(Status.WITHDRAWN, Stage.DATA_COLLECTION), SAYS_WITHDRAWN),
    ),
    Case(
        name="pauses_mid_conversation",
        inputs=Script(messages=["Hola, soy Pablo Gil", "Ahora no puedo, escríbeme mañana"]),
        evaluators=(FinalState(Status.PAUSED, Stage.DATA_COLLECTION), SAYS_PAUSED),
    ),
    Case(
        name="no_licence",
        inputs=Script(messages=["Hola, soy Luis Pérez", "No tengo carnet de conducir"]),
        evaluators=(FinalState(Status.DISQUALIFIED), FieldsExtracted({"driver_license": False}), SAYS_DISQUALIFIED),
    ),
    Case(
        name="no_licence_in_first_message",
        inputs=Script(messages=["Hola, soy Luis Pérez y no tengo carnet de conducir"]),
        evaluators=(FinalState(Status.DISQUALIFIED), SAYS_DISQUALIFIED),
    ),
    Case(
        name="zone_outside_the_list",
        # Salamanca is a Spanish city, but its region (Castilla y León) is not a service zone.
        inputs=Script(messages=["Hola, soy Luis Pérez", "Tengo carnet y vivo en Salamanca"]),
        evaluators=(
            FieldsExtracted({"city_zone": "Salamanca", "service_zone": "outside"}),
            FinalState(Status.DISQUALIFIED, Stage.DATA_COLLECTION),
            SAYS_OUTSIDE_ZONE,
        ),
    ),
    Case(
        name="reopens_after_outside_zone",
        inputs=Script(
            messages=["Hola, soy Luis Pérez", "Tengo carnet y vivo en Salamanca", "Perdón, me equivoqué: vivo en Barcelona"]
        ),
        evaluators=(
            StatusAt(1, Status.DISQUALIFIED),
            FieldsExtracted({"city_zone": "Barcelona", "service_zone": "Cataluña"}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
        ),
    ),
    Case(
        name="full_run_qualified",
        inputs=Script(messages=[*ANA, "Sí, todo correcto"]),
        evaluators=(
            FinalState(Status.QUALIFIED, Stage.CLOSING),
            FieldsExtracted(ANA_FIELDS),
            SummaryAt(4),
            SAYS_QUALIFIED,
        ),
    ),
    # --- Data in any order ---
    Case(
        name="corrects_the_summary",
        inputs=Script(messages=[*ANA, "No, mi zona es Sevilla", "Ahora sí, todo correcto"]),
        evaluators=(
            IntentAt(5, Intent.CORRECTS_SUMMARY),
            SummaryAt(5),
            FieldsExtracted({"city_zone": "Sevilla", "service_zone": "Andalucía"}),
            FinalState(Status.QUALIFIED),
        ),
    ),
    Case(
        name="everything_in_first_message",
        inputs=Script(
            messages=[
                "Hola, soy Luis Pérez, tengo carnet, vivo en Coyoacán CDMX, busco medio tiempo los fines "
                f"de semana, horario flexible, no tengo experiencia y puedo empezar el {spoken(LUIS_START)}",
                "Sí, correcto",
            ],
            country="MX",
        ),
        evaluators=(
            SummaryAt(0),
            FieldsExtracted(
                {
                    "full_name": "Luis Pérez",
                    "driver_license": True,
                    "city_zone": "Coyoacán",
                    "service_zone": "Ciudad de México",
                    "availability": ["part-time", "weekends"],
                    "schedule": ["flexible"],
                    "experience_years": 0,
                    "start_date": LUIS_START,
                }
            ),
            FinalState(Status.QUALIFIED),
        ),
    ),
    Case(
        name="zone_before_it_is_asked",
        inputs=Script(messages=["Hola, soy Marta Ruiz y vivo en Salamanca, Madrid", "Sí, tengo carnet"]),
        evaluators=(
            FieldsExtracted({"city_zone": "Salamanca", "service_zone": "Comunidad de Madrid", "driver_license": True}),
            Judge("zone not asked", "Sonia never asks the candidate where they live or in which zone."),
        ),
    ),
    Case(
        name="no_experience_no_platform_question",
        inputs=Script(
            messages=[
                "Hola, soy Carlos Díaz",
                "Tengo licencia de manejo y vivo en Polanco, CDMX",
                "Medio tiempo, por las tardes",
                "No tengo experiencia como repartidor",
                f"Puedo empezar el {spoken(CARLOS_START)}",
                "Sí, está bien",
            ],
            country="MX",
        ),
        evaluators=(
            FieldsExtracted({"driver_license": True, "experience_years": 0}),
            FinalState(Status.QUALIFIED),
            Judge("platform not asked", "Sonia never asks which platform or company the candidate worked for."),
        ),
    ),
    # --- Reopening a closed conversation ---
    # The candidate is always trusted: a message that changes what closed the conversation reopens it.
    Case(
        name="reopens_after_no_licence",
        inputs=Script(
            messages=["Hola, soy Luis Pérez", "No tengo carnet de conducir", "Perdón, me equivoqué: sí tengo carnet"]
        ),
        evaluators=(
            StatusAt(1, Status.DISQUALIFIED),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            FieldsExtracted({"driver_license": True}),
        ),
    ),
    Case(
        name="reopens_after_withdrawing",
        inputs=Script(messages=["Hola, soy Marta Ruiz", "No me interesa, gracias", "Bueno, sí me interesa"]),
        evaluators=(
            StatusAt(1, Status.WITHDRAWN),
            IntentAt(2, Intent.CONTINUE),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
        ),
    ),
    Case(
        name="qualified_corrects_a_field",
        inputs=Script(messages=[*ANA, "Sí, todo correcto", "Perdón, mi zona es Sevilla"]),
        evaluators=(
            StatusAt(5, Status.QUALIFIED),
            IntentAt(6, Intent.CORRECTS_SUMMARY),
            SummaryAt(6),
            FieldsExtracted({"city_zone": "Sevilla", "service_zone": "Andalucía"}),
            FinalState(Status.ACTIVE, Stage.CLOSING),
        ),
    ),
    Case(
        name="qualified_no_longer_interested",
        inputs=Script(messages=[*ANA, "Sí, todo correcto", "Lo he pensado y ya no me interesa"]),
        evaluators=(
            StatusAt(5, Status.QUALIFIED),
            IntentAt(6, Intent.NOT_INTERESTED),
            FinalState(Status.WITHDRAWN, Stage.CLOSING),
            SAYS_WITHDRAWN,
        ),
    ),
    Case(
        name="goodbye_keeps_qualified",
        inputs=Script(messages=[*ANA, "Sí, todo correcto", "Gracias, adiós"]),
        evaluators=(
            StatusAt(5, Status.QUALIFIED),
            FinalState(Status.QUALIFIED, Stage.CLOSING),
            Judge(
                "short goodbye",
                "Sonia's last reply says goodbye briefly. It asks no screening questions "
                "and does not show the summary again.",
            ),
        ),
    ),
]

DATASET = Dataset[Script, Transcript, None](
    name="sonia_conversations",
    cases=CASES,
    evaluators=[NO_REPEATED_QUESTION, LlmCalls()],
)
