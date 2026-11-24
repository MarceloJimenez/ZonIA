"""How the dashboard shows each field and each row, with the English labels."""

from datetime import datetime, timedelta

from zonia.domain.models import OUTSIDE_ZONE, RecruiterOutcome, ScreeningFields, Stage, Status
from zonia.storage import ConversationRow
from zonia.texts.labels import AVAILABILITY, SCHEDULE

STAGE_LABELS = {Stage.INTRODUCTION: "Introduction", Stage.DATA_COLLECTION: "Data collection", Stage.CLOSING: "Closing"}

OUTCOME_LABELS = {
    RecruiterOutcome.CALLED: "Called",
    RecruiterOutcome.NO_ANSWER: "No answer",
    RecruiterOutcome.INTERVIEW: "Interview",
    RecruiterOutcome.HIRED: "Hired",
    RecruiterOutcome.REJECTED: "Rejected",
}

# Tag colours: ok is green, info blue, warn amber, muted grey, alert red. A status or outcome not listed is neutral.
STATUS_TONE = {
    Status.QUALIFIED: "ok",
    Status.ACTIVE: "info",
    Status.PAUSED: "info",
    Status.DISQUALIFIED: "muted",
    Status.WITHDRAWN: "muted",
    Status.INCOMPLETE: "muted",
    Status.TECHNICAL_ERROR: "alert",
}
OUTCOME_TONE = {
    RecruiterOutcome.INTERVIEW: "info",
    RecruiterOutcome.HIRED: "ok",
    RecruiterOutcome.REJECTED: "muted",
    RecruiterOutcome.NO_ANSWER: "warn",
}

LATE = timedelta(hours=24)  # from this wait on, the Waiting column turns amber

EMPTY = "—"


def when(moment: datetime) -> str:
    """A saved time as the dashboard shows it, for example "22 Nov · 09:14 UTC"."""
    return moment.strftime("%d %b · %H:%M UTC")


def zone(fields: ScreeningFields) -> str:
    """The candidate's words, and the service zone they are in."""
    if fields.city_zone is None:
        return EMPTY
    if fields.service_zone == OUTSIDE_ZONE:
        return f"{fields.city_zone} (outside the service zones)"
    return f"{fields.city_zone} (zone: {fields.service_zone})"


def availability(fields: ScreeningFields) -> str:
    return EMPTY if fields.availability is None else ", ".join(AVAILABILITY["en"][a] for a in fields.availability)


def schedule(fields: ScreeningFields) -> str:
    return EMPTY if fields.schedule is None else ", ".join(SCHEDULE["en"][s] for s in fields.schedule)


def experience(fields: ScreeningFields) -> str:
    """Years and platform, for example "2 years, Glovo"."""
    years = fields.experience_years
    if years is None:
        return EMPTY
    text = f"{years:g} {'year' if years == 1 else 'years'}"
    if years and fields.experience_platform:
        text += f", {fields.experience_platform}"
    return text


def start_date(fields: ScreeningFields) -> str:
    return EMPTY if fields.start_date is None else fields.start_date.strftime("%d %b %Y")


def service_zone(fields: ScreeningFields) -> str:
    """The service zone alone, for the list column. The candidate's own words are on the detail page."""
    if fields.service_zone is None:
        return EMPTY
    return "Outside zones" if fields.service_zone == OUTSIDE_ZONE else fields.service_zone


def waiting(since: datetime, now: datetime) -> str:
    """Time since the last activity, rounded down: "12 min", "3 h", "2 d"."""
    gap = max(now - since, timedelta(0))
    if gap < timedelta(hours=1):
        return f"{gap // timedelta(minutes=1)} min"
    if gap < timedelta(days=1):
        return f"{gap // timedelta(hours=1)} h"
    return f"{gap.days} d"


def initials(name: str | None) -> str:
    """The first letters of the first two words of the name, for example "AL" for "Ana López". "?" without a name."""
    words = (name or "").split()
    return "".join(w[0] for w in words[:2]).upper() or "?"


def field_rows(fields: ScreeningFields) -> list[tuple[str, str]]:
    """(label, value) for each screening field. An empty field shows EMPTY."""
    licence = EMPTY if fields.driver_license is None else ("Yes" if fields.driver_license else "No")
    if fields.driver_license and fields.license_type:
        licence += f" ({fields.license_type})"
    years = fields.experience_years
    return [
        ("Full name", fields.full_name or EMPTY),
        ("Driver's licence", licence),
        ("City or zone", zone(fields)),
        ("Availability", availability(fields)),
        ("Schedule", schedule(fields)),
        ("Experience", EMPTY if years is None else f"{years:g} {'year' if years == 1 else 'years'}"),
        ("Platform", fields.experience_platform or EMPTY),
        ("Start date", start_date(fields)),
    ]


def status_label(status: Status) -> str:
    """"technical_error" -> "Technical error"."""
    return status.value.replace("_", " ").capitalize()


def list_row(c: ConversationRow, now: datetime) -> dict:
    return {
        "id": c.id,
        "name": c.fields.full_name or f"Conversation {c.id}",
        "initials": initials(c.fields.full_name),
        "country": c.country,
        "status": status_label(c.status),
        "status_tone": STATUS_TONE.get(c.status),
        "stage": STAGE_LABELS[c.stage],
        "zone": zone(c.fields),
        "started": when(c.created_at),
        "last": when(c.updated_at),
        "case_code": c.case_code,
        "phone": c.phone,
        "outcome": None if c.outcome is None else OUTCOME_LABELS[c.outcome],
        "outcome_tone": OUTCOME_TONE.get(c.outcome),
        "service_zone": service_zone(c.fields),
        "availability": availability(c.fields),
        "schedule": schedule(c.fields),
        "experience": experience(c.fields),
        "start_date": start_date(c.fields),
        "waiting": waiting(c.updated_at, now),
        "late": now - c.updated_at >= LATE,
    }
