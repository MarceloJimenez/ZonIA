"""Models for Zonia"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel


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

    reply: str
