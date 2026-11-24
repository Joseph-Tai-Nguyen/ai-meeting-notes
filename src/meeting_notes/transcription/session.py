"""LiveSession - wires audio sources -> recognizers -> transcript storage -> UI events.

Each audio source (microphone, system loopback, file) gets its own recognizer
and thread, so in an online meeting your voice ("Me") and the remote voices
("Others") are transcribed separately and labelled automatically - a simple,
reliable speaker split that needs no AI diarization.

Events delivered to ``on_event`` (all JSON-serialisable dicts):
    {"type": "status",  "status": "recording"|"paused"|"done", "elapsed": float}
    {"type": "partial", "source": str, "speaker": str, "text": str}
    {"type": "segment", "segment": {...Segment...}}
    {"type": "level",   "source": str, "rms": float}
    {"type": "error",   "source": str, "message": str}
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from meeting_notes.audio.capture import TARGET_SAMPLE_RATE, AudioSource
from meeting_notes.models import Highlight, Segment
from meeting_notes.storage.store import MeetingStore
from meeting_notes.transcription.base import Engine, Recognizer

log = logging.getLogger(__name__)
EventCallback = Callable[[dict], None]
_STOP = object()
_PAUSE = object()


@dataclass
class _Lane:
    source: AudioSource
    recognizer: Recognizer
    q: queue.Queue = field(default_factory=queue.Queue)
    samples: int = 0
    utt_start: float | None = None
    last_level: float = 0.0
    thread: threading.Thread | None = None
    started: bool = False


class LiveSession:
    def __init__(
        self,
        store: MeetingStore,
        meeting_id: str,
        engine: Engine,
        language: str,
        sources: list[AudioSource],
        on_event: EventCallback | None = None,
    ):
        self.store = store
        self.meeting_id = meeting_id
        self.engine = engine
        self.language = language
        self.sources = sources
        self.on_event = on_event or (lambda e: None)
        meeting = store.get(meeting_id)
        self.base_offset = meeting.duration
        existing = store.segments(meeting_id)
        self._seq = max((s.seq for s in existing), default=0)
        self._seq_lock = threading.Lock()
        self._lanes: list[_Lane] = []
        self._paused = threading.Event()
        self._finished = threading.Event()
        self._ended_sources = 0
        self._stop_lock = threading.Lock()
        self._stopping = False
        self._started_all = False
        self.status = "idle"
        self._last_status_emit = 0.0

    # ----------------------------------------------------------------- public
    @property
    def elapsed(self) -> float:
        active = max((lane.samples for lane in self._lanes), default=0) / TARGET_SAMPLE_RATE
        return self.base_offset + active

    def start(self) -> None:
        errors = []
        for src in self.sources:
            try:
                rec = self.engine.create(self.language)
                lane = _Lane(source=src, recognizer=rec)
                src.on_end = lambda lane=lane: self._source_ended(lane)
                src.start(lambda pcm, lane=lane: self._on_audio(lane, pcm))
                lane.started = True
                lane.thread = threading.Thread(target=self._process, args=(lane,), daemon=True, name=f"stt-{src.source_id}")
                lane.thread.start()
                self._lanes.append(lane)
            except Exception as exc:  # noqa: BLE001 - surface any device/engine failure to the UI
                log.warning("source %s failed: %s", src.source_id, exc)
                errors.append(f"{src.label}: {exc}")
                self._emit({"type": "error", "source": src.source_id, "message": str(exc)})
        if not self._lanes:
            raise RuntimeError("Could not start any audio source. " + " | ".join(errors))
        self.status = "recording"
        self.store.update(self.meeting_id, status="recording", engine=self.engine.name, language=self.language)
        self._emit_status(force=True)
        with self._stop_lock:
            self._started_all = True
            trigger = self._ended_sources >= len(self._lanes)
        if trigger:  # every source already finished (short file / test audio)
            threading.Thread(target=self.stop, daemon=True).start()

    def pause(self) -> None:
        if self.status != "recording":
            return
        self._paused.set()
        for lane in self._lanes:
            lane.q.put(_PAUSE)
        self.status = "paused"
        self.store.update(self.meeting_id, status="paused", duration=self.elapsed)
        self._emit_status(force=True)

    def resume(self) -> None:
        if self.status != "paused":
            return
        self._paused.clear()
        self.status = "recording"
        self.store.update(self.meeting_id, status="recording")
        self._emit_status(force=True)

    def highlight(self, label: str = "") -> Highlight:
        meeting = self.store.get(self.meeting_id)
        h = Highlight(t=round(self.elapsed, 2), label=label.strip())
        meeting.highlights.append(h)
        self.store.save(meeting)
        return h

    def stop(self) -> None:
        with self._stop_lock:
            already = self._stopping
            self._stopping = True
        if already:
            self._finished.wait(65)
            return
        for lane in self._lanes:
            lane.source.stop()
            lane.q.put(_STOP)
        for lane in self._lanes:
            if lane.thread:
                lane.thread.join(timeout=60)
            try:
                lane.recognizer.close()
            except Exception:  # noqa: BLE001
                pass
        self.status = "done"
        self.store.update(self.meeting_id, status="done", duration=round(self.elapsed, 2))
        self.store.write_transcript_md(self.meeting_id)
        self._finished.set()
        self._emit_status(force=True)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until all sources ended (file / array sources) or stop() was called."""
        return self._finished.wait(timeout)

    # ---------------------------------------------------------------- internal
    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 - never let a UI listener break capture
            log.exception("event listener failed")

    def _emit_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_status_emit > 1.0:
            self._last_status_emit = now
            self._emit({"type": "status", "status": self.status, "elapsed": round(self.elapsed, 1)})

    def _on_audio(self, lane: _Lane, pcm: np.ndarray) -> None:
        if self._paused.is_set() or pcm.size == 0:
            return
        lane.q.put(pcm)

    def _source_ended(self, lane: _Lane) -> None:
        lane.q.put(_STOP)
        with self._stop_lock:
            self._ended_sources += 1
            trigger = self._started_all and self._ended_sources >= len(self._lanes) and not self._stopping
        if trigger:
            threading.Thread(target=self.stop, daemon=True).start()

    def _stream_time(self, lane: _Lane) -> float:
        return lane.samples / TARGET_SAMPLE_RATE

    def _process(self, lane: _Lane) -> None:
        while True:
            item = lane.q.get()
            if item is _STOP:
                self._handle(lane, lane.recognizer.flush())
                return
            if item is _PAUSE:
                self._handle(lane, lane.recognizer.flush())
                continue
            pcm: np.ndarray = item
            try:
                events = lane.recognizer.accept(pcm)
            except Exception as exc:  # noqa: BLE001
                log.exception("recognizer failed")
                self._emit({"type": "error", "source": lane.source.source_id, "message": f"recognizer: {exc}"})
                events = []
            lane.samples += len(pcm)
            self._handle(lane, events)
            now = time.monotonic()
            if now - lane.last_level > 0.2:
                lane.last_level = now
                rms = float(np.sqrt(np.mean(pcm * pcm))) if pcm.size else 0.0
                self._emit({"type": "level", "source": lane.source.source_id, "rms": round(rms, 4)})
            self._emit_status()

    def _handle(self, lane: _Lane, events) -> None:
        now_t = self._stream_time(lane)
        for ev in events:
            if not ev.final:
                if ev.text and lane.utt_start is None:
                    lane.utt_start = ev.start if ev.start is not None else max(0.0, now_t - 1.0)
                self._emit({"type": "partial", "source": lane.source.source_id, "speaker": lane.source.label, "text": ev.text})
                continue
            text = ev.text.strip()
            start = ev.start if ev.start is not None else (lane.utt_start if lane.utt_start is not None else max(0.0, now_t - 2.0))
            end = ev.end if ev.end is not None else now_t
            lane.utt_start = None
            self._emit({"type": "partial", "source": lane.source.source_id, "speaker": lane.source.label, "text": ""})
            if not text:
                continue
            with self._seq_lock:
                self._seq += 1
                seg = Segment(
                    seq=self._seq,
                    start=round(self.base_offset + start, 2),
                    end=round(self.base_offset + max(end, start), 2),
                    speaker=lane.source.label,
                    text=text,
                    source=lane.source.source_id,
                )
                self.store.append_segment(self.meeting_id, seg)
            self._emit({"type": "segment", "segment": seg.to_dict()})


def sources_for_mode(mode: str, ts, file_path: str | None = None, realtime_file: bool = False) -> list[AudioSource]:
    """Audio sources for a meeting mode.

    online    - microphone ("Me") + system audio loopback ("Others"): Teams, Zoom, Meet...
                with speakers or headphones.
    in_person - microphone only (offline meeting in a room).
    system    - system audio only (webinar, recorded call playing on the computer).
    file      - an existing .wav recording.
    """
    from meeting_notes.audio.capture import SoundcardSource, WavFileSource

    if mode == "online":
        return [
            SoundcardSource("mic", ts.mic_device, ts.me_label, "mic"),
            SoundcardSource("loopback", ts.system_device, ts.others_label, "system"),
        ]
    if mode == "in_person":
        return [SoundcardSource("mic", ts.mic_device, ts.room_label, "mic")]
    if mode == "system":
        return [SoundcardSource("loopback", ts.system_device, ts.others_label, "system")]
    if mode == "file":
        if not file_path:
            raise ValueError("file mode needs a file path")
        return [WavFileSource(file_path, ts.room_label, realtime=realtime_file)]
    raise ValueError(f"unknown mode: {mode}")
