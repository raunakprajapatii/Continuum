"""
evaluation/test_interruptibility.py
-------------------------------------
Acceptance Test 5 — Interruptibility

Blueprint § 13:
    Procedure: User barges in mid-recap ("skip, I remember").
    Pass:      Queued Rime audio stops promptly; no orphaned audio continues playing.

Evidence artifact: evaluation/artifacts/interruptibility.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ARTIFACT = Path(__file__).parent / "artifacts" / "interruptibility.json"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Stub — implement in Pair A + D integration sprint (LiveKit VAD barge-in)")
async def test_recap_stops_on_barge_in(use_mocks: bool) -> None:
    """
    Verify that when the user speaks on the private mic path during recap,
    Rime TTS playback stops within an acceptable window (< 500ms).

    Implementation approach (Pair A + D):
      1. Start streaming a TtsRequest to the private track.
      2. Simulate VAD activity on the user's private mic at t+2s.
      3. Measure time from VAD trigger to audio silence on the private track.
      4. Assert no audio continues after the stop window.

    TtsRequest.is_interruptible=True is the flag that enables this behaviour.
    Transport must honour it.
    """
    # TODO (Pair A + D): implement real barge-in test
    stop_latency_ms = 0  # placeholder

    result = {
        "test": "interruptibility",
        "stop_latency_ms": stop_latency_ms,
        "threshold_ms": 500,
        "pass": stop_latency_ms <= 500,
        "note": "Stub — full test requires Pair A LiveKit audio track control.",
    }

    ARTIFACT.write_text(json.dumps(result, indent=2))
    assert stop_latency_ms <= 500
