"""Gemini via the Gemini CLI - uses your Google account / Google AI Pro or Ultra plan.

Install: npm install -g @google/gemini-cli   then run `gemini` once and sign in
with Google. No API key needed; usage counts against your Google AI plan.
"""

from __future__ import annotations

import shutil

from meeting_notes.ai.base import AIError, AIProvider, run_cli

_INSTRUCTION = "Follow the instructions in the input exactly and reply with the requested Markdown only. Do not use tools."


class GeminiCLIProvider(AIProvider):
    name = "gemini_cli"
    label = "Gemini CLI (Google AI plan sign-in)"

    def __init__(self, model: str = "", timeout: int = 600, executable: str = "gemini"):
        self._model = model
        self.timeout = timeout
        self.executable = executable

    @property
    def model(self) -> str:
        return self._model or "default"

    def availability(self) -> tuple[bool, str]:
        if not shutil.which(self.executable):
            return False, "npm install -g @google/gemini-cli, then run `gemini` once to sign in"
        return True, f"model: {self.model}"

    def generate(self, prompt: str, system: str | None = None) -> str:
        cmd = [self.executable, "-p", _INSTRUCTION]
        if self._model:
            cmd += ["-m", self._model]
        full = f"{system}\n\n{prompt}" if system else prompt
        out = run_cli(cmd, full, self.timeout).strip()
        if not out:
            raise AIError("Gemini CLI returned an empty answer")
        return out
