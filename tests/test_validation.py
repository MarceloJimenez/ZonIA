"""validate(): which values the candidate gives are not saved, and why."""

from datetime import date, timedelta

import pytest

from zonia.models import ScreeningFields
from zonia.validation import validate

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
