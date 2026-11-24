"""The eval set: scripted conversations and what each one must show.

Each case comes from a check first done by hand while building the agent.
"""

from datetime import date, timedelta

from pydantic_evals import Case, Dataset

from conversation import Script, Transcript
from evaluators import FieldsExtracted, FinalState, IntentAt, Judge, LanguageAt, LlmCalls, StatusAt, SummaryAt
from zonia.flow import MONTHS_ES
from zonia.models import Intent, Stage, Status

NO_REPEATED_QUESTION = Judge(
    "no repeated question",
    "Sonia never asks the candidate for information the candidate already gave, earlier in the "
    "conversation or in the same message. Asking again for something not answered yet is fine. "
    "Showing a summary of the data and asking to confirm it is not a repeated question. "
    "Naming a requirement to explain why the candidate cannot continue is not a question. "
    "Asking again for a value that was not valid (for example a date in the past) is fine. "
    "When Sonia offers options and the candidate answers with something that is not one of them "
    "(for example specific weekdays instead of full-time, part-time or weekends), asking again to choose "
    "one of the options is fine. "
    "When the candidate's message does not answer the question (noise or another conversation), "
    "asking the same question again in other words is fine.",
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

ASKS_TO_CHOOSE_AVAILABILITY = Judge(
    "asks to choose availability",
    "Sonia's last reply asks the candidate to choose between full-time, part-time or weekends. "
    "It does not say which of the three the candidate's days are, and it does not say the answer was saved.",
)



def in_days(days: int) -> date:
    """A start date relative to today, so the cases never fall into the past."""
    return date.today() + timedelta(days=days)


def spoken(d: date) -> str:
    """The date as a candidate writes it: "1 de diciembre de 2026"."""
    return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"


def passed_this_year() -> tuple[str, date]:
    """A day and month that already passed this year, without the year, and the same day next year."""
    d = date.today() - timedelta(days=30)
    if (d.month, d.day) == (2, 29):  # next year has no 29 February
        d -= timedelta(days=1)
    return f"{d.day} de {MONTHS_ES[d.month - 1]}", d.replace(year=d.year + 1)


NO_YEAR_TEXT, NO_YEAR_DATE = passed_this_year()


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
    # --- Values that are not valid ---
    Case(
        name="first_name_only",
        inputs=Script(messages=["Hola, soy Ana"]),
        evaluators=(
            FieldsExtracted({"full_name": None}),
            FinalState(Status.ACTIVE, Stage.INTRODUCTION),
            Judge("asks for the surname", "Sonia's last reply asks the candidate for their surname."),
        ),
    ),
    Case(
        name="vague_zone",
        inputs=Script(messages=["Hola, soy Ana López", "Sí, tengo carnet y vivo cerca del centro"]),
        evaluators=(
            FieldsExtracted({"driver_license": True, "city_zone": None, "service_zone": None}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge("asks for the city", "Sonia's last reply asks the candidate in which city or neighborhood they live."),
        ),
    ),
    Case(
        name="voice_lowercase",
        inputs=Script(
            messages=[
                "hola soy maría fernanda torres",
                "sí tengo licencia de manejo y vivo en la colonia narvarte en la ciudad de méxico",
                "medio tiempo por las mañanas",
                "trabajé un año en rappi",
                f"puedo empezar el {spoken(CARLOS_START)}",
            ],
            country="MX",
        ),
        evaluators=(
            SummaryAt(4),
            Judge(
                "proper names with capitals",
                "In the summary Sonia shows, the name is written \"María Fernanda Torres\" "
                "and the platform is written \"Rappi\".",
            ),
        ),
    ),
    Case(
        name="availability_specific_weekdays",
        inputs=Script(messages=[*ANA[:2], "puedo martes miercoles y jueves"]),
        evaluators=(
            FieldsExtracted({"availability": None}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            ASKS_TO_CHOOSE_AVAILABILITY,
        ),
    ),
    Case(
        name="availability_other_weekdays",
        inputs=Script(messages=[*ANA[:2], "puedo lunes miercoles y viernes"]),
        evaluators=(
            FieldsExtracted({"availability": None}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            ASKS_TO_CHOOSE_AVAILABILITY,
        ),
    ),
    Case(
        name="past_start_date",
        inputs=Script(messages=[*ANA[:4], "Puedo empezar el 3 de marzo de 2025"]),
        evaluators=(
            FieldsExtracted({"start_date": None}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge(
                "asks for a new date",
                "Sonia's last reply says that the date has already passed and asks for a new start date. "
                "It does not show a summary.",
            ),
        ),
    ),
    Case(
        name="start_tomorrow",
        inputs=Script(messages=[*ANA[:4], "Puedo empezar mañana"]),
        evaluators=(FieldsExtracted({"start_date": in_days(1)}), SummaryAt(4)),
    ),
    Case(
        name="start_date_without_year",
        inputs=Script(messages=[*ANA[:4], f"Puedo empezar el {NO_YEAR_TEXT}"]),
        evaluators=(FieldsExtracted({"start_date": NO_YEAR_DATE}), SummaryAt(4)),
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
        name="says_no_to_the_summary_without_saying_what",
        inputs=Script(messages=[*ANA, "No", "La experiencia, son 3 años", "Ahora sí, todo correcto"]),
        evaluators=(
            Judge(
                "asks what is wrong",
                "After the candidate answers only \"No\" to the summary, Sonia's next reply asks which "
                "detail is wrong. That reply does not repeat the whole summary.",
            ),
            SummaryAt(6),
            FieldsExtracted({"experience_years": 3}),
            FinalState(Status.QUALIFIED),
        ),
    ),
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
    # --- Questions off the screening ---
    Case(
        name="asks_the_salary",
        inputs=Script(messages=[*ANA[:2], "Antes de seguir, ¿cuánto se paga?"]),
        evaluators=(
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge(
                "no invented facts",
                "Sonia's last reply gives no figure or detail about pay. It says she does not have that "
                "information and is here to help with the application. It does not say who will explain it, "
                "when, or mention any other step of the process (such as an interview). "
                "Then it asks the next screening question (availability or preferred schedule).",
            ),
        ),
    ),
    Case(
        name="asks_the_salary_twice",
        inputs=Script(messages=[
            ANA[0],
            "Sí, tengo carnet y vivo en Chamberí, Madrid. ¿Cuánto se paga?",
            "Tiempo completo, por las mañanas. Pero dime, ¿cuánto es el sueldo?",
        ]),
        evaluators=(
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge(
                "does not repeat itself",
                "Sonia's last reply gives no figure or detail about pay, and does not say who will explain it "
                "or when. It does not repeat the same sentence Sonia used the first time the candidate asked "
                "about pay: it says it in other, shorter words. Then it asks the next screening question "
                "(years of experience).",
            ),
        ),
    ),
    Case(
        name="asks_where_the_company_operates",
        inputs=Script(messages=[ANA[0], "¿En qué países está la empresa?"]),
        evaluators=(
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge(
                "answers from the job facts",
                "Sonia's last reply says the company is in Spain and Mexico, and adds no other facts about "
                "the company or the job. Then it asks the next screening question (driving licence or "
                "where the candidate lives).",
            ),
        ),
    ),
    # --- A message that is not for Sonia (voice, conversation 24) ---
    Case(
        name="background_conversation",
        inputs=Script(messages=[
            *ANA[:2],
            "¿Pero con quién estás hablando? ¿Con Claudia? No, con la Sonia. Ah. ¿Cómo que Sonia? "
            "Con Sonia, mi agente virtual. Es la que estoy creando para una empresa.",
        ]),
        evaluators=(
            FieldsExtracted({"availability": None, "schedule": None}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge(
                "says it did not understand",
                "Sonia's last reply says briefly that she did not understand the message or that it seems "
                "to be another conversation, and asks again for availability or preferred schedule, "
                "in different words from her previous question.",
            ),
        ),
    ),
    # --- Language: Spanish and English (design 4.3) ---
    Case(
        name="switches_to_english",
        inputs=Script(messages=[*ANA[:2], "Sorry, can we continue in English? Full-time, mornings"]),
        evaluators=(
            LanguageAt(1, "es"),
            LanguageAt(2, "en"),
            FieldsExtracted({"availability": ["full-time"], "schedule": ["morning"]}),
            FinalState(Status.ACTIVE, Stage.DATA_COLLECTION),
            Judge(
                "replies in english",
                "Sonia's last reply is fully in English and asks the next screening question "
                "(years of experience as a delivery driver).",
            ),
        ),
    ),
    Case(
        name="mixed_message_mostly_english",
        inputs=Script(messages=[ANA[0], "Yes, I have a driving licence and I live in Chamberí, Madrid, gracias"]),
        evaluators=(
            LanguageAt(1, "en"),
            FieldsExtracted({"driver_license": True, "service_zone": "Comunidad de Madrid"}),
            Judge("replies in english", "Sonia's last reply is fully in English."),
        ),
    ),
    Case(
        name="writes_in_another_language",
        inputs=Script(messages=[ANA[0], "Sim, tenho carta de condução e moro em Chamberí, Madrid"]),
        evaluators=(
            LanguageAt(1, "es"),
            Judge(
                "only spanish or english",
                "Sonia's last reply is in Spanish. In one sentence it says she can only help in Spanish "
                "or English. It does not reply in Portuguese.",
            ),
        ),
    ),
    # --- The country's words (design 4.3): Mexico says "licencia de manejo" and "colonia" ---
    Case(
        name="mexico_uses_its_words",
        inputs=Script(messages=["Hola, soy Luis Pérez", "No tengo carnet"], country="MX"),
        evaluators=(
            FinalState(Status.DISQUALIFIED),
            FieldsExtracted({"driver_license": False}),
            Judge(
                "mexican words",
                "When Sonia asks about or names the licence, she says \"licencia de manejo\" (or \"licencia\"), "
                "never \"carné\" or \"carnet\". She does not correct the candidate's word.",
            ),
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
