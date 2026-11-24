"""The shape of call 1's reply: Turn and turn_model. Its Spanish descriptions are text the LLM reads."""

from functools import cache
from typing import Literal

from pydantic import BaseModel, Field, create_model, model_validator

from zonia.config import zones_for
from zonia.domain.models import OUTSIDE_ZONE, Country, Intent, Language, ScreeningFields


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
    "La zona de servicio que contiene el lugar de city_zone (ciudad, barrio, colonia, provincia o estado). "
    f"Si el lugar no está en ninguna zona de la lista, '{OUTSIDE_ZONE}'. "
    "Rellénalo siempre que rellenes city_zone."
)


@cache
def turn_model(country: Country) -> type[Turn]:
    """Turn for one country: service_zone accepts only that country's zones or OUTSIDE_ZONE.

    Any other value fails validation, and Pydantic AI asks the LLM again.
    """
    zone = Literal[tuple([*zones_for(country), OUTSIDE_ZONE])]
    fields_model = create_model(
        f"ScreeningFields{country}",
        __base__=ScreeningFields,
        __validators__={"_zone_with_place": model_validator(mode="after")(_zone_with_place)},
        service_zone=(zone | None, Field(None, description=SERVICE_ZONE_DESCRIPTION)),
    )
    return create_model(f"Turn{country}", __base__=Turn, fields=(fields_model, ...))


def _zone_with_place(fields: ScreeningFields) -> ScreeningFields:
    if (fields.city_zone is None) != (fields.service_zone is None):
        raise ValueError("city_zone y service_zone van juntos: rellena los dos o ninguno.")
    return fields
