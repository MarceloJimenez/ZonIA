"""Models for Zonia"""

from datetime import date
from enum import StrEnum
from functools import cache
from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model, model_validator

from zonia.config import zones_for

OUTSIDE_ZONE = "outside"  # service_zone value when the place is in no service zone


class Stage(StrEnum):
    INTRODUCTION = "introduction"
    DATA_COLLECTION = "data_collection"
    CLOSING = "closing"


class Status(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    WITHDRAWN = "withdrawn"
    INCOMPLETE = "incomplete"


class Intent(StrEnum):
    NONE = "none"
    CONTINUE = "continue"
    NOT_NOW = "not_now"
    NOT_INTERESTED = "not_interested"
    CONFIRMS_SUMMARY = "confirms_summary"
    CORRECTS_SUMMARY = "corrects_summary"


class ScreeningFields(BaseModel):
    full_name: Optional[str] = None

    driver_license: Optional[bool] = None

    city_zone: Optional[str] = Field(
        None,
        description=(
            "Lugar donde vive, con las palabras del candidato. Si es vago (por ejemplo \"cerca del centro\"), "
            "déjalo vacío, deja vacío service_zone y pregunta la ciudad y el barrio."
        ),
    )

    # Filled together with city_zone. turn_model() narrows it to the country's zones.
    service_zone: Optional[str] = None

    availability: Optional[list[Literal["full-time", "part-time", "weekends"]]] = None

    schedule: Optional[list[Literal["morning", "afternoon", "evening", "flexible"]]] = None

    experience_years: Optional[float] = None

    experience_platform: Optional[str] = None

    start_date: Optional[date] = None


Language = Literal["es", "en"]  # the languages Sonia speaks (docs/ASSIGNMENT.md:94)


class Turn(BaseModel):
    fields: ScreeningFields

    intent: Intent

    language: Language = Field(
        description=(
            "Idioma del último mensaje del candidato, sin mirar los anteriores: es (español) o en (inglés). "
            "Si mezcla los dos, el que más palabras tiene: \"Yes, I live in Madrid, gracias\" es en. "
            "Si escribe en otro idioma, el idioma actual de la conversación."
        )
    )

    reply: str


SERVICE_ZONE_DESCRIPTION = (
    "La zona de servicio que contiene el lugar de city_zone (ciudad, barrio o provincia). "
    f"Si el lugar no está en ninguna zona de la lista, '{OUTSIDE_ZONE}'. "
    "Rellénalo siempre que rellenes city_zone."
)


@cache
def turn_model(country: str) -> type[Turn]:
    """Turn for one country: service_zone accepts only that country's zones or OUTSIDE_ZONE.

    Any other value fails validation, and Pydantic AI asks the LLM again.
    """
    zone = Literal[tuple([*zones_for(country), OUTSIDE_ZONE])]
    fields_model = create_model(
        f"ScreeningFields{country}",
        __base__=ScreeningFields,
        __validators__={"_zone_with_place": model_validator(mode="after")(_zone_with_place)},
        service_zone=(Optional[zone], Field(None, description=SERVICE_ZONE_DESCRIPTION)),
    )
    return create_model(f"Turn{country}", __base__=Turn, fields=(fields_model, ...))


def _zone_with_place(fields: ScreeningFields) -> ScreeningFields:
    if (fields.city_zone is None) != (fields.service_zone is None):
        raise ValueError("city_zone y service_zone van juntos: rellena los dos o ninguno.")
    return fields
