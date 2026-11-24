"""AI provider interface. Providers only ever receive *text* (transcript + notes)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod


class AIError(RuntimeError):
    pass


class AIProvider(ABC):
    name: str = ""
    label: str = ""

    @abstractmethod
    def availability(self) -> tuple[bool, str]: ...

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> str: ...

    @property
    def model(self) -> str:
        return ""

    def info(self) -> dict:
        ok, reason = self.availability()
        return {"name": self.name, "label": self.label, "available": ok, "reason": reason, "model": self.model}


def run_cli(cmd: list[str], stdin_text: str, timeout: int, check: bool = True) -> str:
    """Run an AI CLI with the prompt on stdin, from an empty temp dir.

    The empty working directory keeps the CLI from picking up this repo's
    CLAUDE.md / GEMINI.md or touching project files.
    """
    exe = shutil.which(cmd[0])
    if not exe:
        raise AIError(f"'{cmd[0]}' not found on PATH")
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")
    with tempfile.TemporaryDirectory(prefix="meeting-notes-ai-") as cwd:
        try:
            proc = subprocess.run(
                [exe, *cmd[1:]], input=stdin_text, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AIError(f"{cmd[0]} timed out after {timeout}s") from exc
    if proc.returncode != 0 and (check or not proc.stdout.strip()):
        detail = (proc.stderr or proc.stdout or "").strip()[-1500:]
        raise AIError(f"{cmd[0]} exited with {proc.returncode}: {detail}")
    return proc.stdout
