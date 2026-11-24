"""Text sent to the LLM: the system prompt, the per-turn instructions and the directives for call 2."""

from zonia.config import JOB_FACTS, PERSONALITY, local_words_for
from zonia.flow import AVAILABILITY_ES, FIELD_ORDER, MONTHS_ES, SCHEDULE_ES, open_fields
from datetime import date

from zonia.models import ScreeningFields, Status

# Same for every client. Design: docs/plans/Process design draft.md, section 2.
FIXED_RULES = [
    "Escribe mensajes cortos, como en WhatsApp.",
    "Di \"yo\" para hablar de ti y \"nosotros\" para hablar de Grupo Sazón.",
    "No intentes ser graciosa.",
    "Pide perdón solo cuando el error es tuyo (no entendiste algo, o algo técnico falló). "
    "Una vez y en pocas palabras. Si el candidato corrige un dato suyo, no pidas perdón: "
    "confirma el dato nuevo.",
    "Para una mala noticia, como una descalificación, di \"lamentablemente\", no \"lo siento\".",
    "No prometas el puesto y no opines sobre el candidato.",
]


def build_system(personality: dict[str, str]) -> str:
    """The system prompt: the client's personality, then the fixed rules."""
    lines = [f"{dimension.capitalize()}: {text}" for dimension, text in personality.items()]
    rules = [f"- {rule}" for rule in FIXED_RULES]
    return "\n".join(["Personalidad:", *lines, "", "Reglas:", *rules])


SYSTEM = build_system(PERSONALITY)

# Code adds the review email and the case code after the LLM's reply (zonia.turn).
NO_CONTACT = "No des ningún correo, teléfono ni código: se añaden después de tu mensaje."

DIRECTIVES = {
    Status.DISQUALIFIED: (
        "El candidato no puede continuar porque el puesto exige {license}. "
        "Díselo directamente, de tú y con amabilidad, usando \"lamentablemente\". "
        f"Agradécele su tiempo y no hagas más preguntas. {NO_CONTACT}"
    ),
    # {license} is filled per country by directive().
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

# {license} and {area} are the country's words (config.LOCAL_WORDS), filled by field_label().
FIELD_LABELS_ES = {
    "full_name": "nombre completo",
    "driver_license": "si tiene {license} vigente",
    "city_zone": "ciudad y {area} donde vive",
    "availability": "disponibilidad (tiempo completo, medio tiempo o fines de semana)",
    "schedule": "horario preferido (mañana, tarde, noche o flexible)",
    "experience_years": "años de experiencia como repartidor",
    "experience_platform": "plataforma o empresa donde trabajó de repartidor",
    "start_date": "fecha en que puede empezar",
}


# Added to an open field in the "Falta" list: how to ask it.
ASK_HINTS_ES = {
    "driver_license": " (en la misma pregunta, dile que si quiere puede decir para qué vehículo)",
}


def field_label(name: str, country: str) -> str:
    """How the prompt names a field, with the country's words."""
    return FIELD_LABELS_ES[name].format(**local_words_for(country))


def local_words(country: str) -> str:
    """The line that tells every call which words to use for the licence and the area."""
    words = local_words_for(country)
    return (
        f"En español, cuando nombres el permiso para conducir, di \"{words['license']}\". "
        f"Cuando preguntes en qué parte de la ciudad vive, di \"{words['area']}\". "
        "No uses estas palabras para nada más. "
        "El candidato puede usar otras palabras (carné, carnet, licencia, permiso, barrio, colonia): "
        "entiéndelas todas y no le corrijas."
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


DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _today_es(today: date) -> str:
    return f"Hoy es {DAYS_ES[today.weekday()]}, {today.day} de {MONTHS_ES[today.month - 1]} de {today.year} ({today.isoformat()})."


def _value_es(name: str, value: object) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    if name == "availability":
        return ", ".join(AVAILABILITY_ES[a] for a in value)
    if name == "schedule":
        return ", ".join(SCHEDULE_ES[s] for s in value)
    return str(value)


def facts_section(facts: list[str]) -> str:
    """The job facts Sonia may give, and what to do with a question they do not answer."""
    return "\n".join([
        "Datos del puesto que puedes dar:",
        *(f"- {fact}" for fact in facts),
        "Si el candidato pregunta algo, responde en una frase y solo con estos datos. "
        "Si el dato no está aquí (por ejemplo el sueldo o los horarios), di con tus palabras que, como asistente "
        "de IA, no tienes esa información y que estás aquí para ayudarte con tu solicitud. "
        "Si ya lo dijiste antes en la conversación, no repitas la misma frase: dilo más corto y con otras palabras. "
        "No digas quién se lo explicará ni cuándo, y no menciones otros pasos del proceso. "
        "Nunca inventes datos. Después sigue con la pregunta pendiente.",
    ])


LANGUAGE_NAMES_ES = {"es": "español", "en": "inglés"}


def language_section(language: str) -> str:
    """Which language call 1 replies in. Design: docs/plans/Process design draft.md, section 4.3."""
    current = LANGUAGE_NAMES_ES[language]
    return (
        f"Idioma actual de la conversación: {current}. "
        "Mira solo el último mensaje del candidato, no los anteriores. "
        "Responde en el idioma de ese mensaje, español o inglés, aunque la conversación vaya en otro. "
        "Si mezcla los dos, responde en el que más palabras tiene. "
        f"Si escribe en otro idioma (por ejemplo portugués), responde en {current} "
        "y empieza diciendo en una frase que solo puedes atender en español o en inglés."
    )


def reply_language(language: str) -> str:
    """The line added to every call 2 instruction: call 1 already decided the language."""
    return f"Responde en {LANGUAGE_NAMES_ES[language]}."


# Call 1 when every field is known: the candidate is checking the summary.
# Code shows the summary again only when a value changes, so a "no" alone reaches the LLM.
CLOSING_RULES = (
    "Ya tienes todos los datos y el candidato está revisando su resumen. "
    "Si dice que algo está mal pero no dice qué, pregúntale qué dato quiere cambiar. "
    "Si da un valor nuevo, ponlo en fields. "
    "No escribas el resumen: el código lo muestra cuando cambia un dato."
)


def turn_instructions(
    fields: ScreeningFields, today: date, facts: list[str] = JOB_FACTS, language: str = "es", country: str = "ES"
) -> str:
    """What call 1 must know this turn: today's date, the language and the country's words,
    the known fields, the open ones in order, and the job facts."""
    known = [
        f"- {field_label(name, country)}: {_value_es(name, getattr(fields, name))}"
        for name in FIELD_ORDER
        if getattr(fields, name) is not None
    ]
    missing = [
        f"{i}. {field_label(name, country)}{ASK_HINTS_ES.get(name, '')}"
        for i, name in enumerate(open_fields(fields), start=1)
    ]
    parts = [_today_es(today), language_section(language), local_words(country)]
    if known:
        parts.append("Ya sabes:\n" + "\n".join(known))
    if missing:
        parts.append("Falta, en este orden:\n" + "\n".join(missing))
    parts.append(facts_section(facts))
    if missing:
        parts.append(
            "Pregunta por los 1 o 2 primeros que falten y que el mensaje del candidato no traiga ya. "
            "Si falta el nombre, pregunta solo el nombre. Nunca preguntes algo que ya sabes. "
            "No leas la lista de zonas de servicio al candidato: pregunta dónde vive."
        )
    else:
        parts.append(CLOSING_RULES)
    parts.append(
        "Si el mensaje del candidato no responde a tu última pregunta y parece ruido, otra conversación "
        "o algo que no se entiende, empieza tu respuesta diciéndolo en pocas palabras "
        "(por ejemplo: \"Creo que hay otra conversación cerca y no te he entendido bien\"). "
        "Luego haz la pregunta otra vez con otras palabras."
    )
    return "\n\n".join(parts)
