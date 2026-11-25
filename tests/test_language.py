"""Spanish and English: code decides the language of the candidate's message; the reply and the texts written by code follow it.

Design: docs/plans/Process design draft.md, section 4.3.
"""

import asyncio
from datetime import date

from test_failures import FailingLLM, http, run
from test_turn import COMPLETE, NO_LICENCE, FakeLLM, llm_fields, make_agent
from zonia.config import MAX_TURNS, contact_email_for
from zonia.texts.summary import render_summary
from zonia.domain.models import ScreeningFields, Stage
from zonia.agent.prompts.call_1 import CONFIRMATION_EXAMPLES, LANGUAGE_RULES, NOISE_EXAMPLES, turn_instructions
from zonia.domain.conversation import Conversation
from zonia.texts.replies import CONTACT_REPLY, FAILURE_REPLY, LIMIT_REPLY
from zonia.agent.turn import run_turn

ANA = ScreeningFields(
    full_name="Ana López",
    driver_license=True,
    city_zone="Chamberí, Madrid",
    availability=["full-time", "weekends"],
    schedule=["morning", "flexible"],
    experience_years=1.5,
    experience_platform="Glovo",
    start_date=date(2026, 12, 1),
)


def test_the_english_summary_has_every_value_next_to_its_label():
    lines = render_summary(ANA, "en").splitlines()
    assert lines[0] == "Great, Ana. Here are your details:"
    for line in [
        "- Name: Ana López",
        "- Driving licence: Yes",
        "- Area: Chamberí, Madrid",
        "- Availability: Full-time, Weekends",
        "- Schedule: Morning, Flexible",
        "- Experience: 1.5 years",
        "- Platform: Glovo",
        "- Start date: December 1, 2026",
    ]:
        assert line in lines
    assert lines[-1] == "Is everything correct?"


def test_the_spanish_summary_is_the_default():
    assert render_summary(ANA) == render_summary(ANA, "es")
    assert "- Experiencia: 1,5 años" in render_summary(ANA).splitlines()


ENGLISH = "Hello, my name is Luis and I do not have a driving licence yet"
UNCLEAR = "Glovo"  # one word: the language is kept


def test_call_1_ends_with_the_language_rule_written_in_that_language():
    english = turn_instructions(ScreeningFields(), date.today(), language="en")
    spanish = turn_instructions(ScreeningFields(), date.today(), language="es")
    assert english.endswith(LANGUAGE_RULES["en"])
    assert spanish.endswith(LANGUAGE_RULES["es"])
    assert "Reply in English," in LANGUAGE_RULES["en"]
    assert "you can only help in Spanish or English" in LANGUAGE_RULES["en"]


def test_call_1_gets_the_examples_in_the_language_of_the_reply():
    for language, other in [("en", "es"), ("es", "en")]:
        text = turn_instructions(ScreeningFields(), date.today(), language=language)
        assert CONFIRMATION_EXAMPLES[language] in text and CONFIRMATION_EXAMPLES[other] not in text
        assert NOISE_EXAMPLES[language] in text and NOISE_EXAMPLES[other] not in text


def test_call_1_gets_the_language_of_the_message_and_the_conversation_keeps_it():
    fake = FakeLLM([{}, {}])
    conversation = Conversation()
    turn = asyncio.run(run_turn(make_agent(fake), conversation, ENGLISH))
    assert turn.language == conversation.language == "en"
    assert "Reply in English," in fake.instructions[-1]
    asyncio.run(run_turn(make_agent(fake), conversation, UNCLEAR))
    assert conversation.language == "en"
    assert "Reply in English," in fake.instructions[-1]


def test_a_clear_spanish_message_changes_the_language_back():
    fake = FakeLLM([{}])
    conversation = Conversation(language="en")
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Bueno, mejor sigo en español. Tengo carné de coche"))
    assert turn.language == conversation.language == "es"
    assert "Responde en español," in fake.instructions[-1]


def test_call_2_is_told_to_reply_in_the_language_of_the_message():
    fake = FakeLLM([NO_LICENCE])
    asyncio.run(run_turn(make_agent(fake), Conversation(), ENGLISH))
    assert fake.instructions[-1].endswith("Reply in English.")


def test_the_review_email_is_in_english_when_the_candidate_writes_in_english():
    conversation = Conversation(country="MX")
    fake = FakeLLM([NO_LICENCE])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, ENGLISH))
    assert turn.reply.endswith(f"write to {contact_email_for('MX')} with the code {conversation.case_code}.")


def test_the_summary_is_in_english_when_the_candidate_writes_in_english():
    all_fields = llm_fields(COMPLETE)
    conversation = Conversation()
    fake = FakeLLM([{"fields": all_fields}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Here is everything in one message"))
    assert turn.stage == Stage.CLOSING
    assert turn.reply == render_summary(conversation.fields, "en")


def test_the_fixed_replies_use_the_last_language_of_the_conversation():
    conversation = Conversation(language="en", country="MX")
    first, _ = run(FailingLLM([http(400)]), conversation)
    second, _ = run(FailingLLM([http(400)]), conversation)
    assert first.reply == FAILURE_REPLY["en"]
    assert second.reply == CONTACT_REPLY["en"].format(email=contact_email_for("MX"))
    assert first.language == "en"


def test_the_limit_reply_uses_the_last_language_of_the_conversation():
    conversation = Conversation(language="en", turns=MAX_TURNS - 1)
    turn, _ = run(FailingLLM([]), conversation)
    assert turn.reply == LIMIT_REPLY["en"].format(email=contact_email_for("ES"))
