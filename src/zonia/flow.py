"""Stages and statuses. Plain code, no LLM."""

from zonia.models import Intent, ScreeningFields, Stage, Status

FIELD_ORDER = [
    "full_name",
    "driver_license",
    "city_zone",
    "availability",
    "schedule",
    "experience_years",
    "experience_platform",
    "start_date",
]

FINAL_STATUSES = {Status.QUALIFIED, Status.DISQUALIFIED, Status.WITHDRAWN, Status.INCOMPLETE}


def open_fields(fields: ScreeningFields) -> list[str]:
    """Fields still empty, in FIELD_ORDER.

    experience_platform is open only if experience_years > 0.
    """
    result = []
    for name in FIELD_ORDER:
        if name == "experience_platform" and not (fields.experience_years or 0) > 0:
            continue
        if getattr(fields, name) is None:
            result.append(name)
    return result


def decide(stage: Stage, status: Status, intent: Intent, fields: ScreeningFields) -> tuple[Stage, Status]:
    """Return the new stage and status after one candidate message."""
    if status == Status.PAUSED:
        status = Status.ACTIVE
    if fields.driver_license is False:
        return stage, Status.DISQUALIFIED
    if intent == Intent.NOT_INTERESTED:
        return stage, Status.WITHDRAWN
    if intent == Intent.NOT_NOW:
        return stage, Status.PAUSED
    if stage == Stage.INTRODUCTION and fields.full_name:
        stage = Stage.DATA_COLLECTION
    if stage == Stage.DATA_COLLECTION and not open_fields(fields):
        return Stage.CLOSING, status
    if stage == Stage.CLOSING and intent == Intent.CONFIRMS_SUMMARY:
        return stage, Status.QUALIFIED
    return stage, status


AVAILABILITY_ES = {"full-time": "Tiempo completo", "part-time": "Medio tiempo", "weekends": "Fines de semana"}

SCHEDULE_ES = {"morning": "Mañana", "afternoon": "Tarde", "evening": "Noche", "flexible": "Flexible"}

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def render_summary(fields: ScreeningFields) -> str:
    """The summary message, one field per line, in Spanish.

    Code renders it so the data is exact. The LLM never types it.
    """
    lines = []
    if fields.full_name is not None:
        lines.append(f"- Nombre: {fields.full_name}")
    if fields.driver_license is not None:
        lines.append(f"- Carnet de conducir: {'Sí' if fields.driver_license else 'No'}")
    if fields.city_zone is not None:
        lines.append(f"- Zona: {fields.city_zone}")
    if fields.availability:
        lines.append(f"- Disponibilidad: {', '.join(AVAILABILITY_ES[a] for a in fields.availability)}")
    if fields.schedule:
        lines.append(f"- Horario: {', '.join(SCHEDULE_ES[s] for s in fields.schedule)}")
    if fields.experience_years is not None:
        unit = "año" if fields.experience_years == 1 else "años"
        lines.append(f"- Experiencia: {fields.experience_years:g} {unit}")
        if fields.experience_years > 0 and fields.experience_platform is not None:
            lines.append(f"- Plataforma: {fields.experience_platform}")
    if fields.start_date is not None:
        d = fields.start_date
        lines.append(f"- Fecha de inicio: {d.day} de {MONTHS_ES[d.month - 1]} de {d.year}")
    first_name = fields.full_name.split()[0] if fields.full_name else ""
    opening = f"Perfecto, {first_name}. Estos son tus datos:" if first_name else "Perfecto. Estos son tus datos:"
    return "\n".join([opening, *lines, "¿Está todo correcto?"])
