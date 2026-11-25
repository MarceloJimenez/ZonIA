"""validate(): which values the candidate gives are not saved, and why."""

from datetime import date, timedelta

import pytest

from zonia.domain.models import ScreeningFields
from zonia.domain.validation import start_date_from, validate

TODAY = date(2026, 11, 22)


@pytest.mark.parametrize("name", ["Ana López", "María José García Ruiz", "José Ángel Núñez"])
def test_a_name_with_a_surname_is_valid(name):
    assert validate(ScreeningFields(full_name=name), TODAY) == {}


@pytest.mark.parametrize("name", ["Ana", "  Ana  "])
def test_a_name_without_a_surname_is_not_valid(name):
    assert "apellido" in validate(ScreeningFields(full_name=name), TODAY)["full_name"]


def test_a_name_with_digits_is_not_valid():
    assert "números" in validate(ScreeningFields(full_name="Ana López 2"), TODAY)["full_name"]


@pytest.mark.parametrize("years", [0, 0.5, 2, 45, 90])
def test_years_a_real_person_can_have_are_valid(years):
    # An older candidate with many years must not be told the answer is wrong.
    assert validate(ScreeningFields(experience_years=years), TODAY) == {}


@pytest.mark.parametrize("years", [-1, 91, 2015])
def test_impossible_years_of_experience_are_not_valid(years):
    # 2015: "desde 2015" read as a number of years.
    assert "experience_years" in validate(ScreeningFields(experience_years=years), TODAY)


@pytest.mark.parametrize("days", [0, 1, 60])
def test_a_start_date_today_or_later_is_valid(days):
    assert validate(ScreeningFields(start_date=TODAY + timedelta(days=days)), TODAY) == {}


def test_a_start_date_in_the_past_is_not_valid():
    assert "start_date" in validate(ScreeningFields(start_date=TODAY - timedelta(days=1)), TODAY)


def test_empty_fields_are_not_checked():
    assert validate(ScreeningFields(), TODAY) == {}


def test_every_invalid_field_is_reported():
    fields = ScreeningFields(full_name="Ana", experience_years=-2, start_date=TODAY - timedelta(days=3))
    assert set(validate(fields, TODAY)) == {"full_name", "experience_years", "start_date"}


# --- start_date_from(): code builds the start date from the day, month and year the candidate said ---


def test_a_said_year_is_kept_even_if_the_date_has_passed():
    assert start_date_from(3, 3, 2025, TODAY) == date(2025, 3, 3)


@pytest.mark.parametrize(("day", "month", "expected"), [
    (22, 11, date(2026, 11, 22)),  # today
    (1, 12, date(2026, 12, 1)),  # later this year
    (3, 3, date(2027, 3, 3)),  # already passed this year: next year
])
def test_without_a_year_the_date_is_the_next_time_it_comes(day, month, expected):
    assert start_date_from(day, month, None, TODAY) == expected


def test_29_february_without_a_year_is_the_next_leap_year():
    assert start_date_from(29, 2, None, TODAY) == date(2028, 2, 29)


@pytest.mark.parametrize("year", [2027, None])
def test_a_day_that_does_not_exist_gives_none(year):
    assert start_date_from(30, 2, year, TODAY) is None
