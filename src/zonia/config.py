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


def zones_for(country: str) -> list[str]:
    """The service zones of a country ("ES" or "MX")."""
    return SERVICE_ZONES[country]
