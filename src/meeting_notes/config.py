"""Application settings.

Settings live in ``<data_dir>/settings.json`` (plain text, human editable).
Secrets such as ``GEMINI_API_KEY`` are read from the environment (or a local
``.env`` file) and are never written to disk by the app.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

APP_NAME = "AIMeetingNotes"
DATA_DIR_ENV = "MEETING_NOTES_DATA_DIR"


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def default_data_dir() -> Path:
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / "Documents" / APP_NAME


@dataclass
class TranscriptionSettings:
    engine: str = "vosk"  # vosk | whisper | macos | windows_sapi | mock
    language: str = "en"  # ISO code; "auto" is supported by whisper only
    vosk_model_dir: str = ""  # empty -> <data_dir>/models/vosk/<language>
    whisper_model: str = "small"  # tiny | base | small | medium | large-v3 | path
    whisper_device: str = "auto"  # auto | cpu | cuda
    whisper_compute_type: str = "int8"
    mic_device: str = ""  # empty -> system default microphone
    system_device: str = ""  # empty -> default speaker loopback (Windows); BlackHole etc. on macOS
    me_label: str = "Me"
    others_label: str = "Others"
    room_label: str = "Speaker"


@dataclass
class AISettings:
    # Tried in order; the first available provider wins, the next is the fallback.
    provider_order: list[str] = field(
        default_factory=lambda: ["gemini_api", "gemini_cli", "claude_code"]
    )
    gemini_model: str = "gemini-flash-latest"
    gemini_cli_model: str = ""  # empty -> Gemini CLI default
    claude_model: str = ""  # empty -> Claude Code default
    output_language: str = ""  # empty -> same language as the transcript
    timeout_seconds: int = 600
    max_chunk_chars: int = 400_000  # longer transcripts are summarised map-reduce style


@dataclass
class Settings:
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    ai: AISettings = field(default_factory=AISettings)
    calendar_ics: list[str] = field(default_factory=list)  # ICS URLs or file paths
    consent_reminder: bool = True
    default_summary_template: str = "general"
    host: str = "127.0.0.1"
    port: int = 8765

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge(cls: type, data: dict[str, Any]) -> Any:
    """Build dataclass ``cls`` from ``data``, ignoring unknown keys."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        default = f.default_factory() if callable(f.default_factory) else f.default  # type: ignore[misc]
        if is_dataclass(default) and isinstance(value, dict):
            value = _merge(type(default), value)
        kwargs[f.name] = value
    return cls(**kwargs)


class SettingsStore:
    """Thread-safe load/save of settings.json."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "settings.json"
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if self.path.is_file():
            try:
                return _merge(Settings, json.loads(self.path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError):
                backup = self.path.with_suffix(".json.bad")
                self.path.replace(backup)
        return Settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def update(self, patch: dict[str, Any]) -> Settings:
        with self._lock:
            current = self._settings.to_dict()
            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(current.get(key), dict):
                    current[key].update(value)
                else:
                    current[key] = value
            self._settings = _merge(Settings, current)
            self.save_locked()
            return self._settings

    def save(self) -> None:
        with self._lock:
            self.save_locked()

    def save_locked(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._settings.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.path)
