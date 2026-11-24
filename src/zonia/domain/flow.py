"""Stages and statuses. Plain code, no LLM."""

from zonia.domain.models import OUTSIDE_ZONE, Intent, ScreeningFields, Stage, Status

FIELD_ORDER = [
    "full_name",
    "driver_license",
    "city_zone",
    "availability",
    "schedule",
    "experience_years",
    "experience_platform",
    "start_date",
]

FINAL_STATUSES = {Status.QUALIFIED, Status.DISQUALIFIED, Status.WITHDRAWN, Status.INCOMPLETE}


def open_fields(fields: ScreeningFields) -> list[str]:
    """Fields still empty, in FIELD_ORDER.

    experience_platform is open only if experience_years > 0.
    """
    result = []
    for name in FIELD_ORDER:
        if name == "experience_platform" and not (fields.experience_years or 0) > 0:
            continue
        if getattr(fields, name) is None:
            result.append(name)
    return result


def is_disqualified(fields: ScreeningFields) -> bool:
    """True when the candidate has no licence, or lives outside the service zones."""
    return fields.driver_license is False or fields.service_zone == OUTSIDE_ZONE


def reopens(status: Status, intent: Intent, fields: ScreeningFields) -> bool:
    """True when a message changes what closed the conversation. The candidate is always trusted.

    Disqualified: no reason to disqualify is left (licence is not "no", zone is a service zone). Withdrawn: the candidate wants to continue.
    Qualified: the candidate corrects the summary, or is no longer interested (then withdrawn).
    Incomplete: any message, because the candidate came back (design 4.1). The conversation continues
    from the first empty field. A conversation closed by the turn limit never gets here:
    run_turn_safely stops it before the LLM.
    """
    if status == Status.DISQUALIFIED:
        return not is_disqualified(fields)
    if status == Status.WITHDRAWN:
        return intent == Intent.CONTINUE
    if status == Status.QUALIFIED:
        return intent in {Intent.CORRECTS_SUMMARY, Intent.NOT_INTERESTED}
    return status == Status.INCOMPLETE


def decide(stage: Stage, status: Status, intent: Intent, fields: ScreeningFields) -> tuple[Stage, Status]:
    """Return the new stage and status after one candidate message."""
    reopened = status in FINAL_STATUSES and reopens(status, intent, fields)
    if status in FINAL_STATUSES and not reopened:
        return stage, status
    if status in {Status.PAUSED, Status.TECHNICAL_ERROR} or reopened:
        status = Status.ACTIVE
    if is_disqualified(fields):
        return stage, Status.DISQUALIFIED
    if intent == Intent.NOT_INTERESTED:
        return stage, Status.WITHDRAWN
    if intent == Intent.NOT_NOW:
        return stage, Status.PAUSED
    if stage == Stage.INTRODUCTION and fields.full_name:
        stage = Stage.DATA_COLLECTION
    if stage == Stage.DATA_COLLECTION and not open_fields(fields):
        return Stage.CLOSING, status
    # A reopened candidate must see the summary with the new data before confirming it.
    if stage == Stage.CLOSING and intent == Intent.CONFIRMS_SUMMARY and not reopened:
        return stage, Status.QUALIFIED
    return stage, status
