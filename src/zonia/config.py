"""Business settings that change without a code change. Example data, to be replaced by Grupo Sazón's real list."""

# Service zones per country: large regions, so the list stays short.
# The assignment only says "Must be within service areas" (docs/ASSIGNMENT.md:30).
SERVICE_ZONES = {
    "ES": [
        "Andalucía",
        "Cataluña",
        "Comunidad de Madrid",
        "Comunidad Valenciana",
        "País Vasco",
        "Galicia",
    ],
    "MX": [
        "Ciudad de México",
        "Estado de México",
        "Jalisco",
        "Nuevo León",
        "Puebla",
        "Guanajuato",
    ],
}


# Where a candidate writes when Sonia cannot go on (for example, the LLM keeps failing).
CONTACT_EMAILS = {
    "ES": "seleccion.es@gruposazon.example",
    "MX": "seleccion.mx@gruposazon.example",
}


# Sonia's personality: the 5 dimensions a client can change.
# Design: docs/plans/Process design draft.md, section 2. The fixed rules live in prompt.py.
PERSONALITY = {
    "identidad": (
        "Eres Sonia, la asistente de IA de Grupo Sazón. "
        "Entrevistas a candidatos para el puesto de repartidor. "
        "Usas el nombre del candidato a veces, no en cada mensaje."
    ),
    "carácter": "Cercana, profesional y alentadora.",
    "tono": (
        "Informal y respetuoso. Al descalificar: empático. "
        "Al calificar: celebras el resultado, sin exagerar."
    ),
    "registro": "Tuteas al candidato. Sin jerga y sin expresiones propias de España o de México.",
    "expresión": (
        "Sin emojis. Pocos signos de exclamación. "
        "Confirmaciones cortas y variadas, como \"Perfecto\" o \"Anotado\"."
    ),
}


def zones_for(country: str) -> list[str]:
    """The service zones of a country ("ES" or "MX")."""
    return SERVICE_ZONES[country]


def contact_email_for(country: str) -> str:
    """The contact email of a country ("ES" or "MX")."""
    return CONTACT_EMAILS[country]
