"""Recruiter dashboard: a list of conversations and one page per conversation.

Read-only. It reads the same SQLite file as Sonia (ZONIA_DB, or zonia.db).
`zonia-dashboard` starts it on http://127.0.0.1:8000.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dotenv import load_dotenv

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
    def candidate_list(request: Request, status: Status | None = None):
        storage = open_storage()
        try:
            every = storage.conversations()
        finally:
            storage.close()
        shown = [c for c in every if status is None or c.status == status]
        shown.sort(key=lambda c: c.status != Status.QUALIFIED)  # qualified first; sort is stable, so newest next
        filters = [("All", None), *((status_label(s), s) for s in Status)]
        return templates.TemplateResponse(
            request,
            "list.html",
            {"rows": [list_row(c, clock()) for c in shown], "total": len(every), "filters": filters, "status": status},
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
