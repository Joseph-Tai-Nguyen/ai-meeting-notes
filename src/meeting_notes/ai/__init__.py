"""Optional AI analysis. Nothing here runs during live transcription."""

from meeting_notes.ai.analysis import TASKS, Analyzer
from meeting_notes.ai.base import AIError, AIProvider
from meeting_notes.ai.prompts import PromptLibrary
from meeting_notes.ai.router import AIRouter, build_providers

__all__ = ["TASKS", "AIError", "AIProvider", "AIRouter", "Analyzer", "PromptLibrary", "build_providers"]
