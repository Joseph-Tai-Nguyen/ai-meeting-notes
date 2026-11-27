# Project context

## What this is

**AI Meeting Notes** is a desktop app for Windows and macOS that transcribes meetings live
and turns them into notes. It is modelled on Notion AI Meeting Notes, with one
deliberate difference: **the core job (live transcription and note taking) works with no
AI service and no internet**. AI analysis is a separate, optional step on the saved transcript.

## Who it is for

People who sit in many Teams, Zoom or Meet calls plus in-person meetings and want:

- a reliable live transcript they own, stored as plain text files;
- their own notes side by side with the transcript;
- summaries, action items and follow-ups when they want them, using the AI plan they
  already pay for (Google AI Pro/Ultra through Gemini, or Claude through Claude Code).

## Key decisions (see docs/adr/)

| Decision | Choice | Why |
|---|---|---|
| Runtime | Python 3.10+ backend + local web UI (FastAPI, vanilla JS), optional native window (pywebview) | The best offline speech libraries are in Python. A web UI is cross-platform and needs no build step, which makes it easy for coding agents to change |
| Speech-to-text | Pluggable offline engines: Vosk (default, streaming), faster-whisper (accuracy), OS engines (Windows SAPI, Apple Speech), mock | "Without AI models / internet" requirement. Users can trade CPU for accuracy |
| Online meeting capture | Microphone + output loopback as **two separate streams** | Works with any meeting app and with speakers or headphones. The source gives "Me" vs "Others" speaker labels with no ML diarization |
| macOS system audio | Virtual loopback device (BlackHole) chosen as an input | No Python-accessible loopback API. ScreenCaptureKit capture is on the roadmap |
| Storage | One folder per meeting with JSON, JSONL and Markdown. No database. Audio never stored | Text format, easy backup, readable without the app, privacy |
| AI | `AIRouter` with Gemini API → Antigravity CLI (`agy`) → Claude Code fallback order | Use the user's Google AI plan first and fall back to Claude Code |
| Security | Server bound to 127.0.0.1, Host-header check, custom header on writes, secrets in env only | Transcripts are sensitive and the server must not be reachable from other sites |

## How it fits together

```text
mic ─┐                               ┌─> transcript.jsonl (append, live)
     ├─ AudioSource ─> Recognizer ─> LiveSession ─┤
loop ┘   (thread)     (per source)     (events)   └─> WebSocket ─> web UI (partials, segments, levels)

saved text ─> Analyzer ─> PromptLibrary + AIRouter ─> gemini_api | agy | claude_code ─> analysis/*.md
```

## Status

Version 0.1.0 is a working MVP. Recording, live transcript, notes, highlights, editing, search, export,
backup and restore, calendar ICS, and AI analysis with fallback are implemented and tested.
See requirements.md for the per-feature status and roadmap.

## Glossary

- **Segment**: one finalized utterance (`seq`, `start`, `end`, `speaker`, `text`, `source`).
- **Partial**: live, not-yet-final text shown in italics and never stored.
- **Source / lane**: one audio input (mic, system, file) with its own recognizer thread.
- **Mode**: `online` (mic + system), `in_person` (mic), `system` (loopback only), `file`.
- **Analysis kind**: `summary`, `action_items`, `decisions`, `follow_up_email`, `speakers`, `draft_doc`, `qa`.
