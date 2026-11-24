"""Engine interface for offline speech-to-text.

An ``Engine`` creates one ``Recognizer`` per audio source. A recognizer is fed
float32 mono 16 kHz chunks and returns ``RecognitionEvent`` objects: partial
(live, may change) or final (committed to the transcript).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


class EngineUnavailable(RuntimeError):
    pass


@dataclass
class RecognitionEvent:
    text: str
    final: bool
    # Optional timing in seconds of *stream* time (audio fed to this recognizer).
    start: float | None = None
    end: float | None = None


class Recognizer(ABC):
    @abstractmethod
    def accept(self, pcm: np.ndarray) -> list[RecognitionEvent]:
        """Feed audio, return any new events."""

    def flush(self) -> list[RecognitionEvent]:
        """Finalize pending audio (called on pause / stop)."""
        return []

    def close(self) -> None:
        pass


class Engine(ABC):
    name: str = ""
    label: str = ""
    description: str = ""
    platforms: tuple[str, ...] = ("win32", "darwin", "linux")
    supports_auto_language: bool = False

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """(available, human readable reason / install hint)."""

    @abstractmethod
    def create(self, language: str) -> Recognizer: ...

    def info(self) -> dict:
        ok, reason = self.availability()
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "available": ok,
            "reason": reason,
            "auto_language": self.supports_auto_language,
        }
