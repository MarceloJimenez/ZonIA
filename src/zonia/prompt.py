"""Text sent to the LLM: the system prompt, the per-turn instructions and the directives for call 2."""

from zonia.flow import AVAILABILITY_ES, FIELD_ORDER, SCHEDULE_ES, open_fields
from zonia.models import ScreeningFields, Status

SYSTEM = (
    "Eres Sonia, la asistente de IA de Grupo Sazón. "
    "Entrevistas a candidatos para el puesto de repartidor. "
    "Escribe mensajes cortos, como en WhatsApp."
)

DIRECTIVES = {
    Status.DISQUALIFIED: (
        "El candidato no puede continuar porque el puesto exige carnet de conducir. "
        "Díselo con amabilidad, agradécele su tiempo y no hagas más preguntas."
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
    "Díselo con amabilidad, agradécele su tiempo y no hagas más preguntas."
)

FIELD_LABELS_ES = {
    "full_name": "nombre completo",
    "driver_license": "si tiene carnet de conducir vigente",
    "city_zone": "ciudad y zona donde vive",
    "availability": "disponibilidad (tiempo completo, medio tiempo o fines de semana)",
    "schedule": "horario preferido (mañana, tarde, noche o flexible)",
    "experience_years": "años de experiencia como repartidor",
    "experience_platform": "plataforma o empresa donde trabajó de repartidor",
    "start_date": "fecha en que puede empezar",
}


def directive(status: Status, fields: ScreeningFields) -> str | None:
    """The instruction for call 2, or None. A disqualified candidate with a licence was cut by zone."""
    if status == Status.DISQUALIFIED and fields.driver_license is not False:
        return ZONE_DIRECTIVE
    return DIRECTIVES.get(status)


def _value_es(name: str, value: object) -> str:
    if isinstance(value, bool):
        return "sí" if value else "no"
    if name == "availability":
        return ", ".join(AVAILABILITY_ES[a] for a in value)
    if name == "schedule":
        return ", ".join(SCHEDULE_ES[s] for s in value)
    return str(value)


def turn_instructions(fields: ScreeningFields) -> str:
    """What call 1 must know this turn: the known fields and the open ones, in order."""
    known = [
        f"- {FIELD_LABELS_ES[name]}: {_value_es(name, getattr(fields, name))}"
        for name in FIELD_ORDER
        if getattr(fields, name) is not None
    ]
    missing = [f"{i}. {FIELD_LABELS_ES[name]}" for i, name in enumerate(open_fields(fields), start=1)]
    parts = []
    if known:
        parts.append("Ya sabes:\n" + "\n".join(known))
    if missing:
        parts.append("Falta, en este orden:\n" + "\n".join(missing))
    parts.append(
        "Pregunta por los 1 o 2 primeros que falten y que el mensaje del candidato no traiga ya. "
        "Si falta el nombre, pregunta solo el nombre. Nunca preguntes algo que ya sabes. "
        "No leas la lista de zonas de servicio al candidato: pregunta dónde vive."
    )
    return "\n\n".join(parts)
