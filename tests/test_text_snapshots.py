"""Every text Sonia or the LLM gets from code stays exactly the same.

Each text is kept in tests/text_snapshots/<name>.txt. A change of one letter fails the test.
To write the files again after a change made on purpose: UPDATE_SNAPSHOTS=1 uv run pytest tests/test_text_snapshots.py
"""

import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from zonia.config import GREETING, contact_email_for
from zonia.flow import render_summary
from zonia.followups import reminder_text
from zonia.models import ScreeningFields, Status, turn_model
from zonia.prompt import SYSTEM, directive, invalid_directive, reply_language, turn_instructions
from zonia.turn import CONTACT_REPLY, FAILURE_REPLY, LIMIT_REPLY, REVIEW_REPLY, Conversation
from zonia.validation import validate

SNAPSHOTS = Path(__file__).parent / "text_snapshots"
TODAY = date(2026, 11, 24)
CASE_CODE = "K7M2Q9XR"
COUNTRIES = ["ES", "MX"]
LANGUAGES = ["es", "en"]

EMPTY = ScreeningFields()
PARTIAL = ScreeningFields(full_name="Ana López", driver_license=True, license_type="moto")
ALL_BUT_ONE = ScreeningFields(
    full_name="Ana López",
    driver_license=True,
    city_zone="Chamberí, Madrid",
    service_zone="Comunidad de Madrid",
    availability=["full-time", "weekends"],
    schedule=["morning", "flexible"],
    experience_years=2,
    experience_platform="Glovo",
)
COMPLETE = ALL_BUT_ONE.model_copy(update={"start_date": date(2026, 12, 1)})
FIELD_SETS = {"empty": EMPTY, "partial": PARTIAL, "all_but_one": ALL_BUT_ONE, "complete": COMPLETE}

# Values that validate() rejects, so invalid_directive() gets the real reasons.
INVALID = ScreeningFields(full_name="Ana", experience_years=2015, start_date=date(2026, 11, 1))
NO_LICENSE = ScreeningFields(full_name="Ana López", driver_license=False)


def _texts() -> dict[str, Callable[[], str]]:
    """Snapshot name -> the code that writes the text today."""
    texts: dict[str, Callable[[], str]] = {"system": lambda: SYSTEM}

    for country in COUNTRIES:
        for set_name, fields in FIELD_SETS.items():
            texts[f"turn_instructions.{set_name}.{country}"] = (
                lambda f=fields, c=country: turn_instructions(f, TODAY, country=c)
            )
        texts[f"turn_instructions.partial.en.{country}"] = (
            lambda c=country: turn_instructions(PARTIAL, TODAY, language="en", country=c)
        )
        for status in Status:
            texts[f"directive.{status}.{country}"] = lambda s=status, c=country: str(directive(s, NO_LICENSE, c))
        texts[f"directive.zone.{country}"] = lambda c=country: str(directive(Status.DISQUALIFIED, PARTIAL, c))
        texts[f"invalid_directive.{country}"] = lambda c=country: invalid_directive(validate(INVALID, TODAY), c)
        texts[f"schema.{country}"] = lambda c=country: json.dumps(
            turn_model(c).model_json_schema(), ensure_ascii=False, indent=2
        )

    for language in LANGUAGES:
        texts[f"reply_language.{language}"] = lambda lang=language: reply_language(lang)
        for country in COUNTRIES:
            texts[f"render_summary.{language}.{country}"] = (
                lambda lang=language, c=country: render_summary(COMPLETE, lang, c)
            )
            email = contact_email_for(country)
            texts[f"reply.review.{language}.{country}"] = (
                lambda lang=language, e=email: REVIEW_REPLY[lang].format(email=e, code=CASE_CODE)
            )
            texts[f"reply.limit.{language}.{country}"] = lambda lang=language, e=email: LIMIT_REPLY[lang].format(email=e)
            texts[f"reply.contact.{language}.{country}"] = (
                lambda lang=language, e=email: CONTACT_REPLY[lang].format(email=e)
            )
        texts[f"reply.failure.{language}"] = lambda lang=language: FAILURE_REPLY[lang]
        for set_name in ["empty", "partial", "all_but_one", "complete"]:
            texts[f"reminder.{set_name}.{language}"] = lambda s=set_name, lang=language: reminder_text(
                Conversation(fields=FIELD_SETS[s], turns=3, language=lang)
            )

    texts["reminder.no_reply"] = lambda: reminder_text(Conversation(turns=0))
    texts["reminder.partial.es.MX"] = lambda: reminder_text(
        Conversation(fields=ScreeningFields(full_name="Ana López"), turns=1, country="MX")
    )
    texts["greeting"] = lambda: "\n---\n".join(GREETING)
    return texts


TEXTS = _texts()


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_text_is_unchanged(name):
    path = SNAPSHOTS / f"{name}.txt"
    text = TEXTS[name]()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"No snapshot for {name}. Write it with UPDATE_SNAPSHOTS=1."
    assert text == path.read_text(encoding="utf-8"), f"The text {name} changed. Diff: {path}"


def test_every_snapshot_has_a_text():
    """A snapshot left without a text means a text was lost or renamed."""
    names = {p.stem for p in SNAPSHOTS.glob("*.txt")}
    assert names == set(TEXTS)
