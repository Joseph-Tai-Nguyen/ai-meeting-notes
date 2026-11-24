from __future__ import annotations

import numpy as np
import pytest

from meeting_notes.ai.base import AIError, AIProvider
from meeting_notes.context import AppContext
from meeting_notes.storage.store import MeetingStore

SR = 16_000


def bursts(n: int = 3, speech_s: float = 1.0, silence_s: float = 1.0, amp: float = 0.2) -> np.ndarray:
    """Synthetic 'speech': tone bursts separated by near-silence."""
    rng = np.random.default_rng(0)
    parts = [np.zeros(int(SR * 0.5), np.float32)]
    t = np.arange(int(SR * speech_s)) / SR
    tone = (amp * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    for _ in range(n):
        parts.append(tone)
        parts.append((rng.standard_normal(int(SR * silence_s)) * 0.0005).astype(np.float32))
    return np.concatenate(parts)


class FakeProvider(AIProvider):
    def __init__(self, name="fake", reply="## Overview\nFake summary.", fail=False, available=True):
        self.name = name
        self.label = name
        self.reply = reply
        self.fail = fail
        self.available = available
        self.prompts: list[str] = []

    def availability(self):
        return self.available, "test"

    def generate(self, prompt, system=None):
        self.prompts.append(prompt)
        if self.fail:
            raise AIError("boom")
        return self.reply


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def store(data_dir):
    return MeetingStore(data_dir)


@pytest.fixture
def ctx(data_dir):
    return AppContext(data_dir)
