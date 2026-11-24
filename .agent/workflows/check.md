---
description: Lint and test the project
---

1. Run `python -m ruff check src tests scripts` (on Windows use `.venv\Scripts\python`). Fix any findings.
2. Run `python -m pytest`. All tests must pass.
3. If a feature changed status, update the table in requirements.md.
