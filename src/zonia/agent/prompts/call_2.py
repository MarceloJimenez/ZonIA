"""What call 2 reads: the directive that replaces call 1's reply when the status changes or a value is not valid."""

from zonia.agent.prompts.call_1 import LANGUAGE_NAMES_ES, field_label
from zonia.config import local_words_for
from zonia.domain.models import ScreeningFields, Status

# Code adds the review email and the case code after the LLM's reply (zonia.agent.turn).
NO_CONTACT = "No des ningún correo, teléfono ni código: se añaden después de tu mensaje."

DIRECTIVES = {
    # {license} is filled per country by directive().
    Status.DISQUALIFIED: (
        "El candidato no puede continuar porque el puesto exige {license}. "
        "Díselo directamente, de tú y con amabilidad, usando \"lamentablemente\". "
        f"Agradécele su tiempo y no hagas más preguntas. {NO_CONTACT}"
    ),
    Status.WITHDRAWN: (
        "El candidato no quiere continuar. Agradécele su tiempo y despídete. No hagas más preguntas."
    ),
    Status.PAUSED: (
        "El candidato no puede seguir ahora. Confírmale que le escribirás más tarde y despídete."
    ),
    Status.QUALIFIED: (
        "El candidato ha confirmado sus datos. Agradécele y dile que el equipo de selección "
        "revisará su candidatura y le contactará. No hagas más preguntas."
    ),
}

ZONE_DIRECTIVE = (
    "El candidato vive fuera de las zonas donde Grupo Sazón tiene servicio. "
    "Díselo directamente, de tú y con amabilidad, usando \"lamentablemente\". "
    f"Agradécele su tiempo y no hagas más preguntas. {NO_CONTACT}"
)


def directive(status: Status, fields: ScreeningFields, country: str = "ES") -> str | None:
    """The instruction for call 2, or None. A disqualified candidate with a licence was cut by zone."""
    if status == Status.DISQUALIFIED and fields.driver_license is not False:
        return ZONE_DIRECTIVE
    text = DIRECTIVES.get(status)
    return text.format(**local_words_for(country)) if text else None


def invalid_directive(problems: dict[str, str], country: str = "ES") -> str:
    """The instruction for call 2 when code dropped a value the candidate gave."""
    lines = [f"- {field_label(name, country)}: {reason}" for name, reason in problems.items()]
    return "\n".join([
        "Estos datos del candidato no son válidos y no se han guardado:",
        *lines,
        "Dile en una frase qué esperas y vuelve a preguntar solo por esos datos. "
        "No digas que los has anotado.",
    ])


def reply_language(language: str) -> str:
    """The line added to every call 2 instruction: call 1 already decided the language."""
    return f"Responde en {LANGUAGE_NAMES_ES[language]}."
