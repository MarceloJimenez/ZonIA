"""Stages and statuses. Plain code, no LLM."""

from zonia.config import local_words_for
from zonia.models import OUTSIDE_ZONE, Intent, ScreeningFields, Stage, Status

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


def is_disqualified(fields: ScreeningFields) -> bool:
    """True when the candidate has no licence, or lives outside the service zones."""
    return fields.driver_license is False or fields.service_zone == OUTSIDE_ZONE


def reopens(status: Status, intent: Intent, fields: ScreeningFields) -> bool:
    """True when a message changes what closed the conversation. The candidate is always trusted.

    Disqualified: no reason to disqualify is left (licence is not "no", zone is a service zone). Withdrawn: the candidate wants to continue.
    Qualified: the candidate corrects the summary, or is no longer interested (then withdrawn).
    Incomplete: any message, because the candidate came back (design 4.1). The conversation continues
    from the first empty field. A conversation closed by the turn limit never gets here:
    run_turn_safely stops it before the LLM.
    """
    if status == Status.DISQUALIFIED:
        return not is_disqualified(fields)
    if status == Status.WITHDRAWN:
        return intent == Intent.CONTINUE
    if status == Status.QUALIFIED:
        return intent in {Intent.CORRECTS_SUMMARY, Intent.NOT_INTERESTED}
    return status == Status.INCOMPLETE


def decide(stage: Stage, status: Status, intent: Intent, fields: ScreeningFields) -> tuple[Stage, Status]:
    """Return the new stage and status after one candidate message."""
    reopened = status in FINAL_STATUSES and reopens(status, intent, fields)
    if status in FINAL_STATUSES and not reopened:
        return stage, status
    if status == Status.PAUSED or reopened:
        status = Status.ACTIVE
    if is_disqualified(fields):
        return stage, Status.DISQUALIFIED
    if intent == Intent.NOT_INTERESTED:
        return stage, Status.WITHDRAWN
    if intent == Intent.NOT_NOW:
        return stage, Status.PAUSED
    if stage == Stage.INTRODUCTION and fields.full_name:
        stage = Stage.DATA_COLLECTION
    if stage == Stage.DATA_COLLECTION and not open_fields(fields):
        return Stage.CLOSING, status
    # A reopened candidate must see the summary with the new data before confirming it.
    if stage == Stage.CLOSING and intent == Intent.CONFIRMS_SUMMARY and not reopened:
        return stage, Status.QUALIFIED
    return stage, status


AVAILABILITY_ES = {"full-time": "Tiempo completo", "part-time": "Medio tiempo", "weekends": "Fines de semana"}

SCHEDULE_ES = {"morning": "Mañana", "afternoon": "Tarde", "evening": "Noche", "flexible": "Flexible"}

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


AVAILABILITY_EN = {"full-time": "Full-time", "part-time": "Part-time", "weekends": "Weekends"}

SCHEDULE_EN = {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "flexible": "Flexible"}

MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# The words of the summary, per language.
SUMMARY_TEXT = {
    "es": {
        "name": "Nombre", "license": "{license}", "yes": "Sí", "no": "No", "zone": "Zona",
        "availability": "Disponibilidad", "schedule": "Horario", "experience": "Experiencia",
        "year": "año", "years": "años", "platform": "Plataforma", "start": "Fecha de inicio",
        "opening": "Perfecto{name}. Estos son tus datos:", "question": "¿Está todo correcto?",
    },
    "en": {
        "name": "Name", "license": "Driving licence", "yes": "Yes", "no": "No", "zone": "Area",
        "availability": "Availability", "schedule": "Schedule", "experience": "Experience",
        "year": "year", "years": "years", "platform": "Platform", "start": "Start date",
        "opening": "Great{name}. Here are your details:", "question": "Is everything correct?",
    },
}
AVAILABILITY = {"es": AVAILABILITY_ES, "en": AVAILABILITY_EN}
SCHEDULE = {"es": SCHEDULE_ES, "en": SCHEDULE_EN}


def _date(d, language: str) -> str:
    if language == "en":
        return f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}"
    return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"


def render_summary(fields: ScreeningFields, language: str = "es", country: str = "ES") -> str:
    """The summary message, one field per line, in Spanish ("es") or English ("en").

    In Spanish, the licence uses the country's word: "Carné de conducir" in Spain, "Licencia de manejo" in Mexico.

    Code renders it so the data is exact. The LLM never types it.
    """
    t = SUMMARY_TEXT[language]
    lines = []
    if fields.full_name is not None:
        lines.append(f"- {t['name']}: {fields.full_name}")
    if fields.driver_license is not None:
        license_label = t["license"].format(license=local_words_for(country)["license"].capitalize())
        lines.append(f"- {license_label}: {t['yes'] if fields.driver_license else t['no']}")
    if fields.city_zone is not None:
        lines.append(f"- {t['zone']}: {fields.city_zone}")
    if fields.availability:
        lines.append(f"- {t['availability']}: {', '.join(AVAILABILITY[language][a] for a in fields.availability)}")
    if fields.schedule:
        lines.append(f"- {t['schedule']}: {', '.join(SCHEDULE[language][s] for s in fields.schedule)}")
    if fields.experience_years is not None:
        unit = t["year"] if fields.experience_years == 1 else t["years"]
        years = f"{fields.experience_years:g}"
        if language == "es":
            years = years.replace(".", ",")
        lines.append(f"- {t['experience']}: {years} {unit}")
        if fields.experience_years > 0 and fields.experience_platform is not None:
            lines.append(f"- {t['platform']}: {fields.experience_platform}")
    if fields.start_date is not None:
        lines.append(f"- {t['start']}: {_date(fields.start_date, language)}")
    first_name = fields.full_name.split()[0] if fields.full_name else ""
    opening = t["opening"].format(name=f", {first_name}" if first_name else "")
    return "\n".join([opening, *lines, t["question"]])
