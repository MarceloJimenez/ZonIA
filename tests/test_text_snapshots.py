"""Every text code writes for the candidate stays exactly the same: the summary, the fixed replies,
the reminders and the greeting. The texts the LLM reads are in test_prompt_version.py.

Each text is kept in tests/text_snapshots/<name>.txt. A change of one letter fails the test.
To write the files again after a change made on purpose: UPDATE_SNAPSHOTS=1 uv run pytest tests/test_text_snapshots.py
"""

import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from zonia.config import GREETING, contact_email_for
from zonia.texts.summary import render_summary
from zonia.domain.models import ScreeningFields
from zonia.domain.conversation import Conversation
from zonia.texts.replies import CONTACT_REPLY, FAILURE_REPLY, LIMIT_REPLY, REVIEW_REPLY, reminder_text

SNAPSHOTS = Path(__file__).parent / "text_snapshots"
SNAPSHOTS_TODAY = date(2026, 11, 24)  # the date in the texts the LLM reads (test_prompt_version.py)
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

# Values that validate() rejects, so invalid_directive() gets the real reasons (test_prompt_version.py).
INVALID = ScreeningFields(full_name="Ana", experience_years=2015, start_date=date(2026, 11, 1))
NO_LICENSE = ScreeningFields(full_name="Ana López", driver_license=False)


def _texts() -> dict[str, Callable[[], str]]:
    """Snapshot name -> the code that writes the text today."""
    texts: dict[str, Callable[[], str]] = {}

    for language in LANGUAGES:
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
