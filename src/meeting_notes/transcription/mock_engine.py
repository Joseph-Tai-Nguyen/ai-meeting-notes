"""Test engine: detects speech with the energy segmenter and emits placeholder text.

Lets you exercise capture, the live UI, storage and export without installing
any speech model. Also used by the test-suite.
"""

from __future__ import annotations

import numpy as np

from meeting_notes.transcription.base import Engine, RecognitionEvent, Recognizer
from meeting_notes.transcription.segmenter import UtteranceSegmenter


class MockRecognizer(Recognizer):
    def __init__(self):
        self.seg = UtteranceSegmenter()
        self.count = 0
        self._partial_shown = False

    def _finals(self, utterances) -> list[RecognitionEvent]:
        events = []
        for start, audio in utterances:
            self.count += 1
            dur = len(audio) / 16000
            events.append(RecognitionEvent(f"(speech #{self.count}, {dur:.1f}s)", True, start, start + dur))
            self._partial_shown = False
        return events

    def accept(self, pcm: np.ndarray) -> list[RecognitionEvent]:
        events = self._finals(self.seg.feed(pcm))
        if self.seg.in_speech and not self._partial_shown:
            self._partial_shown = True
            events.append(RecognitionEvent("(listening…)", False))
        return events

    def flush(self) -> list[RecognitionEvent]:
        return self._finals(self.seg.flush())


class MockEngine(Engine):
    name = "mock"
    label = "Test engine (no recognition)"
    description = "Marks where speech happened. For checking audio capture and the UI without models."
    supports_auto_language = True

    def availability(self) -> tuple[bool, str]:
        return True, "always available"

    def create(self, language: str) -> Recognizer:
        return MockRecognizer()
