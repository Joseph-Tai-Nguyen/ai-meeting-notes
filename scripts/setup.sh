#!/usr/bin/env bash
# One-time developer setup on macOS / Linux.
#   bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
EXTRAS="audio,vosk,calendar,dev"
if [ "$(uname)" = "Darwin" ]; then EXTRAS="$EXTRAS,macos"; fi
.venv/bin/python -m pip install -e ".[$EXTRAS]"

[ -f .env ] || cp .env.example .env

.venv/bin/python scripts/download_models.py vosk en
.venv/bin/python -m meeting_notes doctor
echo
echo "Setup done. Start the app with:  .venv/bin/meeting-notes"
if [ "$(uname)" = "Darwin" ]; then
  echo "macOS: to capture Teams/Zoom audio install BlackHole (brew install blackhole-2ch) - see docs/audio-capture.md"
fi
