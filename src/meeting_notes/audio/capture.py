"""Audio sources. Every source delivers float32 mono 16 kHz chunks to a callback.

* ``SoundcardSource(kind="mic")``     - any microphone (Windows / macOS / Linux)
* ``SoundcardSource(kind="loopback")`` - what you hear through speakers *or
  headphones*. Windows: WASAPI loopback of the output device (works for Teams,
  Zoom, Meet, ... with no extra software). macOS: the OS has no loopback API
  for third-party Python apps, so select a virtual device such as BlackHole
  (see docs/audio-capture.md); it is opened as an input.
* ``WavFileSource`` - transcribe an existing recording.
* ``ArraySource``   - in-memory audio, used by tests.
"""

from __future__ import annotations

import sys
import threading
import time
import warnings
import wave
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import numpy as np

TARGET_SAMPLE_RATE = 16_000
CAPTURE_SAMPLE_RATE = 48_000
CHUNK_SECONDS = 0.1

ChunkCallback = Callable[[np.ndarray], None]


class AudioError(RuntimeError):
    pass


def to_mono_16k(data: np.ndarray, sample_rate: int) -> np.ndarray:
    """Down-mix to mono and resample to 16 kHz (float32)."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sample_rate == TARGET_SAMPLE_RATE or data.size == 0:
        return data.astype(np.float32, copy=False)
    if sample_rate % TARGET_SAMPLE_RATE == 0:
        factor = sample_rate // TARGET_SAMPLE_RATE
        usable = (len(data) // factor) * factor
        return data[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)
    n_out = int(round(len(data) * TARGET_SAMPLE_RATE / sample_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_new = np.linspace(0, len(data) - 1, n_out)
    return np.interp(x_new, np.arange(len(data)), data).astype(np.float32)


class AudioSource(ABC):
    """A capture source. ``label`` becomes the speaker label for its segments."""

    def __init__(self, source_id: str, label: str):
        self.source_id = source_id
        self.label = label
        self.on_end: Callable[[], None] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, callback: ChunkCallback) -> None:
        self._stop.clear()
        self._open()  # raise early (device missing, permissions, ...)
        self._thread = threading.Thread(target=self._run_safe, args=(callback,), daemon=True, name=f"audio-{self.source_id}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _open(self) -> None:  # optional pre-flight
        pass

    def _run_safe(self, callback: ChunkCallback) -> None:
        try:
            self._run(callback)
        finally:
            if self.on_end:
                self.on_end()

    @abstractmethod
    def _run(self, callback: ChunkCallback) -> None: ...


def _com_init() -> None:
    """WASAPI (used by soundcard on Windows) needs COM initialised per thread."""
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        except OSError:
            pass


_SOUNDCARD = None
_SOUNDCARD_LOCK = threading.Lock()
_COM_KEEPALIVE = threading.Event()  # never set: keeps the COM init thread (and its apartment) alive


def load_soundcard():
    """Import ``soundcard`` safely and return the module.

    On Windows, soundcard calls CoInitializeEx at import time and treats
    S_FALSE ("COM already initialised on this thread") as a fatal
    "Error 0x100000001". That happens when another component - e.g. the .NET
    runtime loaded by the Windows Speech engine - initialised COM on the same
    thread first. So the first import always runs on a dedicated thread with
    untouched COM state, which then stays alive for the life of the app.
    """
    global _SOUNDCARD
    if _SOUNDCARD is not None:
        return _SOUNDCARD
    with _SOUNDCARD_LOCK:
        if _SOUNDCARD is not None:
            return _SOUNDCARD
        box: dict = {}
        ready = threading.Event()

        def worker() -> None:
            try:
                import soundcard  # type: ignore

                box["module"] = soundcard
            except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
                box["error"] = exc
            ready.set()
            if sys.platform == "win32" and "module" in box:
                _COM_KEEPALIVE.wait()

        threading.Thread(target=worker, daemon=True, name="audio-com-init").start()
        if not ready.wait(30):
            raise AudioError("Timed out initialising the audio system")
        err = box.get("error")
        if isinstance(err, ImportError):
            raise AudioError("Audio capture needs the 'soundcard' package: pip install -e .[audio]") from err
        if err is not None:
            raise AudioError(f"Could not initialise the audio system: {err}") from err
        _SOUNDCARD = box["module"]
        return _SOUNDCARD


_import_soundcard = load_soundcard  # backwards-compatible alias


def _match(devices, name: str):
    name_cf = name.casefold()
    for dev in devices:
        if dev.name.casefold() == name_cf or str(getattr(dev, "id", "")) == name:
            return dev
    for dev in devices:
        if name_cf in dev.name.casefold():
            return dev
    return None


class SoundcardSource(AudioSource):
    def __init__(self, kind: str, device: str = "", label: str = "", source_id: str | None = None):
        if kind not in ("mic", "loopback"):
            raise ValueError("kind must be 'mic' or 'loopback'")
        super().__init__(source_id or ("system" if kind == "loopback" else "mic"), label or kind)
        self.kind = kind
        self.device_name = device
        self._device = None

    def _resolve(self):
        sc = _import_soundcard()
        if self.kind == "mic":
            if self.device_name:
                dev = _match(sc.all_microphones(), self.device_name)
                if dev is None:
                    raise AudioError(f"Microphone not found: {self.device_name}")
                return dev
            dev = sc.default_microphone()
            if dev is None:
                raise AudioError("No microphone available")
            return dev
        # loopback / system audio
        if sys.platform == "darwin":
            if not self.device_name:
                raise AudioError(
                    "macOS: choose a loopback input (e.g. 'BlackHole 2ch') as System audio device in Settings. "
                    "See docs/audio-capture.md."
                )
            dev = _match(sc.all_microphones(include_loopback=True), self.device_name)
            if dev is None:
                raise AudioError(f"System audio device not found: {self.device_name}")
            return dev
        speaker_name = self.device_name or (sc.default_speaker().name if sc.default_speaker() else "")
        if not speaker_name:
            raise AudioError("No output device found for loopback capture")
        loopbacks = [m for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)]
        dev = _match(loopbacks, speaker_name)
        if dev is None:
            raise AudioError(f"No loopback device for output: {speaker_name}")
        return dev

    def _open(self) -> None:
        self._device = self._resolve()

    def _run(self, callback: ChunkCallback) -> None:
        _com_init()
        frames = int(CAPTURE_SAMPLE_RATE * CHUNK_SECONDS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # soundcard warns on loopback "data discontinuity"
            with self._device.recorder(samplerate=CAPTURE_SAMPLE_RATE, blocksize=frames) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=frames)
                    callback(to_mono_16k(data, CAPTURE_SAMPLE_RATE))


class WavFileSource(AudioSource):
    """Reads a PCM WAV file. ``realtime=True`` paces playback like a live meeting."""

    def __init__(self, path: str | Path, label: str = "Speaker", realtime: bool = False):
        super().__init__("file", label)
        self.path = Path(path)
        self.realtime = realtime

    def _open(self) -> None:
        if not self.path.is_file():
            raise AudioError(f"File not found: {self.path}")
        if self.path.suffix.lower() != ".wav":
            raise AudioError("Only PCM .wav files are supported. Convert first, e.g. ffmpeg -i in.m4a -ac 1 -ar 16000 out.wav")

    def _run(self, callback: ChunkCallback) -> None:
        with wave.open(str(self.path), "rb") as wf:
            sr, ch, width = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
            if width not in (1, 2, 4):
                raise AudioError(f"Unsupported sample width: {width}")
            frames = int(sr * 0.5)
            while not self._stop.is_set():
                raw = wf.readframes(frames)
                if not raw:
                    break
                if width == 2:
                    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                elif width == 4:
                    data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
                else:
                    data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
                if ch > 1:
                    data = data.reshape(-1, ch)
                callback(to_mono_16k(data, sr))
                if self.realtime:
                    time.sleep(frames / sr)


class ArraySource(AudioSource):
    """Feeds a numpy array (already 16 kHz mono) in 100 ms chunks."""

    def __init__(self, audio: np.ndarray, label: str = "Speaker", source_id: str = "mic", realtime: bool = False):
        super().__init__(source_id, label)
        self.audio = np.asarray(audio, dtype=np.float32)
        self.realtime = realtime

    def _run(self, callback: ChunkCallback) -> None:
        step = int(TARGET_SAMPLE_RATE * CHUNK_SECONDS)
        for i in range(0, len(self.audio), step):
            if self._stop.is_set():
                break
            callback(self.audio[i : i + step])
            if self.realtime:
                time.sleep(CHUNK_SECONDS)
