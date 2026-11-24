"""Recruiter dashboard: a list of conversations and one page per conversation.

Read-only. It reads the same SQLite file as Sonia (ZONIA_DB, or zonia.db).
`zonia-dashboard` starts it on http://127.0.0.1:8000.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dotenv import load_dotenv

from zonia.config import SERVICE_ZONES
from zonia.flow import render_summary
from zonia.models import OUTSIDE_ZONE, ScreeningFields, Stage, Status
from zonia.storage import ConversationRow, Storage

HERE = Path(__file__).parent

STAGE_LABELS = {Stage.INTRODUCTION: "Introduction", Stage.DATA_COLLECTION: "Data collection", Stage.CLOSING: "Closing"}

AVAILABILITY_EN = {"full-time": "Full-time", "part-time": "Part-time", "weekends": "Weekends"}
SCHEDULE_EN = {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "flexible": "Flexible"}

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
    return EMPTY if fields.availability is None else ", ".join(AVAILABILITY_EN[a] for a in fields.availability)


def schedule(fields: ScreeningFields) -> str:
    return EMPTY if fields.schedule is None else ", ".join(SCHEDULE_EN[s] for s in fields.schedule)


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
        "country": c.country,
        "status": status_label(c.status),
        "qualified": c.status == Status.QUALIFIED,
        "technical_error": c.status == Status.TECHNICAL_ERROR,  # the recruiter contacts the candidate again
        "stage": STAGE_LABELS[c.stage],
        "zone": zone(c.fields),
        "started": when(c.created_at),
        "last": when(c.updated_at),
        "case_code": c.case_code,
        "phone": c.phone,
        "service_zone": service_zone(c.fields),
        "availability": availability(c.fields),
        "schedule": schedule(c.fields),
        "experience": experience(c.fields),
        "start_date": start_date(c.fields),
        "waiting": waiting(c.updated_at, now),
    }


@dataclass
class Filters:
    """The list filters, as the URL gives them. None means "all"."""

    status: Status | None = None
    country: str | None = None
    zone: str | None = None  # a service zone, or OUTSIDE_ZONE
    availability: str | None = None
    schedule: str | None = None
    search: str | None = None  # part of the name, the phone or the case code

    @property
    def chosen(self) -> int:
        """How many of the five lists have a value. The search is not counted: it is always in sight."""
        return sum(v is not None for v in (self.status, self.country, self.zone, self.availability, self.schedule))

    def matches(self, c: ConversationRow) -> bool:
        f = c.fields
        return (
            (self.status is None or c.status == self.status)
            and (self.country is None or c.country == self.country)
            and (self.zone is None or f.service_zone == self.zone)
            and (self.availability is None or self.availability in (f.availability or []))
            and (self.schedule is None or self.schedule in (f.schedule or []))
            and (self.search is None or self._found(c))
        )

    def _found(self, c: ConversationRow) -> bool:
        needle = self.search.casefold()
        digits = "".join(ch for ch in needle if ch.isdigit())
        return (
            needle in (c.fields.full_name or "").casefold()
            or needle in c.case_code.casefold()
            or (len(digits) >= 3 and digits in (c.phone or ""))
        )


def _choice(name: str, value: str | None, allowed) -> str | None:
    """An empty value means "all". A value outside the allowed ones is an error (422)."""
    if not value:
        return None
    if value not in allowed:
        raise HTTPException(status_code=422, detail=f"Unknown {name}: {value}")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(db_path: str | Path, clock: Callable[[], datetime] = _utc_now) -> FastAPI:
    """clock gives the current time, for the Waiting column; tests pass a fake one."""
    app = FastAPI(title="ZonIA recruiter dashboard")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    def open_storage() -> Storage:
        # One connection per request: a SQLite connection must stay in the thread that opened it.
        return Storage(db_path)

    @app.get("/", response_class=HTMLResponse)
    def candidate_list(
        request: Request,
        status: str | None = None,
        country: str | None = None,
        zone: str | None = None,
        availability: str | None = None,
        schedule: str | None = None,
        q: str | None = None,
    ):
        status = _choice("status", status, {s.value for s in Status})
        filters = Filters(
            status=None if status is None else Status(status),
            country=_choice("country", country, SERVICE_ZONES),
            zone=_choice("zone", zone, {OUTSIDE_ZONE, *(z for zones in SERVICE_ZONES.values() for z in zones)}),
            availability=_choice("availability", availability, AVAILABILITY_EN),
            schedule=_choice("schedule", schedule, SCHEDULE_EN),
            search=(q or "").strip() or None,
        )
        storage = open_storage()
        try:
            every = storage.conversations()
        finally:
            storage.close()
        shown = [c for c in every if filters.matches(c)]
        shown.sort(key=lambda c: c.status != Status.QUALIFIED)  # qualified first; sort is stable, so newest next
        options = {
            "status": [(s.value, status_label(s)) for s in Status],
            "country": [(country, country) for country in SERVICE_ZONES],
            "zone": SERVICE_ZONES,  # grouped by country in the template
            "availability": list(AVAILABILITY_EN.items()),
            "schedule": list(SCHEDULE_EN.items()),
        }
        return templates.TemplateResponse(
            request,
            "list.html",
            {
                "rows": [list_row(c, clock()) for c in shown],
                "total": len(every),
                "filters": filters,
                "options": options,
                "outside_zone": OUTSIDE_ZONE,
            },
        )

    @app.get("/conversations/{conversation_id}", response_class=HTMLResponse)
    def candidate_detail(request: Request, conversation_id: int):
        storage = open_storage()
        try:
            c = storage.conversation(conversation_id)
            messages = storage.messages(conversation_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="No conversation with this id")
        finally:
            storage.close()
        return templates.TemplateResponse(
            request,
            "detail.html",
            {
                "row": list_row(c, clock()),
                "fields": field_rows(c.fields),
                # The summary is shown once the candidate reaches closing.
                "summary": render_summary(c.fields, country=c.country) if c.stage == Stage.CLOSING else None,
                "messages": messages,
            },
        )

    return app


def main() -> None:
    import uvicorn

    load_dotenv(".env")
    uvicorn.run(create_app(os.environ.get("ZONIA_DB", "zonia.db")), host="127.0.0.1", port=8000)
