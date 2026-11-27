"""What call 1 reads each turn: the date, the language, the country's words, the fields and the job facts."""

from datetime import date

from zonia.config import JOB_FACTS, local_words_for
from zonia.domain.flow import FIELD_ORDER, open_fields
from zonia.domain.models import OUTSIDE_ZONE, Country, Language, ScreeningFields, Status
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

# The examples the LLM copies word for word, in each language: we write both, the LLM translates nothing.
CONFIRMATION_EXAMPLES = {
    "es": '"Ok", "Okay", "Perfecto", "Súper", "Genial, gracias" o "Anotado"',
    "en": '"Ok", "Great", "Perfect", "Got it", "Thanks" o "Noted"',
}
NOISE_EXAMPLES = {
    "es": "Creo que hay otra conversación cerca y no te he entendido bien",
    "en": "I think there is another conversation nearby and I did not understand you",
}

# The last line of call 1's instructions, in the language of the reply.
LANGUAGE_RULES = {
    "es": (
        "Responde en español, aunque mensajes anteriores de la conversación estén en otro idioma. "
        "Si el último mensaje del candidato está en un idioma que no es español ni inglés (por ejemplo portugués), "
        "empieza diciendo en una frase que solo puedes atender en español o en inglés."
    ),
    "en": (
        "Reply in English, even if earlier messages in the conversation are in another language. "
        "If the candidate's last message is in a language that is not Spanish or English (for example Portuguese), "
        "start by saying in one sentence that you can only help in Spanish or English."
    ),
}

# Call 1 when every field is known: the candidate is checking the summary.
# Code shows the summary again only when a value changes, so a "no" alone reaches the LLM.
CLOSING_RULES = (
    "Ya tienes todos los datos y el candidato está revisando su resumen. "
    "Si dice que algo está mal pero no dice qué, pregúntale qué dato quiere cambiar. "
    "Si da un valor nuevo, ponlo en fields. "
    "No escribas el resumen: el código lo muestra cuando cambia un dato."
)

# Call 1 when the candidate withdrew: only intent continue reopens the application (zonia.domain.flow.reopens).
WITHDRAWN_RULES = (
    "El candidato retiró su candidatura. "
    "Si ahora dice que quiere seguir, pon intent continue. "
    "Si no pones continue, la candidatura sigue retirada: no le digas que sigue adelante."
)


def field_label(name: str, country: Country) -> str:
    """How the prompt names a field, with the country's words."""
    return FIELD_LABELS_ES[name].format(**local_words_for(country))


# In English, the words for the licence and the area, the same as the English summary (zonia.texts.summary).
LOCAL_WORDS_EN = (
    "In English, when you name the driving permit, say \"driving licence\". "
    "When you ask what part of the city they live in, say \"area\". "
    "Do not copy the Spanish words of the field list. "
    "The candidate can use other words (licence, license, permit, carné, neighbourhood, barrio, colonia): "
    "understand them all and do not correct them."
)


def local_words(country: Country, language: Language = "es") -> str:
    """The line that tells every call which words to use for the licence and the area, in the reply's language."""
    if language == "en":
        return LOCAL_WORDS_EN
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
    """Which language call 1 replies in, written in that language. Code decided it (zonia.domain.language).

    It goes last, so the LLM reads it just before it writes. Design: docs/plans/Process design draft.md, section 4.3.
    """
    return LANGUAGE_RULES[language]


def turn_instructions(
    fields: ScreeningFields,
    today: date,
    facts: list[str] = JOB_FACTS,
    language: Language = "es",
    country: Country = "ES",
    status: Status = Status.ACTIVE,
) -> str:
    """What call 1 must know this turn: today's date, the country's words, the known fields,
    the open ones in order, the job facts, whether the candidate withdrew, and last the language."""
    known = [
        f"- {field_label(name, country)}: {_value_es(name, getattr(fields, name))}"
        for name in FIELD_ORDER
        if getattr(fields, name) is not None
    ]
    missing = [
        f"{i}. {field_label(name, country)}{ASK_HINTS_ES.get(name, '')}"
        for i, name in enumerate(open_fields(fields), start=1)
    ]
    parts = [_today_es(today), local_words(country, language)]
    if known:
        parts.append("Ya sabes:\n" + "\n".join(known))
    if missing:
        parts.append("Falta, en este orden:\n" + "\n".join(missing))
    parts.append(facts_section(facts))
    if missing:
        parts.append(
            "Si el candidato acaba de darte un dato, empieza con una confirmación corta y variada "
            f"(por ejemplo {CONFIRMATION_EXAMPLES[language]}) y luego haz la pregunta. "
            "No repitas la misma confirmación dos veces seguidas. "
            "Pregunta por los 1 o 2 primeros que falten y que el mensaje del candidato no traiga ya. "
            "Si falta el nombre, pregunta solo el nombre. Nunca preguntes algo que ya sabes. "
            "No leas la lista de zonas de servicio al candidato: pregunta dónde vive. "
            "Si dice solo una ciudad que está fuera de todas las zonas de servicio, no preguntes el "
            f"{local_words_for(country)['area']}: guarda la ciudad en city_zone y '{OUTSIDE_ZONE}' en service_zone."
        )
    else:
        parts.append(CLOSING_RULES)
    if status == Status.WITHDRAWN:
        parts.append(WITHDRAWN_RULES)
    parts.append(
        "Si el mensaje del candidato no responde a tu última pregunta y parece ruido, otra conversación "
        "o algo que no se entiende, empieza tu respuesta diciéndolo en pocas palabras "
        f"(por ejemplo: \"{NOISE_EXAMPLES[language]}\"). "
        "Luego haz la pregunta otra vez con una frase distinta de la anterior: no copies tu última pregunta. "
        "Si la pregunta tiene opciones, puedes repetir las opciones."
    )
    parts.append(language_section(language))
    return "\n\n".join(parts)
