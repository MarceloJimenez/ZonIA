"""Checks on what the candidate said. Plain code, no LLM.

These are the candidate's errors, not the LLM's: the LLM read the message correctly,
so asking it again cannot fix them. Code drops the value and Sonia asks again.
Rules: docs/plans/Process design draft.md, section 3.
"""

from datetime import date

from zonia.domain.models import ScreeningFields

# No person can reach it (driving from 18 would mean being over 108), so it treats no one worse
# for their age. It catches misread numbers: "desde 2015" read as 2015 years.
MAX_EXPERIENCE_YEARS = 90


def start_date_from(day: int, month: int, year: int | None, today: date) -> date | None:
    """The start date from what the candidate said, or None if that day does not exist (for example 30 February).

    With a year, that year, even if the date has passed: validate() then rejects it.
    Without a year, the next time that day comes, from today on (a 29 February can be up to 4 years ahead).
    """
    if year is not None:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for y in range(today.year, today.year + 5):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def validate(fields: ScreeningFields, today: date) -> dict[str, str]:
    """The fields that are not valid, each with the reason in Spanish, for Sonia to say."""
    problems = {}
    name = fields.full_name
    if name is not None:
        if any(c.isdigit() for c in name):
            problems["full_name"] = "un nombre no lleva números"
        elif len(name.split()) < 2:
            problems["full_name"] = "falta al menos un apellido"
    years = fields.experience_years
    if years is not None and not 0 <= years <= MAX_EXPERIENCE_YEARS:
        problems["experience_years"] = "ese número de años no es posible"
    if fields.start_date is not None and fields.start_date < today:
        problems["start_date"] = "esa fecha ya pasó; tiene que ser hoy o más adelante"
    return problems
