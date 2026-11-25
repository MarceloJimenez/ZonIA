"""The business types: stages, statuses, intents, recruiter outcomes, message roles, countries, languages,
and the candidate's fields (ScreeningFields)."""

from datetime import date
from enum import StrEnum
from typing import Literal

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


class Role(StrEnum):
    """Who wrote a message in the conversation."""

    CANDIDATE = "candidate"
    AGENT = "agent"  # Sonia, or code writing as Sonia


class ScreeningFields(BaseModel):
    full_name: str | None = Field(
        None,
        description="Nombre y apellidos con mayúscula inicial (por ejemplo \"María Fernanda Torres\"), "
        "aunque el candidato lo escriba en minúsculas.",
    )

    driver_license: bool | None = Field(
        None,
        description=(
            "true si el candidato dice que tiene permiso para conducir, con cualquier palabra y en los dos países: "
            "carné, carnet, licencia, licencia de manejo o permiso de conducir. false si dice que no lo tiene."
        ),
    )

    license_type: str | None = Field(
        None,
        description=(
            "Para qué vehículos es el carné, con las palabras del candidato (por ejemplo \"moto\", \"coche\" "
            "o \"profesional\"). Solo el vehículo: nunca la palabra carné, carnet ni licencia. "
            "Opcional: rellénalo solo si el candidato lo dice. Nunca lo preguntes aparte."
        ),
    )

    city_zone: str | None = Field(
        None,
        description=(
            "Lugar donde vive: el barrio o la colonia y la ciudad, separados por una coma y con los nombres "
            "bien escritos (por ejemplo \"Gràcia, Barcelona\" o \"Coyoacán, Ciudad de México\"), aunque el "
            "candidato escriba abreviaturas como \"bcn\" o \"CDMX\". Si dice solo una ciudad que está fuera "
            f"de todas las zonas de servicio, pon la ciudad y service_zone '{OUTSIDE_ZONE}', y no preguntes "
            "el barrio ni la colonia. Si es vago (por ejemplo \"cerca del centro\"), "
            "déjalo vacío, deja vacío service_zone y pregunta la ciudad y el barrio o la colonia."
        ),
    )

    # Filled together with city_zone. turn_model() narrows it to the country's zones.
    service_zone: str | None = None

    availability: list[Literal["full-time", "part-time", "weekends"]] | None = Field(
        None,
        description=(
            "Rellénalo solo si el candidato dice claramente una o más de estas opciones: tiempo completo (full-time), "
            "medio tiempo (part-time) o fines de semana (weekends). Si responde de otra forma, por ejemplo con días "
            "concretos (\"martes y jueves\") o con horas, déjalo vacío y no elijas tú la opción: "
            "en tu respuesta, pídele que elija una de las tres."
        ),
    )

    schedule: list[Literal["morning", "afternoon", "evening", "flexible"]] | None = None

    experience_years: float | None = None

    experience_platform: str | None = Field(
        None,
        description="Plataforma o empresa donde trabajó, con su nombre bien escrito (por ejemplo \"Rappi\", "
        "\"Uber Eats\"), aunque el candidato lo escriba en minúsculas.",
    )

    # The LLM gives day, month and year apart (zonia.agent.schema.SaidDate); code builds this date.
    start_date: date | None = None

    @property
    def first_name(self) -> str | None:
        """The first word of full_name, to greet the candidate. None when there is no name yet."""
        return self.full_name.split()[0] if self.full_name else None


Country = Literal["ES", "MX"]  # the countries Sonia serves; decides the service zones and the local words
Language = Literal["es", "en"]  # the languages Sonia speaks (docs/ASSIGNMENT.md:94)
