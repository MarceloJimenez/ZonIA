"""Spanish and English: call 1 says the candidate's language; the reply and the texts written by code follow it.

Design: docs/plans/Process design draft.md, section 4.3.
"""

import asyncio
from datetime import date

from test_failures import FailingLLM, http, run
from test_turn import COMPLETE, NO_LICENCE, FakeLLM, make_agent
from zonia.config import MAX_TURNS, contact_email_for
from zonia.texts.summary import render_summary
from zonia.domain.models import ScreeningFields, Stage
from zonia.prompt import turn_instructions
from zonia.domain.conversation import Conversation
from zonia.texts.replies import CONTACT_REPLY, FAILURE_REPLY, LIMIT_REPLY
from zonia.turn import run_turn

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


def test_call_1_is_told_the_current_language_and_the_rule_for_other_languages():
    text = turn_instructions(ScreeningFields(), date.today(), language="en")
    assert "Idioma actual de la conversación: inglés." in text
    assert "Si mezcla los dos, responde en el que más palabras tiene." in text
    assert "responde en inglés y empieza diciendo en una frase que solo puedes atender en español o en inglés" in text


def test_the_language_of_call_1_is_kept_and_sent_with_the_next_turn():
    fake = FakeLLM([{"language": "en"}, {"language": "en"}])
    conversation = Conversation()
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Hi, I'm Ana López"))
    assert turn.language == conversation.language == "en"
    asyncio.run(run_turn(make_agent(fake), conversation, "Yes, I have a licence"))
    assert "Idioma actual de la conversación: inglés." in fake.instructions[-1]


def test_call_2_is_told_to_reply_in_the_language_of_call_1():
    fake = FakeLLM([NO_LICENCE | {"language": "en"}])
    asyncio.run(run_turn(make_agent(fake), Conversation(), "I'm Luis and I have no licence"))
    assert fake.instructions[-1].endswith("Responde en inglés.")


def test_the_review_email_is_in_english_when_the_candidate_writes_in_english():
    conversation = Conversation(country="MX")
    fake = FakeLLM([NO_LICENCE | {"language": "en"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "I'm Luis and I have no licence"))
    assert turn.reply.endswith(f"write to {contact_email_for('MX')} with the code {conversation.case_code}.")


def test_the_summary_is_in_english_when_the_candidate_writes_in_english():
    all_fields = COMPLETE.model_dump(mode="json", exclude_none=True)
    conversation = Conversation()
    fake = FakeLLM([{"fields": all_fields, "language": "en"}])
    turn = asyncio.run(run_turn(make_agent(fake), conversation, "Everything in one message"))
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
