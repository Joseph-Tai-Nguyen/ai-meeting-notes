# Architecture

## Processes and threads

One Python process:

- **uvicorn / FastAPI** (asyncio loop) serves the UI, REST API and WebSockets.
- **LiveSession** (at most one at a time) starts, for each audio source:
  - a **capture thread** (`AudioSource._run`): reads the device in 100 ms blocks, converts
    to mono 16 kHz float32 and puts the chunks on a queue;
  - a **recognizer thread** (`LiveSession._process`): feeds the chunks to that source's
    `Recognizer`, turns its events into partials and segments, appends segments to
    `transcript.jsonl`, and emits events.
- Session events reach WebSocket clients through `AppContext.listeners`, using
  `asyncio.run_coroutine_threadsafe`.
- AI calls run in FastAPI's thread pool (sync endpoints) and can take minutes.

## Timeline

Each lane counts the samples it has fed (`lane.samples`). Paused audio is dropped and never
counted, so pauses are cut out of the timeline. `base_offset` is the meeting's saved
duration, which lets a second recording continue the same timeline. Segment times come
from the recognizer (Whisper, SAPI and mock report utterance start and end) or are
estimated from when the first partial appeared (Vosk).

## Engines

```python
class Engine:            # one per kind, cheap to construct
    availability() -> (ok, reason)
    create(language) -> Recognizer      # one per audio source
class Recognizer:
    accept(pcm) -> [RecognitionEvent(text, final, start?, end?)]
    flush()  -> [...]                    # on pause / stop
```

Utterance-based engines share `UtteranceSegmenter` (energy VAD with an adaptive noise
floor, 0.6 s silence to close an utterance, 15–20 s maximum). Adding an engine means
subclassing `Engine` and `Recognizer`, registering it in `transcription/__init__.py:build_engines`,
and adding an optional extra in `pyproject.toml`.

## Storage

`MeetingStore` owns every file access, holds an RLock, and uses atomic writes (write a
`.tmp` file, then `replace`). See the README for the folder layout. Every id and analysis
kind is checked against a strict regex before it is used in a path.

## AI

`Analyzer` builds prompts from `prompts/*.md` (user overrides in `<data>/prompts`), with
`{{context}}` = meeting header + notes + highlights + transcript. If the transcript is
longer than `max_chunk_chars`, each chunk is condensed first (`tasks/chunk_summary.md`).
`AIRouter` tries providers in the configured order and skips any that are unavailable or
fail. CLI providers run in an empty temporary directory with the prompt on stdin.

## Security model

- The server binds to 127.0.0.1. A middleware rejects foreign `Host` headers (DNS rebinding)
  and any non-GET request without `x-meeting-notes: 1`. A custom header forces a CORS
  preflight, which the server never approves, so other websites cannot post to it.
- WebSocket connections with a foreign `Origin` are refused.
- Restoring a backup ignores absolute paths, `..` and anything outside `meetings/` or `prompts/`.
- Secrets are read only from the environment or `.env`.
