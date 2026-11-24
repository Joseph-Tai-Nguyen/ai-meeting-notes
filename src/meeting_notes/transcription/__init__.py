"""Offline speech-to-text engines. No network or AI service is used here."""

from __future__ import annotations

from pathlib import Path

from meeting_notes.config import TranscriptionSettings
from meeting_notes.transcription.base import Engine, EngineUnavailable, RecognitionEvent, Recognizer
from meeting_notes.transcription.macos_engine import MacOSEngine
from meeting_notes.transcription.mock_engine import MockEngine
from meeting_notes.transcription.vosk_engine import VoskEngine
from meeting_notes.transcription.whisper_engine import WhisperEngine
from meeting_notes.transcription.windows_engine import WindowsSapiEngine


def build_engines(ts: TranscriptionSettings, data_dir: Path) -> dict[str, Engine]:
    engines: list[Engine] = [
        VoskEngine(Path(data_dir) / "models", ts.vosk_model_dir),
        WhisperEngine(ts.whisper_model, ts.whisper_device, ts.whisper_compute_type),
        MacOSEngine(),
        WindowsSapiEngine(),
        MockEngine(),
    ]
    return {e.name: e for e in engines}


__all__ = ["Engine", "EngineUnavailable", "RecognitionEvent", "Recognizer", "build_engines"]
