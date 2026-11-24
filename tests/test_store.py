import pytest

from meeting_notes.models import Segment
from meeting_notes.storage.search import retrieve, search
from meeting_notes.storage.store import NotFound, StoreError


def _seed(store, title="Weekly sync"):
    m = store.create(title, "online")
    store.append_segment(m.id, Segment(1, 0.0, 2.0, "Me", "Let's review the budget for Q3", "mic"))
    store.append_segment(m.id, Segment(2, 2.5, 5.0, "Others", "The launch date moves to March", "system"))
    return m


def test_create_and_roundtrip(store):
    m = _seed(store)
    assert store.get(m.id).title == "Weekly sync"
    segs = store.segments(m.id)
    assert [s.speaker for s in segs] == ["Me", "Others"]
    assert "budget" in store.transcript_text(m.id)
    assert (store.path(m.id) / "transcript.jsonl").read_text(encoding="utf-8").count("\n") == 2


def test_torn_line_is_tolerated(store):
    m = _seed(store)
    with open(store.path(m.id) / "transcript.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "start": 6')  # simulated crash mid-write
    assert len(store.segments(m.id)) == 2


def test_edit_and_rename(store):
    m = _seed(store)
    seg = store.edit_segment(m.id, 2, text="The launch moves to April")
    assert seg.edited and "April" in seg.text
    assert store.rename_speaker(m.id, "Others", "Alice") == 1
    assert store.segments(m.id)[1].speaker == "Alice"
    assert "Alice" in (store.path(m.id) / "transcript.md").read_text(encoding="utf-8")


def test_notes_and_analysis(store):
    m = _seed(store)
    store.write_notes(m.id, "- budget is tight")
    store.write_analysis(m.id, "summary", "## Overview\nok", {"provider": "fake", "model": "x"})
    assert store.notes(m.id).startswith("- budget")
    assert store.analysis(m.id, "summary").startswith("## Overview")
    assert store.get(m.id).analyses["summary"]["provider"] == "fake"
    with pytest.raises(StoreError):
        store.write_analysis(m.id, "../evil", "x", {})


def test_delete_moves_to_trash_and_restore(store):
    m = _seed(store)
    dest = store.delete(m.id)
    assert dest.parent == store.trash_dir and dest.exists()
    with pytest.raises(NotFound):
        store.get(m.id)
    assert store.restore(dest.name).id == m.id


def test_invalid_ids_rejected(store):
    for bad in ("../x", "a/b", "", "..\\x"):
        with pytest.raises(NotFound):
            store.get(bad)


def test_search_and_retrieve(store):
    a = _seed(store, "Budget review")
    _seed(store, "Other meeting")
    hits = search(store, "launch march")
    assert len(hits) == 2
    assert search(store, "budget review")[0].meeting_id == a.id
    ex = retrieve(store, "When is the launch date?")
    assert ex and "launch" in ex[0].text.lower()
