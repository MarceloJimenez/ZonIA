"""The shape of call 1's reply: Turn and turn_model. Its Spanish descriptions are text the LLM reads."""

from functools import cache
from typing import Literal

from pydantic import BaseModel, Field, create_model, model_validator

from zonia.config import zones_for
from zonia.domain.models import OUTSIDE_ZONE, Country, Intent, ScreeningFields


class Turn(BaseModel):
    fields: ScreeningFields

    intent: Intent = Field(
        description=(
            "Lo que el candidato quiere con su último mensaje. "
            "none: responde a la pregunta o dice otra cosa, y no es ninguno de los casos siguientes. "
            "continue: quiere seguir con su candidatura, también después de retirarla "
            "(por ejemplo \"sí, seguimos\" o \"era una broma, mi candidatura sigue\"). "
            "not_now: ahora no puede seguir y quiere seguir más tarde. "
            "not_interested: ya no le interesa el puesto o retira su candidatura. "
            "confirms_summary: dice que el resumen de sus datos es correcto. "
            "corrects_summary: dice que un dato del resumen está mal."
        )
    )

    reply: str = Field(
        description="Tu respuesta al candidato, escrita en el idioma que te indican las instrucciones, aunque estas "
        "instrucciones estén en español."
    )


class SaidDate(BaseModel):
    """The start date as the candidate says it. Code builds the date (zonia.domain.validation.start_date_from)."""

    day: int = Field(ge=1, le=31)
    month: int = Field(ge=1, le=12)
    year: int | None = Field(
        None, description="Solo si el candidato dice el año. Si no lo dice, déjalo vacío: no lo calcules tú."
    )


START_DATE_DESCRIPTION = (
    "La fecha en que puede empezar, con el día, el mes y el año que dice el candidato. "
    "Si dice una fecha relativa (por ejemplo \"mañana\" o \"el lunes\"), calcula el día, el mes y el año desde hoy."
)


SERVICE_ZONE_DESCRIPTION = (
    "La zona de servicio que contiene el lugar de city_zone (ciudad, barrio, colonia, provincia o estado). "
    f"Si el lugar no está en ninguna zona de la lista, '{OUTSIDE_ZONE}'. "
    "Rellénalo siempre que rellenes city_zone."
)


@cache
def turn_model(country: Country) -> type[Turn]:
    """Turn for one country: service_zone accepts only that country's zones or OUTSIDE_ZONE.

    Any other value fails validation, and Pydantic AI asks the LLM again.
    start_date comes as a SaidDate: the LLM gives the day, month and year it heard, and code builds the date.
    """
    zone = Literal[tuple([*zones_for(country), OUTSIDE_ZONE])]
    fields_model = create_model(
        f"ScreeningFields{country}",
        __base__=ScreeningFields,
        __validators__={"_zone_with_place": model_validator(mode="after")(_zone_with_place)},
        service_zone=(zone | None, Field(None, description=SERVICE_ZONE_DESCRIPTION)),
        start_date=(SaidDate | None, Field(None, description=START_DATE_DESCRIPTION)),
    )
    return create_model(f"Turn{country}", __base__=Turn, fields=(fields_model, ...))


def _zone_with_place(fields: ScreeningFields) -> ScreeningFields:
    if (fields.city_zone is None) != (fields.service_zone is None):
        raise ValueError("city_zone y service_zone van juntos: rellena los dos o ninguno.")
    return fields
