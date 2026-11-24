---
trigger: always_on
---

Follow AGENTS.md at the repository root. Key points:

- Live transcription (src/meeting_notes/audio, src/meeting_notes/transcription) must work offline
  and must never call AI services or the network.
- Never store audio. Store text only (JSON, JSONL, Markdown) through MeetingStore.
- AI (src/meeting_notes/ai) runs only on user action. Gemini is first, Claude Code is the fallback, through AIRouter.
- Import optional dependencies lazily and report a clear install hint when they are missing.
- Keep the local-only server protections (Host check, x-meeting-notes header).
- Run `pytest` and `ruff check src tests scripts` before you finish.
