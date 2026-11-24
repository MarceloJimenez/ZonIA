"""Business settings that change without a code change. Example data, to be replaced by Grupo Sazón's real list."""

from datetime import timedelta
from enum import StrEnum

# Service zones per country: large regions, so the list stays short.
# The assignment only says "Must be within service areas" (docs/ASSIGNMENT.md:30).
SERVICE_ZONES = {
    "ES": [
        "Andalucía",
        "Cataluña",
        "Comunidad de Madrid",
        "Comunidad Valenciana",
        "País Vasco",
        "Galicia",
    ],
    "MX": [
        "Ciudad de México",
        "Estado de México",
        "Jalisco",
        "Nuevo León",
        "Puebla",
        "Guanajuato",
    ],
}


# The words Sonia uses in Spanish for the licence and the area, per country.
# Design: docs/plans/Process design draft.md, sections 4.3 and 6. She understands every form in both countries.
LOCAL_WORDS = {
    "ES": {"license": "carné de conducir", "area": "barrio"},
    "MX": {"license": "licencia de manejo", "area": "colonia"},
}


# Sonia's first message, one string per bubble. It says she is an AI.
# Design: docs/plans/Process design draft.md, section 6, "Examples".
GREETING = [
    "Hola, soy Sonia, la asistente de IA de Grupo Sazón. Te escribo por tu solicitud de repartidor.",
    "Son unos 5 minutos. ¿Seguimos? Si es así, dime tu nombre completo.",
]

# The candidate never answered the greeting. On WhatsApp this is a template approved by Meta, in Spanish like the greeting.
NO_REPLY_REMINDER = (
    "Hola de nuevo, soy Sonia, la asistente de IA de Grupo Sazón. "
    "Te escribí por tu solicitud de repartidor. ¿Seguimos? Si es así, dime tu nombre completo."
)


# What Sonia may tell a candidate about the company and the job, one fact per line.
# Only facts from the assignment (docs/ASSIGNMENT.md); the client adds more here.
# For anything not listed (pay, shift hours...), Sonia says she does not have that information.
JOB_FACTS = [
    "El puesto es de repartidor.",
    "Los datos sirven para revisar la solicitud de repartidor.",
    "Grupo Sazón está en España y en México.",
]


# Most candidate messages in one conversation, against abuse and runaway LLM cost.
# A normal conversation takes about 6; 60 leaves room for corrections and questions.
MAX_TURNS = 60


class FollowUpStep(StrEnum):
    """One follow-up step when the candidate stops replying."""

    REMINDER = "reminder"  # Sonia writes again
    PAUSE = "pause"  # status paused
    INCOMPLETE = "incomplete"  # status incomplete


# What happens when the candidate stops replying: (time since Sonia's last message, step).
# Design: docs/plans/Process design draft.md, section 4.1.
FOLLOW_UPS = [  # the candidate stops in the middle of the conversation
    (timedelta(minutes=10), FollowUpStep.REMINDER),
    (timedelta(minutes=30), FollowUpStep.PAUSE),
    (timedelta(hours=20), FollowUpStep.REMINDER),  # still inside the WhatsApp 24-hour window
    (timedelta(hours=24), FollowUpStep.INCOMPLETE),
]
FOLLOW_UPS_NO_REPLY = [  # the candidate never answers the greeting
    (timedelta(hours=3), FollowUpStep.REMINDER),  # on WhatsApp, a template approved by Meta
    (timedelta(hours=24), FollowUpStep.INCOMPLETE),
]


# Where a candidate writes when Sonia cannot go on (for example, the LLM keeps failing).
CONTACT_EMAILS = {
    "ES": "seleccion.es@gruposazon.example",
    "MX": "seleccion.mx@gruposazon.example",
}


def zones_for(country: str) -> list[str]:
    """The service zones of a country ("ES" or "MX")."""
    return SERVICE_ZONES[country]


def local_words_for(country: str) -> dict[str, str]:
    """The Spanish words for the licence and the area in a country ("ES" or "MX")."""
    return LOCAL_WORDS[country]


def contact_email_for(country: str) -> str:
    """The contact email of a country ("ES" or "MX")."""
    return CONTACT_EMAILS[country]
