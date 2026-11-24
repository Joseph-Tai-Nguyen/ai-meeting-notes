"""Windows built-in desktop speech recognition (System.Speech / SAPI) - EXPERIMENTAL.

Fully offline and pre-installed with Windows language packs that include
"Speech recognition". Accuracy is lower than Whisper/Vosk, but it needs no
model download. Audio from any source (microphone *or* system loopback) is
cut into utterances and fed to the engine through an in-memory stream.

Requires ``pip install -e .[windows]`` (pythonnet).
"""

from __future__ import annotations

import sys
import threading

import numpy as np

from meeting_notes.transcription.base import Engine, EngineUnavailable, RecognitionEvent, Recognizer
from meeting_notes.transcription.segmenter import UtteranceSegmenter

_CULTURES = {
    "en": "en-US", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "ja": "ja-JP", "zh": "zh-CN",
}
_CLR_LOCK = threading.Lock()


_ASSEMBLY = "System.Speech, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"


def _load_clr():
    with _CLR_LOCK:
        import clr  # type: ignore  # pythonnet

        # System.Speech lives in the .NET Framework GAC, which only resolves by its full (strong) name.
        try:
            clr.AddReference(_ASSEMBLY)
        except Exception:  # noqa: BLE001 - fall back to the short name (e.g. .NET Core with the NuGet package)
            clr.AddReference("System.Speech")
        from System.Speech.Recognition import SpeechRecognitionEngine  # type: ignore

        return SpeechRecognitionEngine


def installed_cultures() -> list[str]:
    SpeechRecognitionEngine = _load_clr()
    return [str(r.Culture.Name) for r in SpeechRecognitionEngine.InstalledRecognizers()]


class SapiRecognizer(Recognizer):
    def __init__(self, culture: str):
        SpeechRecognitionEngine = _load_clr()
        from System.Globalization import CultureInfo  # type: ignore
        from System.Speech.Recognition import DictationGrammar  # type: ignore

        self.engine = SpeechRecognitionEngine(CultureInfo(culture))
        self.engine.LoadGrammar(DictationGrammar())
        self.seg = UtteranceSegmenter()

    def _recognize(self, start: float, audio: np.ndarray) -> list[RecognitionEvent]:
        from System import Array, Byte  # type: ignore
        from System.IO import MemoryStream  # type: ignore
        from System.Speech.AudioFormat import AudioBitsPerSample, AudioChannel, SpeechAudioFormatInfo  # type: ignore

        pcm16 = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        stream = MemoryStream(Array[Byte](pcm16))
        self.engine.SetInputToAudioStream(stream, SpeechAudioFormatInfo(16000, AudioBitsPerSample.Sixteen, AudioChannel.Mono))
        texts = []
        try:
            for _ in range(20):
                try:
                    result = self.engine.Recognize()
                except Exception:  # noqa: BLE001 - SAPI throws once the in-memory stream is exhausted
                    break
                if result is None:
                    break
                texts.append(str(result.Text))
        finally:
            self.engine.SetInputToNull()
            stream.Dispose()
        text = " ".join(t for t in texts if t).strip()
        if not text:
            return [RecognitionEvent("", False)]
        return [RecognitionEvent(text, True, start, start + len(audio) / 16000)]

    def accept(self, pcm: np.ndarray) -> list[RecognitionEvent]:
        events: list[RecognitionEvent] = []
        for start, audio in self.seg.feed(pcm):
            events.extend(self._recognize(start, audio))
        return events

    def flush(self) -> list[RecognitionEvent]:
        events: list[RecognitionEvent] = []
        for start, audio in self.seg.flush():
            events.extend(self._recognize(start, audio))
        return events

    def close(self) -> None:
        self.engine.Dispose()


class WindowsSapiEngine(Engine):
    name = "windows_sapi"
    label = "Windows Speech (built-in) - experimental"
    description = "Uses the offline speech recognizer that ships with Windows. No download, lower accuracy."
    platforms = ("win32",)

    def availability(self) -> tuple[bool, str]:
        if sys.platform != "win32":
            return False, "Windows only"
        try:
            cultures = installed_cultures()
        except ImportError:
            return False, "pip install -e .[windows]"
        except Exception as exc:  # noqa: BLE001 - CLR load errors vary
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            return False, f"System.Speech not usable: {first_line[:200]}"
        if not cultures:
            return False, "no speech recognizer installed (Settings > Time & language > Speech)"
        return True, "installed: " + ", ".join(cultures)

    def create(self, language: str) -> Recognizer:
        ok, reason = self.availability()
        if not ok:
            raise EngineUnavailable(reason)
        cultures = installed_cultures()
        wanted = _CULTURES.get(language, language)
        culture = next((c for c in cultures if c.lower() == wanted.lower()), None)
        culture = culture or next((c for c in cultures if c.lower().startswith(language.lower())), None)
        if culture is None:
            raise EngineUnavailable(f"No Windows recognizer for '{language}'. Installed: {', '.join(cultures)}")
        return SapiRecognizer(culture)
