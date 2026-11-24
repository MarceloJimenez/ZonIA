"""Recruiter dashboard: the pages show what the database holds."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from test_turn import COMPLETE
from zonia.dashboard import create_app, experience, field_rows, service_zone, waiting
from zonia.models import ScreeningFields, Stage, Status
from zonia.storage import Storage
from zonia.turn import Conversation, TurnResult


def turn(message: str, reply: str) -> TurnResult:
    return TurnResult(
        message=message, reply=reply, intent="none", stage=Stage.DATA_COLLECTION,
        status=Status.ACTIVE, language="es", llm_calls=1, reply_source="call_1",
    )


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
    storage.save_turn(qualified_id, qualified, turn("Soy Ana López", "¿Tienes carnet?"))
    storage.save_turn(qualified_id, qualified, turn("Sí, <b>tengo</b>", "Perfecto."))
    storage.close()
    return path


@pytest.fixture
def client(db):
    return TestClient(create_app(db))


def names_in_order(html: str, names: list[str]) -> list[str]:
    return sorted(names, key=html.index)


def test_the_list_shows_every_conversation_qualified_first_then_newest(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "3 of 3 conversations" in response.text
    assert names_in_order(response.text, ["Luis Pérez", "Ana López", "Marta Gil"]) == [
        "Ana López", "Marta Gil", "Luis Pérez",
    ]


def test_the_status_filter_shows_only_that_status(client):
    response = client.get("/?status=disqualified")
    assert "1 of 3 conversations" in response.text
    assert "Marta Gil" in response.text
    assert "Ana López" not in response.text


def test_an_unknown_status_is_rejected(client):
    assert client.get("/?status=hired").status_code == 422


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
    html = client.get("/").text
    assert '<a href="tel:+34600111222">+34600111222</a>' in html


def test_the_detail_has_a_call_button_only_when_there_is_a_phone(client):
    assert 'href="tel:+34600111222">Call +34600111222</a>' in client.get("/conversations/2").text
    assert "tel:" not in client.get("/conversations/1").text


def test_the_list_shows_the_columns_the_recruiter_decides_with(client):
    html = client.get("/").text
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
    assert '<td class="soft nowrap">5 h</td>' in client.get("/").text


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
    response = client.get("/?status=technical_error")
    assert "Rosa Díaz" in response.text
    assert "zn-tag--alert" in response.text
    assert "Technical error" in response.text
