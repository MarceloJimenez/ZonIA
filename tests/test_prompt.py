"""What the LLM is told: the system prompt, and each turn what is known and what is still missing, in order."""

from datetime import date

from zonia.config import JOB_FACTS, PERSONALITY
from zonia.prompt import DIRECTIVES, FIXED_RULES, SYSTEM, ZONE_DIRECTIVE, build_system, directive, invalid_directive, turn_instructions
from zonia.models import ScreeningFields, Status

TODAY = date(2026, 11, 22)


def _missing_section(text: str) -> str:
    # Fails the test when the section is absent, so "x not in missing" cannot pass on an empty text.
    header = "Falta, en este orden:\n"
    assert header in text, f"no missing section in:\n{text}"
    return text.split(header)[1].split("\n\n")[0]


def test_known_data_is_never_listed_as_missing():
    fields = ScreeningFields(full_name="Ana López", driver_license=True, city_zone="Chamberí")
    missing = _missing_section(turn_instructions(fields, TODAY))
    assert "nombre" not in missing
    assert "carné" not in missing
    assert "zona" not in missing


def test_known_values_are_given_to_the_llm():
    fields = ScreeningFields(full_name="Ana López", driver_license=True, availability=["part-time"])
    text = turn_instructions(fields, TODAY)
    assert "Ana López" in text
    assert "Medio tiempo" in text


def test_missing_fields_are_listed_in_order():
    # With some experience, the platform comes right after it, before the start date.
    missing = _missing_section(turn_instructions(ScreeningFields(full_name="Ana", experience_years=3), TODAY))
    assert missing.splitlines() == [
        "1. si tiene carné de conducir vigente (en la misma pregunta, dile que si quiere puede decir para qué vehículo)",
        "2. ciudad y barrio donde vive",
        "3. disponibilidad (tiempo completo, medio tiempo o fines de semana)",
        "4. horario preferido (mañana, tarde, noche o flexible)",
        "5. plataforma o empresa donde trabajó de repartidor",
        "6. fecha en que puede empezar",
    ]


def test_platform_is_asked_only_after_some_experience():
    assert "plataforma" not in turn_instructions(ScreeningFields(full_name="Ana", experience_years=0), TODAY)
    assert "plataforma" in _missing_section(turn_instructions(ScreeningFields(full_name="Ana", experience_years=3), TODAY))


def test_nothing_missing_when_complete():
    fields = ScreeningFields(
        full_name="Ana", driver_license=True, city_zone="Chamberí", availability=["full-time"],
        schedule=["morning"], experience_years=0, start_date=date(2026, 12, 1),
    )
    assert "Falta" not in turn_instructions(fields, TODAY)


def test_the_job_facts_and_the_rule_for_other_questions_are_given_every_turn():
    text = turn_instructions(ScreeningFields(full_name="Ana"), TODAY)
    for fact in JOB_FACTS:
        assert f"- {fact}" in text
    assert "Nunca inventes datos." in text
    assert "no tienes esa información" in text


def test_the_job_facts_come_from_the_setting():
    text = turn_instructions(ScreeningFields(), TODAY, facts=["El sueldo es X."])
    assert "- El sueldo es X." in text
    assert JOB_FACTS[0] not in text


# --- System prompt ----------------------------------------------------------


def test_the_system_prompt_has_every_personality_dimension_and_every_fixed_rule():
    for text in [*PERSONALITY.values(), *FIXED_RULES]:
        assert text in SYSTEM


def test_a_client_personality_replaces_the_default_and_keeps_the_fixed_rules():
    system = build_system({"identidad": "Eres Leo, el asistente de IA de Otra Empresa."})
    assert "Leo" in system
    assert "Sonia" not in system
    assert all(rule in system for rule in FIXED_RULES)


def test_disqualifying_directives_say_lamentablemente():
    # Design rule: bad news uses "lamentablemente", not "lo siento".
    for text in [DIRECTIVES[Status.DISQUALIFIED], ZONE_DIRECTIVE]:
        assert "lamentablemente" in text


# --- The country's words (design 4.3): "carné de conducir" and "barrio" in Spain, "licencia de manejo" and "colonia" in Mexico ---


def test_call_1_uses_the_words_of_the_country():
    spain = turn_instructions(ScreeningFields(full_name="Ana"), TODAY, country="ES")
    mexico = turn_instructions(ScreeningFields(full_name="Ana"), TODAY, country="MX")
    assert "1. si tiene carné de conducir vigente" in spain and "2. ciudad y barrio donde vive" in spain
    assert "1. si tiene licencia de manejo vigente" in mexico and "2. ciudad y colonia donde vive" in mexico
    assert 'cuando nombres el permiso para conducir, di "licencia de manejo".' in mexico
    assert "carné de conducir" not in mexico


def test_the_disqualification_directive_uses_the_word_of_the_country():
    no_licence = ScreeningFields(driver_license=False)
    assert "exige licencia de manejo" in directive(Status.DISQUALIFIED, no_licence, "MX")
    assert "exige carné de conducir" in directive(Status.DISQUALIFIED, no_licence, "ES")


def test_the_invalid_value_directive_uses_the_word_of_the_country():
    assert "ciudad y colonia donde vive" in invalid_directive({"city_zone": "vacío"}, "MX")
