"""Models for Zonia"""

from datetime import date
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel


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

    city_zone: Optional[str] = None

    availability: Optional[list[Literal["full-time", "part-time", "weekends"]]] = None

    schedule: Optional[list[Literal["morning", "afternoon", "evening", "flexible"]]] = None

    experience_years: Optional[float] = None

    experience_platform: Optional[str] = None

    start_date: Optional[date] = None


class Turn(BaseModel):
    fields: ScreeningFields

    intent: Intent

    reply: str
