# GEMINI.md

Instructions for Gemini CLI and Google Antigravity agents in this repository.

@./AGENTS.md

## Gemini / Antigravity notes

- Read `project_context.md` and `requirements.md` before planning work.
- Antigravity workspace rules and workflows are in `.agent/rules/` and `.agent/workflows/`
  (`/check` runs lint and tests, `/run-app` starts the dev server).
- Run the app for browser checks: `python -m meeting_notes --data-dir ./data serve --no-browser`,
  then open http://127.0.0.1:8765. Use the "Test engine (no recognition)" engine when no speech
  model is installed.
- This app *calls* Gemini as its primary AI provider, in two ways:
  - `src/meeting_notes/ai/gemini_api.py`: REST `generateContent` with `GEMINI_API_KEY` (stdlib only).
  - `src/meeting_notes/ai/antigravity_cli.py`: `agy --input-format stream-json --output-format stream-json`
    with the prompt on stdin, using the user's Google AI plan sign-in.
  Keep the default model configurable (`AISettings.gemini_model`) and do not hard-code model names elsewhere.
- Do not write API keys into any file. `.env` is gitignored, and `.env.example` documents the variables.
