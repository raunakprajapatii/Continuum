"""
evaluation/test_fallback_whisper.py
-------------------------------------
Acceptance Test 6 — Fallback whisper channel (Scenario D)

Blueprint § 13:
    Procedure: Simulate an instant-connect call with no ring buffer; invoke the
               live whisper mid-call.
    Pass:      Whisper is audible only on the user's private track, with no
               audible artifact on the caller-facing track.

Evidence artifact: evaluation/artifacts/fallback_whisper.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.schemas import CallState

ARTIFACT = Path(__file__).parent / "artifacts" / "fallback_whisper.json"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Stub — implement in Pair A + D integration sprint")
async def test_fallback_whisper_channel_is_private(use_mocks: bool) -> None:
    """
    Verify that in the instant-connect scenario (no ring window), the live
    whisper channel is delivered exclusively on the user's private track.

    Implementation approach (Pair A + D):
      1. Use MockCallSession(scenario='instant_connect') to emit a CONNECTED
         event with no preceding RINGING.
      2. User invokes the assistant mid-call (button press or wake phrase).
      3. Verify TtsRequest.private_track_id is correct.
      4. Verify caller-facing track audio is silent during the whisper.
    """
    from mocks.mock_call_session import MockCallSession

    session = MockCallSession(scenario="instant_connect")
    connected_without_ring = False

    async for event in session.event_stream():
        if event.state == CallState.CONNECTED and event.previous_state == CallState.IDLE:
            connected_without_ring = True
            break

    result = {
        "test": "fallback_whisper",
        "connected_without_ring": connected_without_ring,
        "pass": connected_without_ring,
        "note": "Full audio isolation check requires Pair A LiveKit integration.",
    }

    ARTIFACT.write_text(json.dumps(result, indent=2))
    assert connected_without_ring, "instant_connect scenario did not skip ring window"
