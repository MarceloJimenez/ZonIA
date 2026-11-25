"""What call 1 reads each turn: the date, the language, the country's words, the fields and the job facts."""

from datetime import date

from zonia.config import JOB_FACTS, local_words_for
from zonia.domain.flow import FIELD_ORDER, open_fields
from zonia.domain.models import OUTSIDE_ZONE, Country, Language, ScreeningFields
from zonia.texts.labels import AVAILABILITY, MONTHS, SCHEDULE, WEEKDAYS

# {license} and {area} are the country's words (config.LOCAL_WORDS), filled by field_label().
FIELD_LABELS_ES = {
    "full_name": "nombre completo",
    "driver_license": "{license} vigente (sí o no)",
    "city_zone": "ciudad y {area}",
    "availability": "disponibilidad (tiempo completo, medio tiempo o fines de semana)",
    "schedule": "horario preferido (mañana, tarde, noche o flexible)",
    "experience_years": "años de experiencia como repartidor",
    "experience_platform": "plataforma o empresa de su experiencia como repartidor",
    "start_date": "fecha de inicio",
}

# Added to an open field in the "Falta" list: how to ask it.
ASK_HINTS_ES = {
    "driver_license": " (en la misma pregunta, dile que si quiere puede decir para qué vehículo)",
}

LANGUAGE_NAMES_ES = {"es": "español", "en": "inglés"}

# Call 1 when every field is known: the candidate is checking the summary.
# Code shows the summary again only when a value changes, so a "no" alone reaches the LLM.
CLOSING_RULES = (
    "Ya tienes todos los datos y el candidato está revisando su resumen. "
    "Si dice que algo está mal pero no dice qué, pregúntale qué dato quiere cambiar. "
    "Si da un valor nuevo, ponlo en fields. "
    "No escribas el resumen: el código lo muestra cuando cambia un dato."
)


def field_label(name: str, country: Country) -> str:
    """How the prompt names a field, with the country's words."""
    return FIELD_LABELS_ES[name].format(**local_words_for(country))


def local_words(country: Country) -> str:
    """The line that tells every call which words to use for the licence and the area."""
    words = local_words_for(country)
    return (
        f"En español, cuando nombres el permiso para conducir, di \"{words['license']}\". "
        f"Cuando preguntes en qué parte de la ciudad vive, di \"{words['area']}\". "
        "No uses estas palabras para nada más. "
        "El candidato puede usar otras palabras (carné, carnet, licencia, permiso, barrio, colonia): "
        "entiéndelas todas y no le corrijas."
    )


def _today_es(today: date) -> str:
    return f"Hoy es {WEEKDAYS['es'][today.weekday()]}, {today.day} de {MONTHS['es'][today.month - 1]} de {today.year} ({today.isoformat()})."


def _value_es(name: str, value: object) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    if name == "availability":
        return ", ".join(AVAILABILITY["es"][a] for a in value)
    if name == "schedule":
        return ", ".join(SCHEDULE["es"][s] for s in value)
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


def language_section(language: Language) -> str:
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


def turn_instructions(
    fields: ScreeningFields, today: date, facts: list[str] = JOB_FACTS, language: Language = "es", country: Country = "ES"
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
            "No leas la lista de zonas de servicio al candidato: pregunta dónde vive. "
            "Si dice solo una ciudad que está fuera de todas las zonas de servicio, no preguntes el "
            f"{local_words_for(country)['area']}: guarda la ciudad en city_zone y '{OUTSIDE_ZONE}' en service_zone."
        )
    else:
        parts.append(CLOSING_RULES)
    parts.append(
        "Si el mensaje del candidato no responde a tu última pregunta y parece ruido, otra conversación "
        "o algo que no se entiende, empieza tu respuesta diciéndolo en pocas palabras "
        "(por ejemplo: \"Creo que hay otra conversación cerca y no te he entendido bien\"). "
        "Luego haz la pregunta otra vez con una frase distinta de la anterior: no copies tu última pregunta. "
        "Si la pregunta tiene opciones, puedes repetir las opciones."
    )
    return "\n\n".join(parts)
