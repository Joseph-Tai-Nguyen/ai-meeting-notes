---
description: Start the app locally for manual or browser testing
---

1. Make sure the virtualenv exists (`scripts/setup.ps1` on Windows, `scripts/setup.sh` on macOS).
2. Run `python -m meeting_notes --data-dir ./data serve --no-browser` in the background.
3. Open http://127.0.0.1:8765 in the browser.
4. Use the engine "Test engine (no recognition)" if no speech model is installed. Create a meeting, Start, Stop.
5. Stop the server when done. `./data` is gitignored.
