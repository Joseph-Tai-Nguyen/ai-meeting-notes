import pytest
from fastapi.testclient import TestClient

from conftest import bursts
from meeting_notes.audio.capture import ArraySource
from meeting_notes.calendar_ics import _events_basic
from meeting_notes.server.api import create_app

H = {"x-meeting-notes": "1"}


@pytest.fixture
def client(ctx):
    with TestClient(create_app(ctx, allowed_hosts={"testserver"})) as c:
        yield c


def test_status_and_settings(client):
    st = client.get("/api/status").json()
    assert any(e["name"] == "mock" and e["available"] for e in st["engines"])
    assert {p["name"] for p in st["ai_providers"]} == {"gemini_api", "gemini_cli", "claude_code"}
    s = client.put("/api/settings", json={"transcription": {"language": "vi"}}, headers=H).json()
    assert s["transcription"]["language"] == "vi" and s["transcription"]["engine"] == "vosk"


def test_write_requires_csrf_header(client):
    assert client.post("/api/meetings", json={}).status_code == 403
    assert client.post("/api/meetings", json={}, headers=H).status_code == 200


def test_foreign_host_rejected(ctx):
    with TestClient(create_app(ctx)) as c:  # default: localhost only
        assert c.get("/api/status").status_code == 403


def test_meeting_lifecycle(client, ctx):
    m = client.post("/api/meetings", json={"title": "Sync", "mode": "in_person"}, headers=H).json()
    mid = m["id"]
    session = ctx.start_session(mid, engine="mock", sources=[ArraySource(bursts(2), "Speaker")])
    assert session.wait(10)
    data = client.get(f"/api/meetings/{mid}").json()
    assert len(data["segments"]) == 2 and data["meeting"]["status"] == "done"

    assert client.put(f"/api/meetings/{mid}/notes", json={"text": "my notes"}, headers=H).status_code == 200
    seg = client.patch(f"/api/meetings/{mid}/segments/1", json={"text": "fixed"}, headers=H).json()
    assert seg["text"] == "fixed"
    assert client.post(f"/api/meetings/{mid}/speakers/rename", json={"old": "Speaker", "new": "Bob"}, headers=H).json()["renamed"] == 2
    assert client.patch(f"/api/meetings/{mid}", json={"title": "Renamed"}, headers=H).json()["title"] == "Renamed"

    r = client.get(f"/api/meetings/{mid}/export?format=md")
    assert r.status_code == 200 and "Bob" in r.text and "attachment" in r.headers["content-disposition"]
    assert client.get("/api/meetings?q=fixed").json()[0]["id"] == mid

    backup = client.get("/api/backup")
    assert backup.headers["content-type"] == "application/zip"
    assert client.post("/api/restore", content=backup.content, headers=H).json()["skipped"] == [mid]

    assert client.post(f"/api/meetings/{mid}/record/stop", headers=H).status_code == 409
    assert client.delete(f"/api/meetings/{mid}", headers=H).json()["trashed"]
    assert client.get(f"/api/meetings/{mid}").status_code == 404


def test_analyze_without_provider_gives_clear_error(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)
    mid = client.post("/api/meetings", json={"title": "x"}, headers=H).json()["id"]
    client.put(f"/api/meetings/{mid}/notes", json={"text": "notes"}, headers=H)
    r = client.post(f"/api/meetings/{mid}/analyze", json={"kind": "summary"}, headers=H)
    assert r.status_code == 400 and "No AI provider" in r.json()["detail"]


def test_ui_served(client):
    assert "AI Meeting Notes" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_ics_parsing():
    from datetime import datetime, timedelta

    now = datetime.now().astimezone()
    start = (now + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
    ics = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:1\nSUMMARY:Team sync\n"
        f"DTSTART:{start}\nDESCRIPTION:Join https://teams.microsoft.com/l/meetup-join/abc\n"
        'ATTENDEE;CN="Ann Lee":mailto:ann@example.com\nEND:VEVENT\nEND:VCALENDAR\n'
    )
    events = _events_basic(ics, now, now + timedelta(days=1))
    assert len(events) == 1 and events[0].app == "teams" and events[0].attendees == ["Ann Lee"]
