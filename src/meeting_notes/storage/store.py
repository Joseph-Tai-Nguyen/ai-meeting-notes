"""Text-file storage for meetings.

Layout (one folder per meeting, everything is plain text)::

    <data_dir>/meetings/<meeting_id>/
        meeting.json        metadata
        transcript.jsonl    one JSON segment per line, appended live (crash safe)
        transcript.md       human-readable transcript, regenerated on stop / edit
        notes.md            the user's own notes
        analysis/<kind>.md  AI output (summary, action_items, ...)
    <data_dir>/trash/<meeting_id>/   deleted meetings (recoverable)

Audio is never stored.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
from datetime import datetime
from pathlib import Path

from meeting_notes.models import Highlight, Meeting, Segment, format_ts, now_iso

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_KIND_RE = re.compile(r"^[a-z0-9_]{1,40}$")


class StoreError(Exception):
    pass


class NotFound(StoreError):
    pass


def _check_id(meeting_id: str) -> str:
    if not _ID_RE.match(meeting_id or ""):
        raise NotFound(f"invalid meeting id: {meeting_id!r}")
    return meeting_id


def _check_kind(kind: str) -> str:
    if not _KIND_RE.match(kind or ""):
        raise StoreError(f"invalid analysis kind: {kind!r}")
    return kind


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class MeetingStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.meetings_dir = self.data_dir / "meetings"
        self.trash_dir = self.data_dir / "trash"
        self.meetings_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ paths
    def path(self, meeting_id: str) -> Path:
        return self.meetings_dir / _check_id(meeting_id)

    def _require(self, meeting_id: str) -> Path:
        p = self.path(meeting_id)
        if not (p / "meeting.json").is_file():
            raise NotFound(f"meeting not found: {meeting_id}")
        return p

    # --------------------------------------------------------------- meetings
    def create(self, title: str = "", mode: str = "online", **extra) -> Meeting:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        meeting_id = f"{stamp}-{secrets.token_hex(2)}"
        title = title.strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        meeting = Meeting(id=meeting_id, title=title, mode=mode, **extra)
        with self._lock:
            folder = self.path(meeting_id)
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "transcript.jsonl").touch()
            (folder / "notes.md").write_text("", encoding="utf-8")
            self.save(meeting)
        return meeting

    def save(self, meeting: Meeting) -> Meeting:
        meeting.updated_at = now_iso()
        with self._lock:
            _atomic_write(self.path(meeting.id) / "meeting.json", json.dumps(meeting.to_dict(), indent=2, ensure_ascii=False))
        return meeting

    def get(self, meeting_id: str) -> Meeting:
        p = self._require(meeting_id)
        return Meeting.from_dict(json.loads((p / "meeting.json").read_text(encoding="utf-8")))

    def update(self, meeting_id: str, **changes) -> Meeting:
        with self._lock:
            meeting = self.get(meeting_id)
            for key, value in changes.items():
                if key == "highlights":
                    value = [h if isinstance(h, Highlight) else Highlight(**h) for h in value]
                if hasattr(meeting, key) and key not in ("id", "created_at"):
                    setattr(meeting, key, value)
            return self.save(meeting)

    def list(self) -> list[Meeting]:
        out: list[Meeting] = []
        for folder in self.meetings_dir.iterdir():
            meta = folder / "meeting.json"
            if folder.is_dir() and meta.is_file():
                try:
                    out.append(Meeting.from_dict(json.loads(meta.read_text(encoding="utf-8"))))
                except (json.JSONDecodeError, KeyError):
                    continue
        out.sort(key=lambda m: m.created_at, reverse=True)
        return out

    def delete(self, meeting_id: str) -> Path:
        """Move a meeting to the trash folder (recoverable)."""
        with self._lock:
            src = self._require(meeting_id)
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            dest = self.trash_dir / meeting_id
            if dest.exists():
                dest = self.trash_dir / f"{meeting_id}-{secrets.token_hex(2)}"
            shutil.move(str(src), str(dest))
            return dest

    def restore(self, trashed_name: str) -> Meeting:
        with self._lock:
            src = self.trash_dir / _check_id(trashed_name)
            meta = json.loads((src / "meeting.json").read_text(encoding="utf-8"))
            dest = self.path(meta["id"])
            if dest.exists():
                raise StoreError(f"meeting already exists: {meta['id']}")
            shutil.move(str(src), str(dest))
            return self.get(meta["id"])

    # ------------------------------------------------------------- transcript
    def append_segment(self, meeting_id: str, segment: Segment) -> None:
        line = json.dumps(segment.to_dict(), ensure_ascii=False)
        with self._lock:
            with open(self._require(meeting_id) / "transcript.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()

    def segments(self, meeting_id: str) -> list[Segment]:
        path = self._require(meeting_id) / "transcript.jsonl"
        out: list[Segment] = []
        if not path.is_file():
            return out
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(Segment.from_dict(json.loads(raw)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue  # tolerate a torn last line after a crash
        out.sort(key=lambda s: (s.start, s.seq))
        return out

    def replace_segments(self, meeting_id: str, segments: list[Segment]) -> None:
        text = "".join(json.dumps(s.to_dict(), ensure_ascii=False) + "\n" for s in segments)
        with self._lock:
            _atomic_write(self._require(meeting_id) / "transcript.jsonl", text)
            self.write_transcript_md(meeting_id)

    def edit_segment(self, meeting_id: str, seq: int, text: str | None = None, speaker: str | None = None) -> Segment:
        with self._lock:
            segs = self.segments(meeting_id)
            for seg in segs:
                if seg.seq == seq:
                    if text is not None:
                        seg.text = text.strip()
                    if speaker is not None:
                        seg.speaker = speaker.strip()
                    seg.edited = True
                    self.replace_segments(meeting_id, segs)
                    return seg
        raise NotFound(f"segment {seq} not found")

    def rename_speaker(self, meeting_id: str, old: str, new: str) -> int:
        with self._lock:
            segs = self.segments(meeting_id)
            count = 0
            for seg in segs:
                if seg.speaker == old:
                    seg.speaker = new.strip()
                    count += 1
            if count:
                self.replace_segments(meeting_id, segs)
            return count

    def transcript_text(self, meeting_id: str) -> str:
        return "\n".join(s.line() for s in self.segments(meeting_id))

    def write_transcript_md(self, meeting_id: str) -> Path:
        meeting = self.get(meeting_id)
        lines = [
            f"# {meeting.title}",
            "",
            f"- Date: {meeting.created_at}",
            f"- Duration: {format_ts(meeting.duration)}",
            f"- Mode: {meeting.mode}",
        ]
        if meeting.attendees:
            lines.append(f"- Attendees: {', '.join(meeting.attendees)}")
        lines += ["", "---", ""]
        for seg in self.segments(meeting_id):
            lines.append(f"**[{format_ts(seg.start)}] {seg.speaker}:** {seg.text}")
            lines.append("")
        path = self.path(meeting_id) / "transcript.md"
        _atomic_write(path, "\n".join(lines))
        return path

    # ------------------------------------------------------------------ notes
    def notes(self, meeting_id: str) -> str:
        p = self._require(meeting_id) / "notes.md"
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def write_notes(self, meeting_id: str, text: str) -> None:
        with self._lock:
            _atomic_write(self._require(meeting_id) / "notes.md", text)
            self.save(self.get(meeting_id))

    # --------------------------------------------------------------- analysis
    def write_analysis(self, meeting_id: str, kind: str, text: str, meta: dict) -> None:
        kind = _check_kind(kind)
        with self._lock:
            _atomic_write(self._require(meeting_id) / "analysis" / f"{kind}.md", text)
            meeting = self.get(meeting_id)
            meeting.analyses[kind] = {**meta, "created_at": now_iso()}
            self.save(meeting)

    def append_analysis(self, meeting_id: str, kind: str, text: str) -> None:
        kind = _check_kind(kind)
        with self._lock:
            path = self._require(meeting_id) / "analysis" / f"{kind}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text)

    def analysis(self, meeting_id: str, kind: str) -> str | None:
        p = self._require(meeting_id) / "analysis" / f"{_check_kind(kind)}.md"
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def analyses(self, meeting_id: str) -> dict[str, str]:
        folder = self._require(meeting_id) / "analysis"
        if not folder.is_dir():
            return {}
        return {p.stem: p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.md"))}
