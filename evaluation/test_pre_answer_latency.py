"""
evaluation/test_pre_answer_latency.py
--------------------------------------
Acceptance Test 1 — Pre-answer latency

Blueprint § 13:
    Procedure: Force-disconnect a live call mid-sentence; force Z to call back;
               measure time from first ring to first audible recap word.
    Pass:      Recap begins within the first 1–2 rings, well before a human
               would typically answer (~5s).

Evidence artifact: evaluation/artifacts/latency_result.json
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from mocks.mock_call_session import MockCallSession
from shared.schemas import CallState

ARTIFACT = Path(__file__).parent / "artifacts" / "latency_result.json"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Stub — implement in Pair A + D integration sprint")
async def test_recap_starts_within_two_rings(use_mocks: bool) -> None:
    """
    Measure the wall-clock time from the first RINGING event to the first
    TtsRequest being emitted.

    Pass threshold: ≤ 5 seconds (≈ 2 rings).
    """
    # ── Arrange ──────────────────────────────────────────────────────────────
    session = MockCallSession(scenario="reconnect", ring_duration_s=20.0)
    first_ring_ts: float | None = None
    first_tts_ts: float | None = None

    # ── Act ───────────────────────────────────────────────────────────────────
    # TODO (Pair A + D): wire the real pipeline here.
    # Pseudocode:
    #   async for event in session.event_stream():
    #       if event.state == CallState.RINGING and event.is_reconnect:
    #           first_ring_ts = time.perf_counter()
    #           # trigger recap pipeline
    #           tts_req = await recap_pipeline.run(event)
    #           first_tts_ts = time.perf_counter()
    #           break

    # ── Temporary stub values (remove when implemented) ────────────────────
    first_ring_ts = time.perf_counter()
    await asyncio.sleep(0)  # placeholder
    first_tts_ts = time.perf_counter()

    # ── Assert ────────────────────────────────────────────────────────────────
    assert first_ring_ts is not None, "RINGING event was never received"
    assert first_tts_ts is not None, "TtsRequest was never emitted"

    latency_s = first_tts_ts - first_ring_ts
    result = {
        "test": "pre_answer_latency",
        "latency_s": round(latency_s, 3),
        "threshold_s": 5.0,
        "pass": latency_s <= 5.0,
    }

    ARTIFACT.write_text(json.dumps(result, indent=2))

    assert latency_s <= 5.0, (
        f"Recap latency {latency_s:.2f}s exceeds 5s threshold (≈ 2 rings). "
        f"See {ARTIFACT} for details."
    )
