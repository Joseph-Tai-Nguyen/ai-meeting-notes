---
description: Lint and test the project, then summarize failures
---

Run, from the repo root, using the project virtualenv (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS):

1. `python -m ruff check src tests scripts`
2. `python -m pytest`

Fix any lint findings and failing tests caused by the current change. Report what you ran and the final result.
If a feature changed state, update the status table in requirements.md.
