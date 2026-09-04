"""
modules/voice/pipeline.py
---------------------------
Pair D — Voice & Facts Async Pipeline

Top-level orchestrator.  Called by Transport (Pair A) when a ``RecapRequest``
arrives from Brain (Pair C) during a RINGING + is_reconnect=True event.

Pipeline steps (all async, each step timed):

    RecapRequest
        │
        ▼  Step 1
    FreshnessChecker.check()   →  FreshnessResult
        │
        ▼  Step 2
    RecapTextBuilder.build()   →  spoken text (str)
        │                         (validates 8 Rime rules — raises on violation)
        ▼  Step 3
    RimeTtsClient.make_request()  →  TtsRequest
        │
        ▼
    (returned to Transport for Rime API call + private track playback)

Mock flag (AGENTS.md Rule 6):
    When ``settings.use_mocks=True`` the pipeline still runs all three steps
    but the FreshnessChecker queries the local mock API instead of a live
    data source.  The text builder and TTS client are the same in both modes.

Usage::

    from modules.voice.pipeline import VoicePipeline
    from mocks.mock_brain import make_recap_request

    pipeline = VoicePipeline()
    tts_request = await pipeline.run(make_recap_request())
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from shared.config import settings
from shared.schemas import RecapRequest, TtsRequest

from .freshness_checker import FreshnessChecker
from .recap_text_builder import RecapTextBuilder, RecapTextValidationError
from .rime_tts_client import RimeTtsClient

logger = logging.getLogger(__name__)


class VoicePipeline:
    """
    Async orchestrator for the full Voice & Facts module.

    Instantiate once per session (or once globally if stateless).
    The ``FreshnessChecker`` reuses its HTTP connection pool across calls.

    Args:
        freshness_checker: Optional override for testing / injection.
        text_builder:      Optional override for testing / injection.
        tts_client:        Optional override for testing / injection.
    """

    def __init__(
        self,
        freshness_checker: FreshnessChecker | None = None,
        text_builder: RecapTextBuilder | None = None,
        tts_client: RimeTtsClient | None = None,
    ) -> None:
        self._freshness = freshness_checker or FreshnessChecker()
        self._builder = text_builder or RecapTextBuilder()
        self._tts = tts_client or RimeTtsClient()

    async def run(self, recap_request: RecapRequest) -> TtsRequest:
        """
        Execute the full pipeline and return a ``TtsRequest``.

        Raises:
            ``RecapTextValidationError`` if the generated text fails Rime
            prompting guide validation.  Transport should log and discard
            this request; the caller hears nothing on their end (invariant
            preserved).

            Any other exception propagates as-is.
        """
        pipeline_start = time.monotonic()
        req_id = recap_request.request_id
        logger.info(
            "voice_pipeline: START request_id=%s urgency=%s",
            req_id,
            recap_request.urgency.value,
        )

        # ── Step 1: Fact-Freshness Check ──────────────────────────────────────
        t0 = time.monotonic()
        freshness_result = await self._freshness.check(recap_request)
        step1_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "voice_pipeline: step1 freshness done in %dms any_changed=%s",
            step1_ms,
            freshness_result.any_changed,
        )

        # ── Step 2: Build spoken text ─────────────────────────────────────────
        t0 = time.monotonic()
        try:
            spoken_text = self._builder.build(
                summary=recap_request.summary,
                freshness=freshness_result,
                urgency=recap_request.urgency,
            )
        except RecapTextValidationError as exc:
            logger.error(
                "voice_pipeline: recap text FAILED validation for request_id=%s: %s",
                req_id,
                exc,
            )
            raise
        step2_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "voice_pipeline: step2 text built in %dms len=%d chars",
            step2_ms,
            len(spoken_text),
        )
        logger.debug("voice_pipeline: spoken_text=%r", spoken_text)

        # ── Step 3: Build TtsRequest ──────────────────────────────────────────
        t0 = time.monotonic()
        tts_request = self._tts.make_request(
            recap_request=recap_request,
            spoken_text=spoken_text,
        )
        step3_ms = int((time.monotonic() - t0) * 1000)

        total_ms = int((time.monotonic() - pipeline_start) * 1000)
        logger.info(
            "voice_pipeline: DONE request_id=%s total=%dms "
            "(freshness=%dms text=%dms tts=%dms) model=%s",
            req_id,
            total_ms,
            step1_ms,
            step2_ms,
            step3_ms,
            tts_request.model.value,
        )

        return tts_request

    async def aclose(self) -> None:
        """Release resources (HTTP client pool in FreshnessChecker)."""
        await self._freshness.aclose()
