"""Recruiter dashboard: the pages show what the database holds."""

import pytest
from fastapi.testclient import TestClient

from test_turn import COMPLETE
from zonia.dashboard import create_app
from zonia.models import ScreeningFields, Stage, Status
from zonia.storage import Storage
from zonia.turn import Conversation, TurnResult


def turn(message: str, reply: str) -> TurnResult:
    return TurnResult(
        message=message, reply=reply, intent="none", stage=Stage.DATA_COLLECTION,
        status=Status.ACTIVE, llm_calls=1, reply_source="call_1",
    )


@pytest.fixture
def db(tmp_path):
    """Three conversations: active (oldest), qualified, disqualified (newest)."""
    path = tmp_path / "zonia.db"
    storage = Storage(path)
    active = Conversation(fields=ScreeningFields(full_name="Luis Pérez"), stage=Stage.DATA_COLLECTION)
    storage.create(active)
    qualified_id = storage.create(Conversation(fields=COMPLETE, stage=Stage.CLOSING, status=Status.QUALIFIED))
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


def test_an_unknown_id_gives_404(client):
    assert client.get("/conversations/999").status_code == 404
