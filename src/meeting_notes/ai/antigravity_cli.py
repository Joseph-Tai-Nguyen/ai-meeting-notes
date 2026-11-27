"""Gemini via the Antigravity CLI (`agy`) - uses your Google account / Google AI Pro or Ultra plan.

Install: https://antigravity.google (Windows PowerShell:
`irm https://antigravity.google/cli/install.ps1 | iex`), then run `agy` once
to sign in with Google. No API key needed; usage counts against your Google AI plan.
"""

from __future__ import annotations

import json
import shutil

from meeting_notes.ai.base import AIError, AIProvider, run_cli

_INSTRUCTION = "Follow the instructions below exactly and reply with the requested Markdown only. Do not use tools."
_AUTH_KEYWORDS = ("auth", "login", "sign in", "credential", "unauthenticated")


def _auth_hint(msg: str) -> str:
    return " - run `agy` in a terminal and sign in with your Google account." if any(k in msg.lower() for k in _AUTH_KEYWORDS) else ""


class AntigravityCLIProvider(AIProvider):
    name = "agy"
    label = "Antigravity CLI (Google AI plan sign-in)"

    def __init__(self, model: str = "", timeout: int = 600, executable: str = "agy"):
        self._model = model
        self.timeout = timeout
        self.executable = executable

    @property
    def model(self) -> str:
        return self._model or "default"

    def availability(self) -> tuple[bool, str]:
        if not shutil.which(self.executable):
            return False, "install Antigravity CLI (https://antigravity.google), then run `agy` once to sign in"
        return True, f"model: {self.model}"

    def generate(self, prompt: str, system: str | None = None) -> str:
        # Use stream-json on stdin so arbitrarily large transcripts bypass OS command-line length limits.
        cmd = [
            self.executable,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--disable-slash-commands",
        ]
        if self._model:
            cmd += ["--model", self._model]
        parts = [_INSTRUCTION]
        if system:
            parts.append(system)
        parts.append(prompt)
        payload = json.dumps({"event": "user", "message": {"content": "\n\n".join(parts)}}) + "\n"
        try:
            # check=False: on failure agy still emits a result event on stdout with the error reason.
            raw = run_cli(cmd, payload, self.timeout, check=False)
        except AIError as exc:
            msg = str(exc)
            raise AIError(f"{msg}{_auth_hint(msg)}") from exc

        result: dict | None = None
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("event") == "result" and isinstance(ev.get("result"), dict):
                result = ev["result"]

        if result is None:
            raise AIError(f"Antigravity CLI returned unexpected output: {raw.strip()[:500]}")
        if result.get("status") != "SUCCESS" or result.get("error"):
            reason = str(result.get("error") or result.get("status") or "unknown error")
            raise AIError(f"Antigravity CLI error: {reason}{_auth_hint(reason)}")
        text = str(result.get("response") or "").strip()
        if not text:
            raise AIError("Antigravity CLI returned an empty answer")
        return text
