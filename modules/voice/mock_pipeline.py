"""
modules/voice/mock_pipeline.py
--------------------------------
Pair D — Mock Voice Pipeline

Drop-in replacement for ``VoicePipeline`` when ``settings.use_mocks=True`` OR
when callers explicitly want a deterministic, zero-network-call result.

Used by:
  * Pair A (Transport) integration tests — need a valid ``TtsRequest`` without
    spinning up a real FreshnessChecker or a running mock API server.
  * The evaluation harness ``conftest.py`` for tests that only care about the
    final ``TtsRequest`` shape, not the freshness logic.

The mock always uses the Scenario C fixture from ``mocks/mock_brain.py``
(``price_usd`` changed $400 → $420) so the emitted ``TtsRequest.text`` will
include the ``"Heads up —"`` freshness flag.  This lets Transport/A verify
the full audio path without requiring Brain/C to be running.

Usage::

    from modules.voice.mock_pipeline import MockVoicePipeline
    tts_req = await MockVoicePipeline().run(recap_request)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from shared.schemas import (
    FreshnessResult,
    FreshnessStatus,
    FactCheckResult,
    RecapRequest,
    RimeModel,
    TtsRequest,
)
from shared.config import settings

logger = logging.getLogger(__name__)

# Canned spoken text matching Scenario C (Pair D's showcase scenario).
# Pure recap: headline → freshness flag → single next action (no repeated
# "still open" line — it only duplicates the headline or the next action).
_MOCK_SPOKEN_TEXT = (
    "Z wanted the Q3 number; you said you'd check with finance. "
    "Heads up — Unit price was $400, it's now $420. "
    "Your move: Loop in finance today and get back to Z on volume discounts."
)


class MockVoicePipeline:
    """
    Deterministic Voice & Facts pipeline for tests and local dev.

    ``run()`` returns instantly with a pre-built ``TtsRequest``; it does
    NOT call the FreshnessChecker, RecapTextBuilder, or any network service.
    """

    async def run(self, recap_request: RecapRequest) -> TtsRequest:
        logger.info(
            "mock_voice_pipeline: returning deterministic TtsRequest "
            "for request_id=%s",
            recap_request.request_id,
        )
        return TtsRequest(
            request_id=recap_request.request_id,
            session_id=recap_request.session_id,
            thread_id=recap_request.thread_id,
            text=_MOCK_SPOKEN_TEXT,
            model=RimeModel.CODA,
            speaker=settings.rime_default_speaker,
            language=settings.rime_default_language,
            time_scale_factor=settings.rime_time_scale_factor,
            speed_alpha=None,
            private_track_id=settings.private_track_id,
            is_interruptible=True,
            created_at=datetime.now(tz=timezone.utc),
        )

    async def aclose(self) -> None:
        """No-op — mock has no resources to release."""
        pass

    # ── convenience factory ────────────────────────────────────────────────────

    @staticmethod
    def make_freshness_result(recap_request: RecapRequest) -> FreshnessResult:
        """
        Return the deterministic ``FreshnessResult`` that corresponds to
        Scenario C (price changed).  Useful for unit-testing RecapTextBuilder
        in isolation.
        """
        from datetime import timezone

        results = []
        for fact in recap_request.facts_to_verify:
            if fact.key == "price_usd":
                results.append(
                    FactCheckResult(
                        key=fact.key,
                        label=fact.label,
                        cached_value=fact.value,
                        live_value="$420",
                        status=FreshnessStatus.CHANGED,
                        checked_at=datetime.now(tz=timezone.utc),
                        latency_ms=12,
                    )
                )
            else:
                results.append(
                    FactCheckResult(
                        key=fact.key,
                        label=fact.label,
                        cached_value=fact.value,
                        live_value=fact.value,
                        status=FreshnessStatus.UNCHANGED,
                        checked_at=datetime.now(tz=timezone.utc),
                        latency_ms=8,
                    )
                )

        return FreshnessResult(
            request_id=recap_request.request_id,
            thread_id=recap_request.thread_id,
            results=results,
            any_changed=any(r.status == FreshnessStatus.CHANGED for r in results),
            completed_at=datetime.now(tz=timezone.utc),
        )
