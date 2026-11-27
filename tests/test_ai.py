import pytest

from conftest import FakeProvider
from meeting_notes.ai import antigravity_cli
from meeting_notes.ai.analysis import Analyzer
from meeting_notes.ai.antigravity_cli import AntigravityCLIProvider
from meeting_notes.ai.base import AIError
from meeting_notes.ai.prompts import PromptLibrary, render
from meeting_notes.ai.router import AIRouter
from meeting_notes.config import AISettings
from meeting_notes.models import Segment
from meeting_notes.storage.store import StoreError


def _meeting(store, n=3):
    m = store.create("Planning", "online")
    for i in range(n):
        store.append_segment(m.id, Segment(i + 1, i * 10.0, i * 10 + 5.0, "Me", f"Point number {i} about the roadmap"))
    store.write_notes(m.id, "Remember the deadline")
    return m


def _analyzer(store, *providers, **ai_kwargs):
    router = AIRouter({p.name: p for p in providers}, [p.name for p in providers])
    return Analyzer(store, router, PromptLibrary(store.data_dir / "prompts"), AISettings(**ai_kwargs))


def test_router_falls_back():
    bad, good = FakeProvider("a", fail=True), FakeProvider("b", reply="ok")
    off = FakeProvider("c", available=False)
    r = AIRouter({"c": off, "a": bad, "b": good}, ["c", "a", "b"])
    res = r.generate("hi")
    assert res.text == "ok" and res.provider == "b" and bad.prompts == ["hi"] and off.prompts == []
    with pytest.raises(AIError):
        AIRouter({"a": bad}, ["a"]).generate("x")


def test_summary_written_with_context(store):
    m = _meeting(store)
    fake = FakeProvider()
    out = _analyzer(store, fake).run(m.id, "summary", "standup")
    assert out.provider == "fake"
    prompt = fake.prompts[0]
    assert "Remember the deadline" in prompt and "[00:00:10] Me: Point number 1" in prompt and "Yesterday" in prompt
    assert "{{" not in prompt
    assert store.analysis(m.id, "summary").startswith("## Overview")
    assert store.get(m.id).analyses["summary"]["template"] == "standup"


def test_all_task_kinds_render(store):
    m = _meeting(store)
    fake = FakeProvider()
    an = _analyzer(store, fake)
    for kind in ("action_items", "decisions", "follow_up_email", "speakers", "draft_doc"):
        an.run(m.id, kind, doc_type="PRD")
    assert "PRD" in fake.prompts[-1]
    assert set(store.analyses(m.id)) == {"action_items", "decisions", "follow_up_email", "speakers", "draft_doc"}


def test_long_transcript_is_condensed(store):
    m = _meeting(store, n=40)
    fake = FakeProvider(reply="part notes")
    _analyzer(store, fake, max_chunk_chars=400).run(m.id, "summary")
    assert len(fake.prompts) > 2
    assert "part 1 of" in fake.prompts[0] and "condensed notes" in fake.prompts[-1]


def test_ask_and_ask_all(store):
    m = _meeting(store)
    fake = FakeProvider(reply="The deadline is Friday [00:00:10]")
    an = _analyzer(store, fake)
    an.ask(m.id, "What is the deadline?")
    assert "### Q: What is the deadline?" in store.analysis(m.id, "qa")
    res = an.ask_all("roadmap points")
    assert res["sources"] and res["sources"][0]["meeting_id"] == m.id
    assert an.ask_all("zebra")["provider"] == ""


def test_empty_meeting_errors(store):
    m = store.create("Empty")
    with pytest.raises(StoreError):
        _analyzer(store, FakeProvider()).run(m.id, "summary")


def test_templates_and_user_override(store):
    lib = PromptLibrary(store.data_dir / "prompts")
    names = [t["name"] for t in lib.summary_templates()]
    assert names[0] == "general" and {"standup", "sales_call", "one_on_one"} <= set(names)
    custom = store.data_dir / "prompts" / "summary"
    custom.mkdir(parents=True)
    (custom / "retro.md").write_text("<!-- label: Retro -->\n{{context}}\nWhat went well?", encoding="utf-8")
    assert {"name": "retro", "label": "Retro"} in lib.summary_templates()
    assert render("a {{x}} {{missing}}", {"x": "1"}) == "a 1\n"


def test_router_maps_legacy_gemini_cli_to_agy():
    provs = {n: FakeProvider(n) for n in ("gemini_api", "agy", "claude_code")}
    r = AIRouter(provs, ["gemini_api", "gemini_cli", "claude_code"])
    assert r.order == ["gemini_api", "agy", "claude_code"]


def test_antigravity_cli_provider(monkeypatch):
    import json

    monkeypatch.setattr("shutil.which", lambda _exe: None)
    p = AntigravityCLIProvider(model="gemini-4")
    ok, reason = p.availability()
    assert not ok and "agy" in reason

    monkeypatch.setattr("shutil.which", lambda _exe: "/usr/local/bin/agy")
    ok, reason = p.availability()
    assert ok and "gemini-4" in reason

    captured: list[tuple[list[str], str, int, bool]] = []

    def fake_run_cli(cmd, stdin_text, timeout, check=True):
        captured.append((cmd, stdin_text, timeout, check))
        return (
            '{"event":"init","conversation_id":"c1"}\n'
            '{"event":"result","result":{"status":"SUCCESS","response":"## Summary\\nDone\\n"}}\n'
        )

    monkeypatch.setattr(antigravity_cli, "run_cli", fake_run_cli)
    out = p.generate("transcript text", system="sys")
    assert out == "## Summary\nDone"
    cmd, stdin_text, _timeout, check = captured[0]
    assert cmd[:6] == ["agy", "--input-format", "stream-json", "--output-format", "stream-json", "--disable-slash-commands"]
    assert "--model" in cmd and "gemini-4" in cmd
    assert check is False
    sent = json.loads(stdin_text)
    assert sent["event"] == "user"
    assert "sys" in sent["message"]["content"] and "transcript text" in sent["message"]["content"]

    def fail_result(_cmd, _stdin, _timeout, check=True):
        return '{"event":"result","result":{"status":"ERROR","error":"unauthenticated"}}\n'

    monkeypatch.setattr(antigravity_cli, "run_cli", fail_result)
    with pytest.raises(AIError, match="run `agy` in a terminal"):
        p.generate("hi")

    def fail_cli(_cmd, _stdin, _timeout, check=True):
        raise AIError("agy exited with 1: login required")

    monkeypatch.setattr(antigravity_cli, "run_cli", fail_cli)
    with pytest.raises(AIError, match="run `agy` in a terminal"):
        p.generate("hi")
