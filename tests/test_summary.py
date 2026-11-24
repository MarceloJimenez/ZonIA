"""The summary the candidate confirms must show their data exactly, in Spanish. English: tests/test_language.py."""

from datetime import date

import pytest

from zonia.texts.summary import render_summary
from zonia.domain.models import ScreeningFields

ANA = ScreeningFields(
    full_name="Ana López",
    driver_license=True,
    city_zone="Chamberí, Madrid",
    availability=["full-time", "weekends"],
    schedule=["morning", "flexible"],
    experience_years=2,
    experience_platform="Glovo",
    start_date=date(2026, 12, 1),
)


def test_every_value_appears_next_to_its_label():
    lines = render_summary(ANA).splitlines()
    for line in [
        "- Nombre: Ana López",
        "- Carné de conducir: Sí",
        "- Zona: Chamberí, Madrid",
        "- Disponibilidad: Tiempo completo, Fines de semana",
        "- Horario: Mañana, Flexible",
        "- Experiencia: 2 años",
        "- Plataforma: Glovo",
        "- Fecha de inicio: 1 de diciembre de 2026",
    ]:
        assert line in lines


@pytest.mark.parametrize(
    ("code", "label"),
    [("full-time", "Tiempo completo"), ("part-time", "Medio tiempo"), ("weekends", "Fines de semana")],
)
def test_every_availability_is_shown_in_spanish(code, label):
    lines = render_summary(ANA.model_copy(update={"availability": [code]})).splitlines()
    assert f"- Disponibilidad: {label}" in lines


@pytest.mark.parametrize(
    ("code", "label"),
    [("morning", "Mañana"), ("afternoon", "Tarde"), ("evening", "Noche"), ("flexible", "Flexible")],
)
def test_every_schedule_is_shown_in_spanish(code, label):
    lines = render_summary(ANA.model_copy(update={"schedule": [code]})).splitlines()
    assert f"- Horario: {label}" in lines


def test_licence_no_is_shown_as_no():
    text = render_summary(ANA.model_copy(update={"driver_license": False}))
    assert "Carné de conducir: No" in text


def test_platform_is_hidden_when_there_is_no_experience():
    # The LLM may still extract a platform word ("ninguna"); it must not reach the summary.
    text = render_summary(ANA.model_copy(update={"experience_years": 0, "experience_platform": "ninguna"}))
    assert "Plataforma" not in text
    assert "0 años" in text


def test_one_year_is_singular():
    assert "1 año\n" in render_summary(ANA.model_copy(update={"experience_years": 1}))


def test_half_years_use_a_decimal_comma():
    assert "1,5 años" in render_summary(ANA.model_copy(update={"experience_years": 1.5}))


def test_summary_greets_by_first_name():
    assert render_summary(ANA).startswith("Perfecto, Ana.")


def test_summary_asks_for_confirmation():
    assert render_summary(ANA).rstrip().endswith("¿Está todo correcto?")


def test_the_licence_uses_the_word_of_the_country():
    assert "- Licencia de manejo: Sí" in render_summary(ANA, country="MX").splitlines()
    assert "- Carné de conducir: Sí" in render_summary(ANA, country="ES").splitlines()


def test_the_licence_type_goes_next_to_yes_when_the_candidate_gave_it():
    lines = render_summary(ANA.model_copy(update={"license_type": "moto y coche"})).splitlines()
    assert "- Carné de conducir: Sí (moto y coche)" in lines


def test_the_licence_type_is_optional():
    assert "- Carné de conducir: Sí" in render_summary(ANA).splitlines()
