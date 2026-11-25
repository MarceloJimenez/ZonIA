"""What call 2 reads: the directive that replaces call 1's reply when the status changes or a value is not valid."""

from zonia.agent.prompts.call_1 import field_label
from zonia.config import local_words_for
from zonia.domain.models import Country, Language, ScreeningFields, Status

# Code adds the review email and the case code after the LLM's reply (zonia.agent.turn).
NO_CONTACT = "No des ningún correo, teléfono ni código: se añaden después de tu mensaje."

DIRECTIVES = {
    # {license} is filled per country by directive().
    Status.DISQUALIFIED: (
        "Dile al candidato, hablándole de tú y con amabilidad, que lamentablemente no puede seguir "
        "porque el puesto exige {license}. "
        f"Dale las gracias por su tiempo y no hagas más preguntas. {NO_CONTACT}"
    ),
    Status.WITHDRAWN: (
        "El candidato no quiere seguir. Dale las gracias por su tiempo, de tú, y despídete. "
        "No hagas más preguntas."
    ),
    Status.PAUSED: (
        "El candidato no puede seguir ahora. Dile, de tú, que le escribirás más tarde, y despídete."
    ),
    Status.QUALIFIED: (
        "El candidato ha confirmado sus datos. Dale las gracias y dile, de tú, que el equipo de selección "
        "revisará su candidatura y se pondrá en contacto con él. No hagas más preguntas."
    ),
}

ZONE_DIRECTIVE = (
    "Dile al candidato, hablándole de tú y con amabilidad, que lamentablemente no puede seguir "
    "porque vive fuera de las zonas donde Grupo Sazón tiene servicio. "
    f"Dale las gracias por su tiempo y no hagas más preguntas. {NO_CONTACT}"
)

REPLY_LANGUAGE = {"es": "Responde en español.", "en": "Reply in English."}


def directive(status: Status, fields: ScreeningFields, country: Country = "ES") -> str | None:
    """The instruction for call 2, or None. A disqualified candidate with a licence was cut by zone."""
    if status == Status.DISQUALIFIED and fields.driver_license is not False:
        return ZONE_DIRECTIVE
    text = DIRECTIVES.get(status)
    return text.format(**local_words_for(country)) if text else None


def invalid_directive(problems: dict[str, str], country: Country = "ES") -> str:
    """The instruction for call 2 when code dropped a value the candidate gave."""
    lines = [f"- {field_label(name, country)}: {reason}" for name, reason in problems.items()]
    return "\n".join([
        "Estos datos del candidato no son válidos y no se han guardado:",
        *lines,
        "Dile en una frase el motivo que aparece en la lista, con tus palabras y sin añadir otros motivos. "
        "Después vuelve a preguntar solo por esos datos, hablándole de tú. "
        "No digas que los has anotado.",
    ])


def reply_language(language: Language) -> str:
    """The last line of every call 2 instruction, in the language code decided."""
    return REPLY_LANGUAGE[language]
