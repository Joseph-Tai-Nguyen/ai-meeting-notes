"""Plain data models. Everything serialises to JSON / Markdown text."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

MODES = ("online", "in_person", "system", "file")
STATUSES = ("idle", "recording", "paused", "done")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def format_ts(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class Segment:
    seq: int
    start: float
    end: float
    speaker: str
    text: str
    source: str = "mic"  # mic | system | file
    edited: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Segment:
        return cls(
            seq=int(d["seq"]),
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            speaker=str(d.get("speaker", "")),
            text=str(d.get("text", "")),
            source=str(d.get("source", "mic")),
            edited=bool(d.get("edited", False)),
        )

    def line(self) -> str:
        return f"[{format_ts(self.start)}] {self.speaker}: {self.text}"


@dataclass
class Highlight:
    t: float
    label: str = ""


@dataclass
class Meeting:
    id: str
    title: str
    created_at: str = field(default_factory=now_iso)
    mode: str = "online"
    status: str = "idle"
    duration: float = 0.0
    language: str = "en"
    engine: str = ""
    attendees: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    consent_confirmed: bool = False
    calendar_event: dict[str, Any] | None = None
    highlights: list[Highlight] = field(default_factory=list)
    # kind -> {"provider", "model", "created_at", "template"}
    analyses: dict[str, dict[str, Any]] = field(default_factory=dict)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Meeting:
        return cls(
            id=d["id"],
            title=d.get("title", "Untitled meeting"),
            created_at=d.get("created_at", now_iso()),
            mode=d.get("mode", "online"),
            status=d.get("status", "idle"),
            duration=float(d.get("duration", 0.0)),
            language=d.get("language", "en"),
            engine=d.get("engine", ""),
            attendees=list(d.get("attendees", [])),
            tags=list(d.get("tags", [])),
            consent_confirmed=bool(d.get("consent_confirmed", False)),
            calendar_event=d.get("calendar_event"),
            highlights=[Highlight(**h) for h in d.get("highlights", [])],
            analyses=dict(d.get("analyses", {})),
            updated_at=d.get("updated_at", now_iso()),
        )
