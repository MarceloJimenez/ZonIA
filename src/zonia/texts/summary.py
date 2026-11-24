"""The summary message: the candidate's data, one field per line. Code writes it, so the data is exact."""

from zonia.config import local_words_for
from zonia.domain.models import ScreeningFields

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
        answer = t["yes"] if fields.driver_license else t["no"]
        if fields.driver_license and fields.license_type:
            answer += f" ({fields.license_type})"
        lines.append(f"- {license_label}: {answer}")
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
