"""Recruiter dashboard: the pages show what the database holds."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from test_turn import COMPLETE
from zonia.dashboard.app import create_app
from zonia.dashboard.rows import experience, field_rows, initials, service_zone, waiting
from zonia.domain.models import RecruiterOutcome, ScreeningFields, Stage, Status
from zonia.storage import Storage
from zonia.domain.conversation import Conversation


@pytest.fixture
def db(tmp_path):
    """Three conversations: active (oldest), qualified, disqualified (newest)."""
    path = tmp_path / "zonia.db"
    storage = Storage(path)
    active = Conversation(fields=ScreeningFields(full_name="Luis Pérez"), stage=Stage.DATA_COLLECTION)
    storage.create(active)
    qualified_id = storage.create(
        Conversation(fields=COMPLETE, stage=Stage.CLOSING, status=Status.QUALIFIED), phone="+34600111222"
    )
    storage.create(Conversation(
        fields=ScreeningFields(full_name="Marta Gil", driver_license=False), status=Status.DISQUALIFIED, country="MX",
        case_code="K7PX-3QMD",
    ))
    qualified = storage.load(qualified_id)
    storage.save_turn(qualified_id, qualified, "Soy Ana López", "¿Tienes carnet?")
    storage.save_turn(qualified_id, qualified, "Sí, <b>tengo</b>", "Perfecto.")
    storage.close()
    return path


@pytest.fixture
def client(db):
    return TestClient(create_app(db))


def names_in_order(html: str, names: list[str]) -> list[str]:
    return sorted(names, key=html.index)


def test_the_list_shows_every_conversation_qualified_first_then_newest(client):
    response = client.get("/?view=all")
    assert response.status_code == 200
    assert "3 of 3 conversations" in response.text
    assert names_in_order(response.text, ["Luis Pérez", "Ana López", "Marta Gil"]) == [
        "Ana López", "Marta Gil", "Luis Pérez",
    ]


def test_the_status_filter_shows_only_that_status(client):
    response = client.get("/?view=all&status=disqualified")
    assert "1 of 3 conversations" in response.text
    assert "Marta Gil" in response.text
    assert "Ana López" not in response.text


@pytest.mark.parametrize(
    ("query", "shown"),
    [
        ("country=MX", ["Marta Gil"]),
        ("zone=Comunidad+de+Madrid", ["Ana López"]),
        ("availability=full-time", ["Ana López"]),
        ("schedule=morning", ["Ana López"]),
        ("schedule=evening", []),
        ("q=luis", ["Luis Pérez"]),  # part of the name, any case
        ("q=600+111", ["Ana López"]),  # part of the phone, with a space
        ("q=k7px", ["Marta Gil"]),  # part of the case code
        ("country=ES&status=active", ["Luis Pérez"]),  # filters add up
        ("status=&country=&zone=&availability=&schedule=&q=", ["Ana López", "Marta Gil", "Luis Pérez"]),  # "All"
    ],
)
def test_the_filters_show_only_the_matching_candidates(client, query, shown):
    html = client.get(f"/?view=all&{query}").text
    assert f"{len(shown)} of 3 conversations" in html
    for name in ["Luis Pérez", "Ana López", "Marta Gil"]:
        assert (f">{name}</a>" in html) == (name in shown)


def test_the_form_keeps_the_chosen_filters(client):
    html = client.get("/?view=all&country=ES&zone=Comunidad+de+Madrid&q=ana").text
    assert '<option value="ES" selected>' in html
    assert '<option value="Comunidad de Madrid" selected>' in html
    assert 'value="ana"' in html


def test_the_filter_icon_shows_how_many_lists_are_chosen(client):
    assert '<span class="filter-count">2</span>' in client.get("/?view=all&country=ES&schedule=morning&q=ana").text
    html = client.get("/?view=all&q=ana").text
    assert "filter-count" not in html
    assert ">Clear</a>" in html
    assert ">Clear</a>" not in client.get("/?view=all").text


@pytest.mark.parametrize("query", ["country=FR", "zone=Lima", "availability=nights", "schedule=night"])
def test_an_unknown_filter_value_is_rejected(client, query):
    assert client.get(f"/?view=all&{query}").status_code == 422


def test_an_unknown_status_is_rejected(client):
    assert client.get("/?view=all&status=hired").status_code == 422


def test_the_detail_shows_the_fields_the_summary_and_the_messages_in_order(client):
    response = client.get("/conversations/2")
    assert response.status_code == 200
    html = response.text
    assert "Chamberí (zone: Comunidad de Madrid)" in html
    assert "Full-time" in html
    assert "Summary shown to the candidate" in html
    assert html.index("Soy Ana López") < html.index("¿Tienes carnet?") < html.index("Perfecto.")


def test_candidate_text_is_escaped(client):
    html = client.get("/conversations/2").text
    assert "&lt;b&gt;tengo&lt;/b&gt;" in html
    assert "<b>tengo</b>" not in html


def test_no_summary_before_closing(client):
    html = client.get("/conversations/1").text
    assert "Luis Pérez" in html
    assert "Summary shown to the candidate" not in html
    assert "No messages yet." in html


def test_the_detail_shows_the_case_code(client):
    assert "Case K7PX-3QMD" in client.get("/conversations/3").text


def test_the_list_shows_the_phone_as_a_call_link(client):
    html = client.get("/?view=all").text
    assert '<a href="tel:+34600111222">+34600111222</a>' in html


def test_the_detail_has_a_call_button_only_when_there_is_a_phone(client):
    assert 'href="tel:+34600111222">Call +34600111222</a>' in client.get("/conversations/2").text
    assert "tel:" not in client.get("/conversations/1").text


def test_the_list_shows_the_columns_the_recruiter_decides_with(client):
    html = client.get("/?view=all").text
    for header in ["Zone", "Availability", "Schedule", "Experience", "Start date", "Waiting"]:
        assert f"<th>{header}</th>" in html
    for gone in ["Country", "Stage", "Started", "Last message"]:
        assert f"<th>{gone}</th>" not in html
    assert "<td>Comunidad de Madrid</td>" in html  # Ana López's service zone, without "Chamberí"


def test_the_zone_column_shows_the_service_zone_only():
    assert service_zone(ScreeningFields(city_zone="Chamberí", service_zone="Comunidad de Madrid")) == "Comunidad de Madrid"
    assert service_zone(ScreeningFields(city_zone="Lima", service_zone="outside")) == "Outside zones"
    assert service_zone(ScreeningFields()) == "—"


def test_experience_shows_the_platform_only_with_years():
    assert experience(ScreeningFields(experience_years=2, experience_platform="Glovo")) == "2 years, Glovo"
    assert experience(ScreeningFields(experience_years=0)) == "0 years"
    assert experience(ScreeningFields()) == "—"


@pytest.mark.parametrize(
    ("gap", "shown"),
    [(timedelta(seconds=30), "0 min"), (timedelta(minutes=59), "59 min"), (timedelta(hours=3, minutes=50), "3 h"),
     (timedelta(days=2, hours=23), "2 d")],
)
def test_waiting_is_rounded_down(gap, shown):
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    assert waiting(now - gap, now) == shown


def test_the_waiting_column_counts_from_the_last_turn(tmp_path):
    saved = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
    path = tmp_path / "zonia.db"
    storage = Storage(path, clock=lambda: saved)
    storage.create(Conversation(fields=ScreeningFields(full_name="Rosa Díaz")))
    storage.close()
    client = TestClient(create_app(path, clock=lambda: saved + timedelta(hours=5)))
    assert '<td class="soft nowrap">5 h</td>' in client.get("/?view=all").text


def test_the_recruiter_sets_an_outcome_with_a_note(client):
    response = client.post("/conversations/2/updates", data={"outcome": "interview", "note": "  Tuesday 10:00  "})
    assert response.status_code == 200  # the client follows the 303 to the candidate page
    assert response.url.path == "/conversations/2"
    assert '<span class="zn-tag outcome zn-tag--info">Interview</span>' in response.text
    assert "<strong>Interview</strong> · Tuesday 10:00</span>" in response.text


def test_a_note_alone_keeps_the_outcome_and_the_newest_update_is_first(client):
    client.post("/conversations/2/updates", data={"outcome": "no_answer"})
    html = client.post("/conversations/2/updates", data={"note": "Call again after 18:00"}).text
    assert '<span class="zn-tag outcome zn-tag--warn">No answer</span>' in html
    assert html.index("Call again after 18:00") < html.index("<strong>No answer</strong>")


def test_an_update_without_outcome_or_note_is_rejected(client):
    assert client.post("/conversations/2/updates", data={"note": "   "}).status_code == 422


def test_an_unknown_outcome_is_rejected(client):
    assert client.post("/conversations/2/updates", data={"outcome": "maybe"}).status_code == 422


def test_an_update_for_an_unknown_conversation_gives_404(client):
    assert client.post("/conversations/999/updates", data={"outcome": "called"}).status_code == 404


def test_the_storage_keeps_every_recruiter_update_and_gives_the_newest_outcome(tmp_path):
    times = iter(datetime(2026, 11, 24, h, 0, tzinfo=UTC) for h in range(9, 20))
    storage = Storage(tmp_path / "zonia.db", clock=lambda: next(times))
    conversation_id = storage.create(Conversation())
    storage.add_recruiter_update(conversation_id, RecruiterOutcome.CALLED, None)
    storage.add_recruiter_update(conversation_id, None, "Wants weekends only")
    assert storage.conversation(conversation_id).outcome == RecruiterOutcome.CALLED
    assert storage.conversations()[0].outcome == RecruiterOutcome.CALLED
    assert [(t.hour, o, n) for t, o, n in storage.recruiter_updates(conversation_id)] == [
        (11, None, "Wants weekends only"),
        (10, RecruiterOutcome.CALLED, None),
    ]
    with pytest.raises(ValueError):
        storage.add_recruiter_update(conversation_id, None, None)
    with pytest.raises(KeyError):
        storage.add_recruiter_update(999, RecruiterOutcome.CALLED, None)


def test_the_home_page_lists_only_the_qualified_candidates_to_call(client):
    html = client.get("/").text
    assert "1 of 1 candidates to call" in html
    assert ">Ana López</a>" in html
    assert ">Luis Pérez</a>" not in html and ">Marta Gil</a>" not in html
    assert '<a href="/" aria-current="page">To call</a>' in html
    assert 'name="status"' not in html  # every row is qualified, so the status list and column are not shown
    assert "<th>Status</th>" not in html


@pytest.mark.parametrize(("outcome", "still_to_call"), [("no_answer", True), ("called", False), ("interview", False)])
def test_a_candidate_leaves_to_call_once_the_recruiter_reaches_them(client, outcome, still_to_call):
    client.post("/conversations/2/updates", data={"outcome": outcome})
    assert (">Ana López</a>" in client.get("/").text) == still_to_call


def test_nobody_to_call_says_so(client):
    client.post("/conversations/2/updates", data={"outcome": "hired"})
    assert "Nobody to call right now." in client.get("/").text


def test_to_call_shows_the_longest_wait_first_and_keeps_the_view_when_filtering(tmp_path):
    times = iter(datetime(2026, 11, 24, h, 0, tzinfo=UTC) for h in range(8, 20))
    path = tmp_path / "zonia.db"
    storage = Storage(path, clock=lambda: next(times))
    for name, zone in [("Rosa Díaz", "Andalucía"), ("Pablo Ruiz", "Cataluña")]:
        storage.create(Conversation(
            fields=ScreeningFields(full_name=name, city_zone="x", service_zone=zone), status=Status.QUALIFIED,
        ))
    storage.close()
    client = TestClient(create_app(path))
    html = client.get("/").text
    assert names_in_order(html, ["Pablo Ruiz", "Rosa Díaz"]) == ["Rosa Díaz", "Pablo Ruiz"]  # Rosa waits longer
    html = client.get("/?zone=Catalu%C3%B1a").text
    assert "1 of 2 candidates to call" in html
    assert 'name="view"' not in html  # the form stays on To call


def test_the_all_view_shows_the_recruiter_outcome(client):
    client.post("/conversations/2/updates", data={"outcome": "no_answer"})
    assert '<td class="nowrap"><span class="zn-tag zn-tag--warn">No answer</span></td>' in client.get("/?view=all").text


def test_an_unknown_view_is_rejected(client):
    assert client.get("/?view=mine").status_code == 422


def test_an_unknown_id_gives_404(client):
    assert client.get("/conversations/999").status_code == 404


def test_the_licence_row_shows_the_type_when_the_candidate_gave_it():
    rows = dict(field_rows(ScreeningFields(driver_license=True, license_type="profesional")))
    assert rows["Driver's licence"] == "Yes (profesional)"


def test_a_technical_error_is_labelled_and_highlighted(tmp_path):
    path = tmp_path / "zonia.db"
    storage = Storage(path)
    storage.create(Conversation(fields=ScreeningFields(full_name="Rosa Díaz"), status=Status.TECHNICAL_ERROR))
    storage.close()
    client = TestClient(create_app(path))
    response = client.get("/?view=all&status=technical_error")
    assert "Rosa Díaz" in response.text
    assert "zn-tag--alert" in response.text
    assert "Technical error" in response.text


@pytest.mark.parametrize(("name", "shown"), [("Ana López", "AL"), ("rosa", "R"), ("Ana María López Gil", "AM"), (None, "?")])
def test_initials(name, shown):
    assert initials(name) == shown


def test_the_list_colours_each_status(client):
    html = client.get("/?view=all").text
    assert '<span class="zn-tag zn-tag--ok">Qualified</span>' in html
    assert '<span class="zn-tag zn-tag--info">Active</span>' in html
    assert '<span class="zn-tag zn-tag--muted">Disqualified</span>' in html
    assert '<span class="avatar" aria-hidden="true">AL</span>' in html


def test_a_wait_of_a_day_or_more_is_marked_late(tmp_path):
    saved = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
    path = tmp_path / "zonia.db"
    storage = Storage(path, clock=lambda: saved)
    storage.create(Conversation(fields=ScreeningFields(full_name="Rosa Díaz")))
    storage.close()
    late = TestClient(create_app(path, clock=lambda: saved + timedelta(hours=24))).get("/?view=all").text
    assert '<td class="soft nowrap late">1 d</td>' in late
    on_time = TestClient(create_app(path, clock=lambda: saved + timedelta(hours=23))).get("/?view=all").text
    assert '<td class="soft nowrap">23 h</td>' in on_time
