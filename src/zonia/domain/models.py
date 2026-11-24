"""Models for Zonia"""

from datetime import date
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, Field

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
    TECHNICAL_ERROR = "technical_error"  # 2 failed turns in a row; not final: a good turn goes back to active


class RecruiterOutcome(StrEnum):
    """What the recruiter did with the candidate after Sonia. The recruiter sets it in the dashboard."""

    CALLED = "called"
    NO_ANSWER = "no_answer"
    INTERVIEW = "interview"
    HIRED = "hired"
    REJECTED = "rejected"


class Intent(StrEnum):
    NONE = "none"
    CONTINUE = "continue"
    NOT_NOW = "not_now"
    NOT_INTERESTED = "not_interested"
    CONFIRMS_SUMMARY = "confirms_summary"
    CORRECTS_SUMMARY = "corrects_summary"


class ScreeningFields(BaseModel):
    full_name: Optional[str] = Field(
        None,
        description="Nombre y apellidos con mayúscula inicial (por ejemplo \"María Fernanda Torres\"), "
        "aunque el candidato lo escriba en minúsculas.",
    )

    driver_license: Optional[bool] = None

    license_type: Optional[str] = Field(
        None,
        description=(
            "Para qué vehículos es el carné, con las palabras del candidato (por ejemplo \"moto\", \"coche\" "
            "o \"profesional\"). Opcional: rellénalo solo si el candidato lo dice. Nunca lo preguntes aparte."
        ),
    )

    city_zone: Optional[str] = Field(
        None,
        description=(
            "Lugar donde vive, con las palabras del candidato. Si es vago (por ejemplo \"cerca del centro\"), "
            "déjalo vacío, deja vacío service_zone y pregunta la ciudad y el barrio o la colonia."
        ),
    )

    # Filled together with city_zone. turn_model() narrows it to the country's zones.
    service_zone: Optional[str] = None

    availability: Optional[list[Literal["full-time", "part-time", "weekends"]]] = Field(
        None,
        description=(
            "Rellénalo solo si el candidato dice claramente una o más de estas opciones: tiempo completo (full-time), "
            "medio tiempo (part-time) o fines de semana (weekends). Si responde de otra forma, por ejemplo con días "
            "concretos (\"martes y jueves\") o con horas, déjalo vacío y no elijas tú la opción: "
            "en tu respuesta, pídele que elija una de las tres."
        ),
    )

    schedule: Optional[list[Literal["morning", "afternoon", "evening", "flexible"]]] = None

    experience_years: Optional[float] = None

    experience_platform: Optional[str] = Field(
        None,
        description="Plataforma o empresa donde trabajó, con su nombre bien escrito (por ejemplo \"Rappi\", "
        "\"Uber Eats\"), aunque el candidato lo escriba en minúsculas.",
    )

    start_date: Optional[date] = Field(
        None,
        description=(
            "Si el candidato no dice el año, usa la próxima vez que llega esa fecha, contando desde hoy: "
            "si este año ya pasó, es la del año que viene."
        ),
    )

    @property
    def first_name(self) -> str | None:
        """The first word of full_name, to greet the candidate. None when there is no name yet."""
        return self.full_name.split()[0] if self.full_name else None


Language = Literal["es", "en"]  # the languages Sonia speaks (docs/ASSIGNMENT.md:94)
