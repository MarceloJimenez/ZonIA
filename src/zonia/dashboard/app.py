"""The dashboard's web app: the candidate list, the candidate page, and saving the recruiter's outcome and note."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from zonia import settings
from zonia.config import SERVICE_ZONES
from zonia.dashboard.filters import Filters, to_call
from zonia.dashboard.rows import OUTCOME_LABELS, field_rows, list_row, status_label, when
from zonia.domain.models import OUTSIDE_ZONE, RecruiterOutcome, Stage, Status
from zonia.pages import add_static_and_templates
from zonia.storage import Storage
from zonia.texts.labels import AVAILABILITY, SCHEDULE
from zonia.texts.summary import render_summary

NOTE_MAX = 2000  # characters; a note is a few lines, not a document


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
    templates = add_static_and_templates(app)

    def open_storage() -> Storage:
        # One connection per request: a SQLite connection must stay in the thread that opened it.
        return Storage(db_path, clock=clock)

    @app.get("/", response_class=HTMLResponse)
    def candidate_list(
        request: Request,
        status: str | None = None,
        country: str | None = None,
        zone: str | None = None,
        availability: str | None = None,
        schedule: str | None = None,
        q: str | None = None,
        view: str | None = None,
    ):
        """view "all" lists every conversation. Without it, the page lists the candidates to call."""
        view = _choice("view", view, {"all"}) or "to_call"
        status = _choice("status", status, {s.value for s in Status})
        filters = Filters(
            status=None if status is None else Status(status),
            country=_choice("country", country, SERVICE_ZONES),
            zone=_choice("zone", zone, {OUTSIDE_ZONE, *(z for zones in SERVICE_ZONES.values() for z in zones)}),
            availability=_choice("availability", availability, AVAILABILITY["en"]),
            schedule=_choice("schedule", schedule, SCHEDULE["en"]),
            search=(q or "").strip() or None,
        )
        with open_storage() as storage:
            every = storage.conversations()
        if view == "to_call":
            pool = [c for c in every if to_call(c)]
            shown = sorted((c for c in pool if filters.matches(c)), key=lambda c: c.updated_at)  # longest wait first
        else:
            pool = every
            shown = [c for c in every if filters.matches(c)]
            shown.sort(key=lambda c: c.status != Status.QUALIFIED)  # qualified first; sort is stable, so newest next
        options = {
            "status": [(s.value, status_label(s)) for s in Status],
            "country": [(country, country) for country in SERVICE_ZONES],
            "zone": SERVICE_ZONES,  # grouped by country in the template
            "availability": list(AVAILABILITY["en"].items()),
            "schedule": list(SCHEDULE["en"].items()),
        }
        return templates.TemplateResponse(
            request,
            "list.html",
            {
                "rows": [list_row(c, clock()) for c in shown],
                "total": len(pool),
                "view": view,
                "filters": filters,
                "options": options,
                "outside_zone": OUTSIDE_ZONE,
            },
        )

    @app.get("/conversations/{conversation_id}", response_class=HTMLResponse)
    def candidate_detail(request: Request, conversation_id: int):
        with open_storage() as storage:
            try:
                c = storage.conversation(conversation_id)
                messages = storage.messages(conversation_id)
                updates = storage.recruiter_updates(conversation_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="No conversation with this id")
        return templates.TemplateResponse(
            request,
            "detail.html",
            {
                "row": list_row(c, clock()),
                "fields": field_rows(c.fields),
                # The summary is shown once the candidate reaches closing.
                "summary": render_summary(c.fields, country=c.country) if c.stage == Stage.CLOSING else None,
                "messages": messages,
                "outcomes": list(OUTCOME_LABELS.items()),
                "updates": [
                    (when(moment), None if outcome is None else OUTCOME_LABELS[outcome], note)
                    for moment, outcome, note in updates
                ],
                "note_max": NOTE_MAX,
            },
        )

    @app.post("/conversations/{conversation_id}/updates")
    def add_update(
        conversation_id: int,
        outcome: RecruiterOutcome | None = Form(None),
        note: str = Form("", max_length=NOTE_MAX),
    ):
        """Save the recruiter's outcome, note, or both, then show the candidate page again."""
        note = note.strip() or None
        if outcome is None and note is None:
            raise HTTPException(status_code=422, detail="Choose an outcome or write a note")
        with open_storage() as storage:
            try:
                storage.add_recruiter_update(conversation_id, outcome, note)
            except KeyError:
                raise HTTPException(status_code=404, detail="No conversation with this id")
        # 303: the browser loads the page with GET, so a reload does not send the form again.
        return RedirectResponse(f"/conversations/{conversation_id}", status_code=303)

    return app


def main() -> None:
    import uvicorn

    settings.load()
    uvicorn.run(create_app(settings.db_path()), host="127.0.0.1", port=8000)
