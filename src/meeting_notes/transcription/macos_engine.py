"""macOS native speech recognition (Apple Speech framework, on-device) - EXPERIMENTAL.

Uses SFSpeechRecognizer with SFSpeechAudioBufferRecognitionRequest and
``requiresOnDeviceRecognition`` so audio never leaves the Mac (macOS 13+ on
Apple Silicon has on-device models for most major languages).

Requirements
------------
* ``pip install -e .[macos]`` (pyobjc Speech + AVFoundation bindings)
* macOS privacy (TCC) requires the *host app* to declare
  ``NSSpeechRecognitionUsageDescription`` and ``NSMicrophoneUsageDescription``
  in its Info.plist. A bare ``python`` from Terminal may be killed by the OS
  when it requests permission. Use the packaged app (see docs/packaging.md) or
  fall back to the Vosk / Whisper engines, which need no special permission
  beyond microphone access.
"""

from __future__ import annotations

import sys
import threading
import time

import numpy as np

from meeting_notes.transcription.base import Engine, EngineUnavailable, RecognitionEvent, Recognizer
from meeting_notes.transcription.segmenter import UtteranceSegmenter

_LOCALES = {
    "en": "en-US", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "it": "it-IT", "pt": "pt-BR",
    "ja": "ja-JP", "zh": "zh-CN", "ko": "ko-KR", "vi": "vi-VN", "ru": "ru-RU", "nl": "nl-NL",
}
_TASK_MAX_S = 50.0  # rotate requests well before Apple's per-request limits


class MacSpeechRecognizer(Recognizer):
    def __init__(self, language: str):
        import AVFoundation  # type: ignore
        import Foundation  # type: ignore
        import Speech  # type: ignore

        self._Speech = Speech
        self._AV = AVFoundation
        locale = Foundation.NSLocale.alloc().initWithLocaleIdentifier_(_LOCALES.get(language, language))
        self.rec = Speech.SFSpeechRecognizer.alloc().initWithLocale_(locale)
        if self.rec is None or not self.rec.isAvailable():
            raise EngineUnavailable(f"Apple speech recognizer not available for '{language}'")
        self.on_device = bool(self.rec.supportsOnDeviceRecognition())
        self.rec.setQueue_(Foundation.NSOperationQueue.alloc().init())
        self.fmt = AVFoundation.AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
            AVFoundation.AVAudioPCMFormatFloat32, 16000.0, 1, False
        )
        self._lock = threading.Lock()
        self._events: list[RecognitionEvent] = []
        self._seg = UtteranceSegmenter(min_silence_s=0.8)
        self._task_started = 0.0
        self._req = None
        self._task = None
        self._start_task()

    def _start_task(self) -> None:
        req = self._Speech.SFSpeechAudioBufferRecognitionRequest.alloc().init()
        req.setShouldReportPartialResults_(True)
        if self.on_device:
            req.setRequiresOnDeviceRecognition_(True)

        def handler(result, error):
            if result is not None:
                text = str(result.bestTranscription().formattedString()).strip()
                with self._lock:
                    self._events.append(RecognitionEvent(text, bool(result.isFinal())))

        self._task = self.rec.recognitionTaskWithRequest_resultHandler_(req, handler)
        self._req = req
        self._task_started = time.monotonic()

    def _rotate(self) -> None:
        if self._req is not None:
            self._req.endAudio()
        self._start_task()

    def _buffer(self, pcm: np.ndarray):
        n = len(pcm)
        buf = self._AV.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(self.fmt, n)
        buf.setFrameLength_(n)
        channel = buf.floatChannelData()[0]
        try:
            np.frombuffer(channel.as_buffer(n), dtype=np.float32)[:] = pcm
        except (AttributeError, TypeError, ValueError):
            for i, v in enumerate(pcm.tolist()):  # slow fallback for older pyobjc
                channel[i] = v
        return buf

    def _drain(self) -> list[RecognitionEvent]:
        with self._lock:
            events, self._events = self._events, []
        return events

    def accept(self, pcm: np.ndarray) -> list[RecognitionEvent]:
        if pcm.size:
            self._req.appendAudioPCMBuffer_(self._buffer(pcm.astype(np.float32, copy=False)))
            ended = self._seg.feed(pcm)
            if ended or time.monotonic() - self._task_started > _TASK_MAX_S:
                self._rotate()
        return self._drain()

    def flush(self) -> list[RecognitionEvent]:
        self._rotate()
        time.sleep(0.8)  # give the final result a moment to arrive
        return self._drain()

    def close(self) -> None:
        if self._task is not None:
            self._task.cancel()


class MacOSEngine(Engine):
    name = "macos"
    label = "macOS Speech (on-device) - experimental"
    description = "Apple's built-in recognizer, on-device when supported. Needs the packaged app for permissions."
    platforms = ("darwin",)

    def availability(self) -> tuple[bool, str]:
        if sys.platform != "darwin":
            return False, "macOS only"
        try:
            import Speech  # type: ignore
        except ImportError:
            return False, "pip install -e .[macos]"
        status = Speech.SFSpeechRecognizer.authorizationStatus()
        # 0 notDetermined, 1 denied, 2 restricted, 3 authorized
        if status in (1, 2):
            return False, "speech recognition permission denied (System Settings > Privacy & Security)"
        return True, "on-device when supported" + ("" if status == 3 else " (permission will be requested)")

    def create(self, language: str) -> Recognizer:
        ok, reason = self.availability()
        if not ok:
            raise EngineUnavailable(reason)
        import Speech  # type: ignore

        if Speech.SFSpeechRecognizer.authorizationStatus() == 0:
            done = threading.Event()
            Speech.SFSpeechRecognizer.requestAuthorization_(lambda _status: done.set())
            done.wait(30)
        return MacSpeechRecognizer(language or "en")
