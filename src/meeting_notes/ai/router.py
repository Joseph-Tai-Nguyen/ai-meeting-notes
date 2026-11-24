"""Provider selection with fallback: Gemini first (Google AI plan), Claude Code as fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from meeting_notes.ai.base import AIError, AIProvider
from meeting_notes.ai.claude_code import ClaudeCodeProvider
from meeting_notes.ai.gemini_api import GeminiAPIProvider
from meeting_notes.ai.gemini_cli import GeminiCLIProvider
from meeting_notes.config import AISettings

log = logging.getLogger(__name__)


@dataclass
class AIResult:
    text: str
    provider: str
    model: str


def build_providers(ai: AISettings) -> dict[str, AIProvider]:
    providers: list[AIProvider] = [
        GeminiAPIProvider(ai.gemini_model, ai.timeout_seconds),
        GeminiCLIProvider(ai.gemini_cli_model, ai.timeout_seconds),
        ClaudeCodeProvider(ai.claude_model, ai.timeout_seconds),
    ]
    return {p.name: p for p in providers}


class AIRouter:
    def __init__(self, providers: dict[str, AIProvider], order: list[str]):
        self.providers = providers
        self.order = [n for n in order if n in providers] + [n for n in providers if n not in order]

    def status(self) -> list[dict]:
        return [self.providers[n].info() for n in self.order]

    def generate(self, prompt: str, system: str | None = None, provider: str | None = None) -> AIResult:
        """Use ``provider`` if given, else the first available in order; fall back on errors."""
        names = [provider] if provider and provider != "auto" else self.order
        errors: list[str] = []
        for name in names:
            p = self.providers.get(name)
            if p is None:
                errors.append(f"{name}: unknown provider")
                continue
            ok, reason = p.availability()
            if not ok:
                errors.append(f"{name}: {reason}")
                continue
            try:
                return AIResult(p.generate(prompt, system), p.name, p.model)
            except AIError as exc:
                log.warning("provider %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
        raise AIError("No AI provider succeeded. " + " | ".join(errors))
