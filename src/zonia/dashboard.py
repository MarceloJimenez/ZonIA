"""Recruiter dashboard: a list of conversations and one page per conversation.

Read-only. It reads the same SQLite file as Sonia (ZONIA_DB, or zonia.db).
`zonia-dashboard` starts it on http://127.0.0.1:8000.
"""

import os
from datetime import datetime
from pathlib import Path

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


def field_rows(fields: ScreeningFields) -> list[tuple[str, str]]:
    """(label, value) for each screening field. An empty field shows EMPTY."""

    def show(value, render=str) -> str:
        return EMPTY if value is None else render(value)

    licence = show(fields.driver_license, lambda v: "Yes" if v else "No")
    if fields.driver_license and fields.license_type:
        licence += f" ({fields.license_type})"
    experience = show(fields.experience_years, lambda y: f"{y:g} {'year' if y == 1 else 'years'}")
    return [
        ("Full name", show(fields.full_name)),
        ("Driver's licence", licence),
        ("City or zone", zone(fields)),
        ("Availability", show(fields.availability, lambda v: ", ".join(AVAILABILITY_EN[a] for a in v))),
        ("Schedule", show(fields.schedule, lambda v: ", ".join(SCHEDULE_EN[s] for s in v))),
        ("Experience", experience),
        ("Platform", show(fields.experience_platform)),
        ("Start date", show(fields.start_date, lambda d: d.strftime("%d %b %Y"))),
    ]


def list_row(c: ConversationRow) -> dict:
    return {
        "id": c.id,
        "name": c.fields.full_name or f"Conversation {c.id}",
        "country": c.country,
        "status": c.status.value.capitalize(),
        "qualified": c.status == Status.QUALIFIED,
        "stage": STAGE_LABELS[c.stage],
        "zone": zone(c.fields),
        "started": when(c.created_at),
        "last": when(c.updated_at),
        "case_code": c.case_code,
    }


def create_app(db_path: str | Path) -> FastAPI:
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
        filters = [("All", None), *((s.value.capitalize(), s) for s in Status)]
        return templates.TemplateResponse(
            request,
            "list.html",
            {"rows": [list_row(c) for c in shown], "total": len(every), "filters": filters, "status": status},
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
                "row": list_row(c),
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
