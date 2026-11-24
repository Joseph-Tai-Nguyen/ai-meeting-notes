"""Energy-based voice activity segmentation (no ML, no dependencies beyond numpy).

Used by engines that work on whole utterances (faster-whisper, Windows SAPI,
the mock engine): audio is cut at pauses so each utterance can be recognized
as soon as the speaker stops.
"""

from __future__ import annotations

from collections import deque

import numpy as np


class UtteranceSegmenter:
    def __init__(
        self,
        sample_rate: int = 16_000,
        frame_ms: int = 30,
        min_silence_s: float = 0.6,
        max_utterance_s: float = 15.0,
        min_speech_s: float = 0.25,
        energy_floor: float = 0.004,
        preroll_s: float = 0.2,
    ):
        self.sr = sample_rate
        self.frame = int(sample_rate * frame_ms / 1000)
        self.min_silence_frames = max(1, int(min_silence_s * 1000 / frame_ms))
        self.max_frames = int(max_utterance_s * 1000 / frame_ms)
        self.min_speech_frames = max(1, int(min_speech_s * 1000 / frame_ms))
        self.energy_floor = energy_floor
        self._noise = energy_floor
        self._buf = np.zeros(0, dtype=np.float32)
        self._pos = 0  # samples consumed into frames
        self._preroll: deque[np.ndarray] = deque(maxlen=max(1, int(preroll_s * 1000 / frame_ms)))
        self._utt: list[np.ndarray] = []
        self._utt_start: int | None = None
        self._speech = 0
        self._silence = 0
        self.last_rms = 0.0

    @property
    def in_speech(self) -> bool:
        return self._utt_start is not None

    @property
    def position_s(self) -> float:
        return self._pos / self.sr

    def pending(self) -> tuple[float, np.ndarray] | None:
        if self._utt_start is None or not self._utt:
            return None
        return self._utt_start / self.sr, np.concatenate(self._utt)

    def feed(self, pcm: np.ndarray) -> list[tuple[float, np.ndarray]]:
        """Return completed utterances as (start_seconds, audio)."""
        out: list[tuple[float, np.ndarray]] = []
        if pcm.size:
            self._buf = np.concatenate([self._buf, pcm.astype(np.float32, copy=False)])
        n = len(self._buf) // self.frame
        f = self.frame
        for i in range(n):
            fr = self._buf[i * f : (i + 1) * f]
            rms = float(np.sqrt(np.mean(fr * fr))) if fr.size else 0.0
            self.last_rms = rms
            start = self._pos
            self._pos += f
            threshold = max(self.energy_floor, self._noise * 3.0)
            speech = rms > threshold
            if not speech and self._utt_start is None:
                self._noise = min(0.05, 0.95 * self._noise + 0.05 * max(rms, self.energy_floor / 2))
            if self._utt_start is None:
                if speech:
                    pre = list(self._preroll)
                    self._utt = pre + [fr.copy()]
                    self._utt_start = start - len(pre) * f
                    self._speech, self._silence = 1, 0
                else:
                    self._preroll.append(fr.copy())
                continue
            self._utt.append(fr.copy())
            if speech:
                self._speech += 1
                self._silence = 0
            else:
                self._silence += 1
            if self._silence >= self.min_silence_frames or len(self._utt) >= self.max_frames:
                out.extend(self._close())
        self._buf = self._buf[n * f :]
        return out

    def flush(self) -> list[tuple[float, np.ndarray]]:
        return self._close() if self._utt_start is not None else []

    def _close(self) -> list[tuple[float, np.ndarray]]:
        result: list[tuple[float, np.ndarray]] = []
        if self._utt_start is not None and self._speech >= self.min_speech_frames:
            audio = np.concatenate(self._utt)
            # trim trailing silence (keep ~150 ms)
            keep_tail = max(0, self._silence - 5) * self.frame
            if keep_tail and keep_tail < len(audio):
                audio = audio[:-keep_tail]
            result.append((max(0, self._utt_start) / self.sr, audio))
        self._utt = []
        self._utt_start = None
        self._speech = self._silence = 0
        self._preroll.clear()
        return result
