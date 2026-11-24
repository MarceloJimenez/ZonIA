"""The names of the option values and of dates, per language ("es" or "en").

The summary, the prompt and the recruiter dashboard all read them from here.
"""

AVAILABILITY = {
    "es": {"full-time": "Tiempo completo", "part-time": "Medio tiempo", "weekends": "Fines de semana"},
    "en": {"full-time": "Full-time", "part-time": "Part-time", "weekends": "Weekends"},
}

SCHEDULE = {
    "es": {"morning": "Mañana", "afternoon": "Tarde", "evening": "Noche", "flexible": "Flexible"},
    "en": {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "flexible": "Flexible"},
}

MONTHS = {
    "es": [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}

# Monday first, as date.weekday() counts. Only the prompt uses them, in Spanish.
WEEKDAYS = {"es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]}
