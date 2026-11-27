# AGENTS.md — rules for AI coding agents

This is the single source of truth for any coding agent working in this repo
(Claude Code, Gemini CLI, Google Antigravity, Codex, Cursor…). `CLAUDE.md` and
`GEMINI.md` import this file and add only tool-specific notes.

Read [project_context.md](project_context.md) first, then [requirements.md](requirements.md)
for the feature list and status, and [docs/architecture.md](docs/architecture.md) for the module map.

## Product invariants (do not break)

1. **Live transcription never needs the network or an AI service.** Nothing under
   `src/meeting_notes/transcription/` or `audio/` may import or call
   `meeting_notes.ai`, open sockets, or download at runtime. Model downloads go only
   through `scripts/download_models.py`, or the engine's own first-run cache when the user picks that engine.
2. **Audio is never written to disk.** Only text is stored.
3. **Storage is plain text** (JSON, JSONL, Markdown) under the data folder, one folder per meeting.
   Keep the formats backward compatible. Add fields with defaults and never rename them.
   `transcript.jsonl` is append-only while recording.
4. **AI runs only when the user asks** (Generate / Ask buttons, `analyze` / `ask` CLI). It receives text only.
5. **Gemini first, Claude Code as fallback**, through `AIRouter` and the user's provider order. New
   providers implement `AIProvider` (`ai/base.py`) and are registered in `ai/router.py`.
6. **Local-only server.** Keep the Host-header check and the `x-meeting-notes: 1` header that
   every non-GET request needs (`server/api.py`). The front-end `api()` helper sends it.
   Never bind to `0.0.0.0` by default.
7. **No secrets in files.** API keys come only from environment variables or `.env` (gitignored).
8. **Cross-platform.** Windows and macOS are first-class, Linux best-effort. Guard OS-specific
   code with `sys.platform` and import optional dependencies lazily inside functions,
   so the app starts with the core install only.

## Layout

```text
src/meeting_notes/
  cli.py              argparse entry point (meeting-notes)
  config.py           Settings dataclasses + settings.json + .env loader
  context.py          AppContext: store, engines, AI router, the single LiveSession
  models.py           Meeting / Segment / Highlight dataclasses
  calendar_ics.py     read-only ICS calendar feeds
  audio/              capture sources (soundcard mic + loopback, wav file, array) and device listing
  transcription/      Engine/Recognizer ABCs, vosk, whisper, macos, windows_sapi, mock, segmenter, LiveSession
  storage/            MeetingStore (files), export/backup/restore, offline search & retrieval
  ai/                 providers (gemini_api, agy, claude_code), router, prompts, Analyzer
  prompts/            built-in prompt templates (Markdown); users override in <data>/prompts
  server/api.py       FastAPI REST + WebSocket
  web/                index.html, app.js, styles.css (vanilla JS, no build step)
scripts/              setup.ps1, setup.sh, download_models.py
tests/                pytest suite (no audio hardware, network or AI needed)
docs/                 architecture, API, audio capture, packaging, ADRs
```

## Commands

```bash
pip install -e ".[audio,vosk,dev]"     # dev install (Windows venv: .venv\Scripts\python -m ...)
pytest                                 # must pass before you finish
ruff check src tests scripts           # must be clean
meeting-notes doctor                   # environment check
meeting-notes --data-dir ./data serve --no-browser   # run the app at http://127.0.0.1:8765
```

## Conventions

- Python ≥ 3.10 with `from __future__ import annotations`, type hints, and dataclasses for data.
  Line length is 130 (ruff).
- Keep core dependencies to `fastapi`, `uvicorn` and `numpy`. Everything else is an optional extra in
  `pyproject.toml` and is imported lazily, with a clear install hint when it is missing
  (`Engine.availability()` / `AIProvider.availability()` return `(ok, reason)`).
- Errors shown to users should say what to do (for example "pip install -e .[whisper]").
- Validate every path segment that comes from a request (`store._check_id`, `_check_kind`).
- Background threads must never raise into the UI. Report failures as `{"type": "error"}` session events.
- Front-end: vanilla JS in `web/app.js`. Escape all dynamic text with `esc()`, and render Markdown only with `md()`.
- Prompts live in `src/meeting_notes/prompts/*.md` with `{{placeholders}}`. Change prompt wording there, not in Python.
- Tests: add or adjust tests in `tests/` for each behaviour change. Use `MockEngine`, `ArraySource`
  and `FakeProvider` (in `tests/conftest.py`) and never use real audio, network or AI services in tests.

## Definition of done

- `pytest` passes and `ruff check` is clean.
- `requirements.md` status table is updated if a feature changed state.
- User-facing behaviour changes are reflected in `README.md`, and API changes in `docs/api.md`.
- No `.env`, `data/`, `models/` or audio files are committed.

## Things to avoid

- Do not add a JS build toolchain or framework without an ADR in `docs/adr/`.
- Do not add a database. Text files are a product requirement.
- Do not send transcripts anywhere automatically (Slack, email, webhooks) without an explicit,
  opt-in user setting and a confirmation step.
- Do not commit, push or open PRs unless the human asks.
