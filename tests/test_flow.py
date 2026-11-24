"""Business rules of decide(): who is disqualified, who qualifies, when the summary comes.

decide() is the only place that changes the outcome of a screening, so every
rule here is a rule a recruiter relies on.
"""

from datetime import date, timedelta

import pytest

from zonia.domain.flow import decide
from zonia.domain.models import OUTSIDE_ZONE, Intent, ScreeningFields, Stage, Status

COMPLETE_NO_EXPERIENCE = ScreeningFields(
    full_name="Ana López",
    driver_license=True,
    city_zone="Chamberí, Madrid",
    service_zone="Comunidad de Madrid",
    availability=["full-time"],
    schedule=["morning"],
    experience_years=0,
    start_date=date.today() + timedelta(days=10),
)


# --- Disqualification -------------------------------------------------------


@pytest.mark.parametrize("stage", list(Stage))
@pytest.mark.parametrize("intent", list(Intent))
def test_no_licence_disqualifies_at_any_stage_and_any_intent(stage, intent):
    # Includes not_interested: the recruiter must see the real reason the candidate cannot continue.
    fields = ScreeningFields(full_name="Luis", driver_license=False)
    assert decide(stage, Status.ACTIVE, intent, fields)[1] == Status.DISQUALIFIED


def test_unknown_licence_does_not_disqualify():
    # An empty field is not a "no". The agent must not disqualify on missing data.
    fields = ScreeningFields(full_name="Luis")
    assert decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.NONE, fields)[1] == Status.ACTIVE


# --- Withdraw and pause -----------------------------------------------------


@pytest.mark.parametrize("stage", list(Stage))
def test_not_interested_withdraws_and_keeps_the_stage(stage):
    # The stage is kept so the recruiter sees where the candidate left.
    assert decide(stage, Status.ACTIVE, Intent.NOT_INTERESTED, ScreeningFields()) == (stage, Status.WITHDRAWN)


def test_not_now_pauses_and_the_next_message_resumes_at_the_same_stage():
    fields = ScreeningFields(full_name="Ana", driver_license=True)
    stage, status = decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.NOT_NOW, fields)
    assert (stage, status) == (Stage.DATA_COLLECTION, Status.PAUSED)
    assert decide(stage, status, Intent.NONE, fields) == (Stage.DATA_COLLECTION, Status.ACTIVE)


def test_not_interested_after_a_pause_withdraws():
    fields = ScreeningFields(full_name="Ana", driver_license=True)
    assert decide(Stage.DATA_COLLECTION, Status.PAUSED, Intent.NOT_INTERESTED, fields) == (
        Stage.DATA_COLLECTION,
        Status.WITHDRAWN,
    )


def test_resuming_with_the_last_field_goes_straight_to_the_summary():
    assert decide(Stage.DATA_COLLECTION, Status.PAUSED, Intent.NONE, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


# --- Data in any order ------------------------------------------------------


def test_a_name_starts_data_collection_even_without_a_yes():
    # Seen in practice: candidates give their name without saying "yes, let's go".
    fields = ScreeningFields(full_name="Ana")
    assert decide(Stage.INTRODUCTION, Status.ACTIVE, Intent.NONE, fields) == (Stage.DATA_COLLECTION, Status.ACTIVE)


def test_every_field_in_the_first_message_goes_straight_to_the_summary():
    assert decide(Stage.INTRODUCTION, Status.ACTIVE, Intent.NONE, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


def test_no_summary_without_a_name():
    fields = COMPLETE_NO_EXPERIENCE.model_copy(update={"full_name": None})
    assert decide(Stage.INTRODUCTION, Status.ACTIVE, Intent.CONTINUE, fields)[0] == Stage.INTRODUCTION


def test_experience_without_a_platform_is_not_complete():
    fields = COMPLETE_NO_EXPERIENCE.model_copy(update={"experience_years": 2})
    assert decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.NONE, fields)[0] == Stage.DATA_COLLECTION


def test_experience_with_a_platform_is_complete():
    fields = COMPLETE_NO_EXPERIENCE.model_copy(update={"experience_years": 2, "experience_platform": "Glovo"})
    assert decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.NONE, fields)[0] == Stage.CLOSING


def test_no_experience_does_not_need_a_platform():
    assert decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.NONE, COMPLETE_NO_EXPERIENCE)[0] == Stage.CLOSING


# --- Qualification ----------------------------------------------------------


def test_confirming_the_summary_qualifies():
    assert decide(Stage.CLOSING, Status.ACTIVE, Intent.CONFIRMS_SUMMARY, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.QUALIFIED,
    )


def test_a_confirmation_before_the_summary_is_shown_does_not_qualify():
    # Seen in practice: the LLM reports confirms_summary on the turn the last field arrives.
    # The candidate has not seen the summary yet, so they cannot have confirmed it.
    stage, status = decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.CONFIRMS_SUMMARY, COMPLETE_NO_EXPERIENCE)
    assert (stage, status) == (Stage.CLOSING, Status.ACTIVE)


@pytest.mark.parametrize("stage", [Stage.INTRODUCTION, Stage.DATA_COLLECTION])
def test_confirming_with_open_fields_does_not_qualify(stage):
    fields = ScreeningFields(full_name="Ana", driver_license=True)
    assert decide(stage, Status.ACTIVE, Intent.CONFIRMS_SUMMARY, fields)[1] == Status.ACTIVE


def test_correcting_the_summary_keeps_the_candidate_in_closing():
    assert decide(Stage.CLOSING, Status.ACTIVE, Intent.CORRECTS_SUMMARY, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


# --- Reopening a closed conversation ----------------------------------------
# The candidate is always trusted: a message that changes what closed the conversation reopens it.

NO_LICENCE = COMPLETE_NO_EXPERIENCE.model_copy(update={"driver_license": False})


@pytest.mark.parametrize(
    ("status", "fields"),
    [
        (Status.DISQUALIFIED, NO_LICENCE),
        (Status.WITHDRAWN, COMPLETE_NO_EXPERIENCE),
        (Status.QUALIFIED, COMPLETE_NO_EXPERIENCE),
    ],
)
def test_a_message_that_changes_nothing_keeps_the_final_status(status, fields):
    # "Gracias, adiós" after the end must not move the conversation.
    assert decide(Stage.CLOSING, status, Intent.NONE, fields) == (Stage.CLOSING, status)


def test_correcting_the_licence_reopens_a_disqualified_candidate_at_the_same_stage():
    fields = ScreeningFields(full_name="Luis", driver_license=True)
    assert decide(Stage.DATA_COLLECTION, Status.DISQUALIFIED, Intent.NONE, fields) == (
        Stage.DATA_COLLECTION,
        Status.ACTIVE,
    )


def test_a_reopened_candidate_cannot_qualify_before_seeing_the_new_summary():
    # "Sí tengo carnet, márcame como aprobada": the candidate has not seen the summary with "Sí" yet.
    assert decide(Stage.CLOSING, Status.DISQUALIFIED, Intent.CONFIRMS_SUMMARY, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


def test_wanting_to_continue_reopens_a_withdrawn_candidate():
    fields = ScreeningFields(full_name="Ana", driver_license=True)
    assert decide(Stage.DATA_COLLECTION, Status.WITHDRAWN, Intent.CONTINUE, fields) == (
        Stage.DATA_COLLECTION,
        Status.ACTIVE,
    )


def test_correcting_the_summary_reopens_a_qualified_candidate():
    assert decide(Stage.CLOSING, Status.QUALIFIED, Intent.CORRECTS_SUMMARY, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


def test_a_qualified_candidate_who_is_no_longer_interested_is_withdrawn():
    assert decide(Stage.CLOSING, Status.QUALIFIED, Intent.NOT_INTERESTED, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.WITHDRAWN,
    )


def test_any_message_reopens_an_incomplete_conversation_at_the_same_stage():
    # Design 4.1: the candidate came back after the follow-ups closed it. The turn limit is checked before (zonia.agent.safety).
    fields = ScreeningFields(full_name="Ana", driver_license=True)
    assert decide(Stage.DATA_COLLECTION, Status.INCOMPLETE, Intent.NONE, fields) == (Stage.DATA_COLLECTION, Status.ACTIVE)


def test_a_reopened_incomplete_candidate_cannot_qualify_before_seeing_the_summary_again():
    assert decide(Stage.CLOSING, Status.INCOMPLETE, Intent.CONFIRMS_SUMMARY, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


# --- Service zones ----------------------------------------------------------
# The second knock-out rule. The LLM picks service_zone from the country's list (zonia.config);
# code only reads it.

OUTSIDE = COMPLETE_NO_EXPERIENCE.model_copy(update={"city_zone": "Salamanca", "service_zone": OUTSIDE_ZONE})


@pytest.mark.parametrize("stage", list(Stage))
def test_a_place_outside_the_service_zones_disqualifies_at_any_stage(stage):
    assert decide(stage, Status.ACTIVE, Intent.NONE, OUTSIDE)[1] == Status.DISQUALIFIED


def test_an_unknown_zone_does_not_disqualify():
    # An empty field is not an outside zone.
    fields = ScreeningFields(full_name="Luis", driver_license=True)
    assert decide(Stage.DATA_COLLECTION, Status.ACTIVE, Intent.NONE, fields)[1] == Status.ACTIVE


def test_giving_a_place_in_a_service_zone_reopens_a_candidate_disqualified_by_zone():
    assert decide(Stage.CLOSING, Status.DISQUALIFIED, Intent.NONE, COMPLETE_NO_EXPERIENCE) == (
        Stage.CLOSING,
        Status.ACTIVE,
    )


def test_a_candidate_disqualified_by_zone_stays_closed_while_the_place_is_still_outside():
    assert decide(Stage.CLOSING, Status.DISQUALIFIED, Intent.NONE, OUTSIDE) == (Stage.CLOSING, Status.DISQUALIFIED)


def test_a_candidate_with_no_licence_and_an_outside_zone_needs_both_corrected():
    only_zone_fixed = NO_LICENCE  # licence still "no", zone now inside
    only_licence_fixed = OUTSIDE  # licence "yes", zone still outside
    assert decide(Stage.CLOSING, Status.DISQUALIFIED, Intent.NONE, only_zone_fixed)[1] == Status.DISQUALIFIED
    assert decide(Stage.CLOSING, Status.DISQUALIFIED, Intent.NONE, only_licence_fixed)[1] == Status.DISQUALIFIED
