"""faster-whisper - local Whisper models (higher accuracy, 99 languages, auto language).

Runs fully offline after the model is downloaded once (Hugging Face cache, or
set ``whisper_model`` to a local folder). Works on CPU (int8) or NVIDIA GPU.
Utterances are cut at pauses by the energy segmenter and recognized as soon as
the speaker stops, so text appears ~1-3 s after each sentence.
"""

from __future__ import annotations

import threading

import numpy as np

from meeting_notes.transcription.base import Engine, EngineUnavailable, RecognitionEvent, Recognizer
from meeting_notes.transcription.segmenter import UtteranceSegmenter

_MODELS: dict[tuple, object] = {}
_LOCK = threading.Lock()


class WhisperRecognizer(Recognizer):
    def __init__(self, model, language: str | None, partial_interval_s: float = 0.0):
        self.model = model
        self.language = language
        self.seg = UtteranceSegmenter(max_utterance_s=20.0)
        self.partial_interval_s = partial_interval_s
        self._last_partial_len = 0.0

    def _transcribe(self, audio: np.ndarray) -> str:
        segments, _info = self.model.transcribe(
            audio, language=self.language, beam_size=1, vad_filter=False,
            condition_on_previous_text=False, without_timestamps=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def _finals(self, utterances) -> list[RecognitionEvent]:
        events = []
        for start, audio in utterances:
            text = self._transcribe(audio)
            if text:
                events.append(RecognitionEvent(text, True, start, start + len(audio) / 16000))
            else:
                events.append(RecognitionEvent("", False))
        self._last_partial_len = 0.0
        return events

    def accept(self, pcm: np.ndarray) -> list[RecognitionEvent]:
        events = self._finals(self.seg.feed(pcm))
        if self.partial_interval_s > 0:
            pending = self.seg.pending()
            if pending:
                dur = len(pending[1]) / 16000
                if dur - self._last_partial_len >= self.partial_interval_s:
                    self._last_partial_len = dur
                    text = self._transcribe(pending[1])
                    if text:
                        events.append(RecognitionEvent(text, False, pending[0]))
        return events

    def flush(self) -> list[RecognitionEvent]:
        return self._finals(self.seg.flush())


class WhisperEngine(Engine):
    name = "whisper"
    label = "Whisper (faster-whisper, offline)"
    description = "Best accuracy and auto language detection; heavier on CPU. Text appears after each sentence."
    supports_auto_language = True

    def __init__(self, model: str = "small", device: str = "auto", compute_type: str = "int8", partial_interval_s: float = 0.0):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.partial_interval_s = partial_interval_s

    def availability(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # type: ignore  # noqa: F401
        except ImportError:
            return False, "pip install -e .[whisper]"
        return True, f"model: {self.model_name} (downloaded on first use)"

    def create(self, language: str) -> Recognizer:
        ok, reason = self.availability()
        if not ok:
            raise EngineUnavailable(f"Whisper unavailable: {reason}")
        from faster_whisper import WhisperModel  # type: ignore

        key = (self.model_name, self.device, self.compute_type)
        with _LOCK:
            if key not in _MODELS:
                _MODELS[key] = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
            model = _MODELS[key]
        lang = None if language in ("", "auto") else language
        return WhisperRecognizer(model, lang, self.partial_interval_s)
