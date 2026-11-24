"""Vosk (Kaldi) - true streaming, low CPU, fully offline. Default engine.

Models: https://alphacephei.com/vosk/models  (run scripts/download_models.py)
Expected location: <data_dir>/models/vosk/<language>/  (folder containing 'am', 'conf', ...)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from meeting_notes.transcription.base import Engine, EngineUnavailable, RecognitionEvent, Recognizer

_MODEL_CACHE: dict[str, object] = {}
_CACHE_LOCK = threading.Lock()


def _to_pcm16(pcm: np.ndarray) -> bytes:
    return (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class VoskRecognizer(Recognizer):
    def __init__(self, model):
        from vosk import KaldiRecognizer  # type: ignore

        self._rec = KaldiRecognizer(model, 16000)
        self._last_partial = ""

    def accept(self, pcm: np.ndarray) -> list[RecognitionEvent]:
        if pcm.size == 0:
            return []
        if self._rec.AcceptWaveform(_to_pcm16(pcm)):
            text = json.loads(self._rec.Result()).get("text", "").strip()
            self._last_partial = ""
            return [RecognitionEvent(text, final=True)] if text else [RecognitionEvent("", final=False)]
        partial = json.loads(self._rec.PartialResult()).get("partial", "").strip()
        if partial != self._last_partial:
            self._last_partial = partial
            return [RecognitionEvent(partial, final=False)]
        return []

    def flush(self) -> list[RecognitionEvent]:
        text = json.loads(self._rec.FinalResult()).get("text", "").strip()
        self._last_partial = ""
        return [RecognitionEvent(text, final=True)] if text else []


class VoskEngine(Engine):
    name = "vosk"
    label = "Vosk (offline, streaming)"
    description = "Lightweight real-time recognizer. Small models (~50 MB) per language."

    def __init__(self, models_root: Path, model_dir_override: str = ""):
        self.models_root = Path(models_root)
        self.model_dir_override = model_dir_override

    def model_path(self, language: str) -> Path:
        if self.model_dir_override:
            return Path(self.model_dir_override).expanduser()
        return self.models_root / "vosk" / language

    def availability(self) -> tuple[bool, str]:
        try:
            import vosk  # type: ignore  # noqa: F401
        except ImportError:
            return False, "pip install -e .[vosk]"
        root = self.models_root / "vosk"
        if self.model_dir_override:
            ok = Path(self.model_dir_override).expanduser().is_dir()
            return ok, "" if ok else f"model folder not found: {self.model_dir_override}"
        langs = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        if not langs:
            return False, "no model installed: python scripts/download_models.py vosk en"
        return True, "models: " + ", ".join(langs)

    def create(self, language: str) -> Recognizer:
        ok, reason = self.availability()
        if not ok:
            raise EngineUnavailable(f"Vosk unavailable: {reason}")
        path = self.model_path(language)
        if not path.is_dir():
            raise EngineUnavailable(f"No Vosk model for '{language}'. Run: python scripts/download_models.py vosk {language}")
        from vosk import Model, SetLogLevel  # type: ignore

        SetLogLevel(-1)
        key = str(path.resolve())
        with _CACHE_LOCK:
            if key not in _MODEL_CACHE:
                _MODEL_CACHE[key] = Model(key)
            model = _MODEL_CACHE[key]
        return VoskRecognizer(model)
