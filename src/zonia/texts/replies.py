"""What Sonia says with fixed text, written by code, in Spanish ("es") or English ("en").

No LLM call writes these replies, so they use the conversation's last language.
{email} is the country's contact email (config.contact_email_for); {code} is the case code.
"""

from zonia.config import NO_REPLY_REMINDER, local_words_for
from zonia.domain.conversation import Conversation
from zonia.domain.flow import open_fields

# A new disqualification: code adds this to Sonia's reply.
REVIEW_REPLY = {
    "es": "Si quieres que una persona revise tu caso, escribe a {email} con el código {code}.",
    "en": "If you want a person to review your case, write to {email} with the code {code}.",
}

FAILURE_REPLY = {
    "es": "Perdona, he tenido un problema técnico. ¿Puedes repetir tu último mensaje?",
    "en": "Sorry, I had a technical problem. Can you send your last message again?",
}
LIMIT_REPLY = {
    "es": "Hemos llegado al límite de esta conversación. Si quieres seguir con tu candidatura, escribe a {email}.",
    "en": "We have reached the limit of this conversation. If you want to continue your application, write to {email}.",
}
CONTACT_REPLY = {
    "es": (
        "Seguimos con un problema técnico. Escríbenos a {email} con tu nombre y tu teléfono, "
        "y una persona del equipo seguirá con tu candidatura. También puedes intentarlo aquí más tarde."
    ),
    "en": (
        "We still have a technical problem. Write to us at {email} with your name and phone number, "
        "and a person from the team will continue your application. You can also try here again later."
    ),
}

# A message with a photo, audio or other file and no text. Code writes the reply; no LLM call.
# Other formats are in docs/Backlog.md.
TEXT_ONLY_REPLY = {
    "es": "Por ahora solo puedo leer mensajes de texto. ¿Me lo escribes?",
    "en": "For now I can only read text messages. Could you write it?",
}


# What is missing, as the reminder says it. {license} and {area} are the country's words.
NEXT_ES = {
    "full_name": "tu nombre completo",
    "driver_license": "saber si tienes {license}",
    "city_zone": "saber en qué ciudad y {area} vives",
    "availability": "tu disponibilidad",
    "schedule": "tu horario preferido",
    "experience_years": "tu experiencia como repartidor",
    "experience_platform": "dónde trabajaste como repartidor",
    "start_date": "tu fecha de inicio",
}
NEXT_EN = {
    "full_name": "your full name",
    "driver_license": "whether you have a driving licence",
    "city_zone": "the city and area where you live",
    "availability": "your availability",
    "schedule": "your preferred schedule",
    "experience_years": "your experience as a delivery driver",
    "experience_platform": "where you worked as a delivery driver",
    "start_date": "your start date",
}
REMINDER_TEXT = {
    "es": {
        "ask": "¿Seguimos{name}?",
        "last": "Solo falta {thing}.",
        "next": "Lo siguiente es {thing}.",
        "confirm": "Solo falta que confirmes tus datos.",
    },
    "en": {
        "ask": "Shall we continue{name}?",
        "last": "There is only {thing} left.",
        "next": "Next is {thing}.",
        "confirm": "You only need to confirm your details.",
    },
}




def reminder_text(c: Conversation) -> str:
    """The reminder for a conversation the candidate started: it names what is missing, like the design's example."""
    if c.turns == 0:
        return NO_REPLY_REMINDER
    t = REMINDER_TEXT[c.language]
    ask = t["ask"].format(name=f", {c.fields.first_name}" if c.fields.first_name else "")
    missing = open_fields(c.fields)
    if not missing:
        return f"{ask} {t['confirm']}"
    names = NEXT_ES if c.language == "es" else NEXT_EN
    thing = names[missing[0]].format(**local_words_for(c.country))
    return f"{ask} {t['last' if len(missing) == 1 else 'next'].format(thing=thing)}"
