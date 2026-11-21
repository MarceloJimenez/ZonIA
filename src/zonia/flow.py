"""Stages and statuses. Plain code, no LLM."""

from zonia.models import Intent, ScreeningFields, Stage, Status

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


def decide(stage: Stage, status: Status, intent: Intent, fields: ScreeningFields) -> tuple[Stage, Status]:
    """Return the new stage and status after one candidate message."""
    if status == Status.PAUSED:
        status = Status.ACTIVE
    if fields.driver_license is False:
        return stage, Status.DISQUALIFIED
    if intent == Intent.NOT_INTERESTED:
        return stage, Status.WITHDRAWN
    if intent == Intent.NOT_NOW:
        return stage, Status.PAUSED
    if stage == Stage.INTRODUCTION and fields.full_name:
        stage = Stage.DATA_COLLECTION
    if stage == Stage.DATA_COLLECTION and not open_fields(fields):
        return Stage.CLOSING, status
    if stage == Stage.CLOSING and intent == Intent.CONFIRMS_SUMMARY:
        return stage, Status.QUALIFIED
    return stage, status
