import importlib.util
import subprocess
import sys

import numpy as np
import pytest

from conftest import SR, bursts
from meeting_notes.audio.capture import ArraySource, to_mono_16k
from meeting_notes.transcription.mock_engine import MockEngine
from meeting_notes.transcription.segmenter import UtteranceSegmenter
from meeting_notes.transcription.session import LiveSession


def test_resample_and_downmix():
    stereo = np.ones((48_000, 2), np.float32) * 0.5
    out = to_mono_16k(stereo, 48_000)
    assert out.shape == (16_000,) and np.allclose(out, 0.5)
    out44 = to_mono_16k(np.zeros(44_100, np.float32), 44_100)
    assert abs(len(out44) - 16_000) <= 1


def test_segmenter_finds_utterances():
    seg = UtteranceSegmenter()
    audio = bursts(3)
    found = []
    for i in range(0, len(audio), 1600):
        found += seg.feed(audio[i : i + 1600])
    found += seg.flush()
    assert len(found) == 3
    starts = [round(s, 1) for s, _ in found]
    assert starts[0] < 0.6 and all(b > a for a, b in zip(starts, starts[1:], strict=False))
    assert all(0.8 < len(a) / SR < 1.6 for _, a in found)


def test_silence_produces_nothing():
    seg = UtteranceSegmenter()
    assert seg.feed(np.zeros(SR * 3, np.float32)) == [] and seg.flush() == []


def test_live_session_two_sources(store):
    m = store.create("Call", "online")
    events = []
    sources = [ArraySource(bursts(2), "Me", "mic"), ArraySource(bursts(3), "Others", "system")]
    s = LiveSession(store, m.id, MockEngine(), "en", sources, events.append)
    s.start()
    assert s.wait(10)
    segs = store.segments(m.id)
    assert sorted(x.speaker for x in segs) == ["Me", "Me", "Others", "Others", "Others"]
    assert len({x.seq for x in segs}) == 5
    meeting = store.get(m.id)
    assert meeting.status == "done" and meeting.duration > 3
    assert any(e["type"] == "segment" for e in events) and events[-1] == {"type": "status", "status": "done", "elapsed": events[-1]["elapsed"]}
    assert (store.path(m.id) / "transcript.md").is_file()


def test_continue_recording_appends_after_previous(store):
    m = store.create("Two parts", "in_person")
    for _ in range(2):
        s = LiveSession(store, m.id, MockEngine(), "en", [ArraySource(bursts(1), "Speaker")])
        s.start()
        assert s.wait(10)
    segs = store.segments(m.id)
    assert [x.seq for x in segs] == [1, 2]
    assert segs[1].start > segs[0].end


def test_pause_drops_audio(store):
    m = store.create("Paused", "in_person")
    s = LiveSession(store, m.id, MockEngine(), "en", [ArraySource(bursts(5), "Speaker", realtime=True)])
    s.start()
    s.pause()
    s.stop()
    assert len(store.segments(m.id)) <= 1


@pytest.mark.skipif(sys.platform != "win32" or importlib.util.find_spec("soundcard") is None, reason="Windows + soundcard only")
def test_soundcard_loads_when_com_already_initialised():
    """Regression: 'Error 0x100000001' when e.g. the Windows Speech engine initialised COM first."""
    code = (
        "import ctypes, threading\n"
        "from meeting_notes.audio.capture import load_soundcard\n"
        "out = {}\n"
        "def job():\n"
        "    ctypes.windll.ole32.CoInitializeEx(None, 0)\n"
        "    try:\n"
        "        load_soundcard(); out['ok'] = True\n"
        "    except Exception as e:\n"
        "        out['err'] = repr(e)\n"
        "t = threading.Thread(target=job); t.start(); t.join()\n"
        "print(out)\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert "'ok': True" in res.stdout, res.stdout + res.stderr
