"""ScreeningFields.first_name: the word the summary and the reminders greet the candidate with."""

from zonia.domain.models import ScreeningFields


def test_first_name_is_the_first_word_of_the_full_name():
    assert ScreeningFields(full_name="María Fernanda Torres").first_name == "María"


def test_first_name_of_a_single_name_is_that_name():
    assert ScreeningFields(full_name="Ana").first_name == "Ana"


def test_first_name_is_none_without_a_name():
    assert ScreeningFields().first_name is None


def test_first_name_is_not_saved_with_the_fields():
    assert "first_name" not in ScreeningFields(full_name="Ana López").model_dump()
