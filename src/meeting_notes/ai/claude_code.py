"""Claude via Claude Code in headless mode (`claude -p`) - the fallback provider.

Uses whatever account Claude Code is signed in with (Pro / Max plan or API
key). Install: https://docs.claude.com/en/docs/claude-code
"""

from __future__ import annotations

import json
import shutil

from meeting_notes.ai.base import AIError, AIProvider, run_cli


class ClaudeCodeProvider(AIProvider):
    name = "claude_code"
    label = "Claude Code (headless)"

    def __init__(self, model: str = "", timeout: int = 600, executable: str = "claude"):
        self._model = model
        self.timeout = timeout
        self.executable = executable

    @property
    def model(self) -> str:
        return self._model or "default"

    def availability(self) -> tuple[bool, str]:
        if not shutil.which(self.executable):
            return False, "install Claude Code and sign in (`claude`)"
        return True, f"model: {self.model}"

    def generate(self, prompt: str, system: str | None = None) -> str:
        cmd = [self.executable, "-p", "--output-format", "json"]
        if self._model:
            cmd += ["--model", self._model]
        # System text goes on stdin too: multi-line arguments are unsafe through .cmd shims on Windows.
        full = f"{system}\n\n{prompt}" if system else prompt
        # check=False: on failure Claude Code still prints a JSON result with the reason.
        raw = run_cli(cmd, full, self.timeout, check=False)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise AIError(f"Claude Code returned unexpected output: {raw.strip()[:500]}") from None
        if data.get("is_error"):
            reason = data.get("result") or data.get("subtype")
            hint = " - run `claude` in a terminal and sign in again (/login)." if "auth" in str(reason).lower() else ""
            raise AIError(f"Claude Code error: {reason}{hint}")
        text = str(data.get("result") or "").strip()
        if not text:
            raise AIError(f"Claude Code returned an empty result ({data.get('subtype')})")
        return text
