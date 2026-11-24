import io
import json
import zipfile

import pytest

from meeting_notes.models import Segment
from meeting_notes.storage.export import backup_zip, export_meeting, restore_zip
from meeting_notes.storage.store import MeetingStore, StoreError


@pytest.fixture
def meeting(store):
    m = store.create("Design review", "in_person")
    store.append_segment(m.id, Segment(1, 1.0, 3.5, "Speaker", "We agreed on the blue theme"))
    store.write_notes(m.id, "Theme decided")
    store.write_analysis(m.id, "summary", "## Overview\nTheme chosen.", {"provider": "fake"})
    return m


def test_export_formats(store, meeting):
    name, md = export_meeting(store, meeting.id, "md")
    assert name.endswith(".md") and "# Design review" in md and "## Summary" in md and "blue theme" in md
    _, txt = export_meeting(store, meeting.id, "txt")
    assert "[00:00:01] Speaker: We agreed" in txt
    _, srt = export_meeting(store, meeting.id, "srt")
    assert "00:00:01,000 --> 00:00:03,500" in srt
    _, js = export_meeting(store, meeting.id, "json")
    data = json.loads(js)
    assert data["segments"][0]["text"].startswith("We agreed") and data["notes"] == "Theme decided"
    with pytest.raises(StoreError):
        export_meeting(store, meeting.id, "exe")


def test_backup_restore_roundtrip(store, meeting, tmp_path):
    _, data = backup_zip(store.data_dir)
    other = tmp_path / "restored"
    result = restore_zip(other, data)
    assert result["restored"] == [meeting.id]
    restored = MeetingStore(other)
    assert restored.segments(meeting.id)[0].text.startswith("We agreed")
    again = restore_zip(other, data)
    assert again["skipped"] == [meeting.id]


def test_restore_rejects_path_traversal(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
        zf.writestr("meetings/../../evil2.txt", "x")
        zf.writestr("other/file.txt", "x")
    target = tmp_path / "d"
    target.mkdir()
    restore_zip(target, buf.getvalue())
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "evil2.txt").exists()
    assert not (target / "other").exists()


def test_restore_bad_zip(tmp_path):
    with pytest.raises(StoreError):
        restore_zip(tmp_path, b"not a zip")
