"""
modules/voice/__init__.py
--------------------------
Pair D — Voice & Facts public API.

Import the right pipeline based on ``settings.use_mocks``:

    from modules.voice import get_pipeline
    pipeline = get_pipeline()
    tts_req  = await pipeline.run(recap_request)

Or import specific components directly::

    from modules.voice import (
        VoicePipeline,
        MockVoicePipeline,
        FreshnessChecker,
        RecapTextBuilder,
        RecapTextValidationError,
        RimeTtsClient,
    )
"""

from __future__ import annotations

from .freshness_checker import FreshnessChecker
from .mock_pipeline import MockVoicePipeline
from .pipeline import VoicePipeline
from .recap_text_builder import RecapTextBuilder, RecapTextValidationError, RimePromptValidator
from .rime_tts_client import RimeTtsClient

__all__ = [
    "VoicePipeline",
    "MockVoicePipeline",
    "FreshnessChecker",
    "RecapTextBuilder",
    "RecapTextValidationError",
    "RimePromptValidator",
    "RimeTtsClient",
    "get_pipeline",
]


def get_pipeline() -> VoicePipeline | MockVoicePipeline:
    """
    Factory: return ``MockVoicePipeline`` when ``USE_MOCKS=true``, else
    ``VoicePipeline``.

    Respects AGENTS.md Rule 6 — never hardcode which implementation to use.
    """
    from shared.config import settings

    if settings.use_mocks:
        return MockVoicePipeline()
    return VoicePipeline()
