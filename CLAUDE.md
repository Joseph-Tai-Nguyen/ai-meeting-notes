# CLAUDE.md

@AGENTS.md

## Claude Code notes

- Context: @project_context.md. Feature list and status: @requirements.md.
- Windows dev shell: use the venv interpreter directly, for example `.venv/Scripts/python.exe -m pytest`
  (bash) or `.\.venv\Scripts\python -m pytest` (PowerShell).
- Run the app for manual checks with the `meeting-notes` launch configuration in
  `.claude/launch.json` (serves http://localhost:8777 with `./data`, so it does not clash with a running copy on 8765).
- Use `/check` (`.claude/commands/check.md`) to run lint and tests before finishing.
- This app *calls* Claude Code as an AI provider (`src/meeting_notes/ai/claude_code.py`,
  `claude -p --output-format json`, prompt on stdin, run from an empty temp directory).
  If you change that call, keep the prompt on stdin: multi-line arguments break through `.cmd` shims on Windows.
- Large or risky changes (new engine, storage format change, new provider): write a short plan
  first and an ADR in `docs/adr/` when it changes an invariant in AGENTS.md.
