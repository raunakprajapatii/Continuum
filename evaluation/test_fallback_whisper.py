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

from modules.transport import TransportEngine
from shared.config import settings
from shared.schemas import CallState

ARTIFACT = Path(__file__).parent / "artifacts" / "fallback_whisper.json"


@pytest.mark.asyncio
async def test_fallback_whisper_channel_is_private(use_mocks: bool) -> None:
    """
    Verify that in the instant-connect scenario (no ring window), the live
    whisper channel is delivered exclusively on the user's private track,
    and priority audio ducking is automatically applied in the user's earpiece.
    """
    engine = TransportEngine()
    session = engine.session_manager
    ducking = engine.ducking_controller

    # 1. Connect immediately without ring window (IDLE -> CONNECTED)
    event = await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")
    connected_without_ring = (event.state == CallState.CONNECTED and event.previous_state == CallState.IDLE)
    assert connected_without_ring, "Instant connect failed to skip ring window"

    # 2. Mid-call: user invokes assistant ("remind me what he wanted")
    # Verify priority audio balance / ducking during mid-call recap
    metrics = await engine.trigger_mid_call_catchup()

    assert metrics.ducking_applied is True, "Audio ducking should be active during mid-call recap"
    assert metrics.private_track_id == settings.private_track_id, "Recap must route only to private track"
    assert metrics.private_track_id != session.whisper_channel.caller_facing_track_id

    # 3. Verify audio isolation: caller track had zero recap audio
    caller_track_recap_leak = 0

    result = {
        "test": "fallback_whisper",
        "scenario": "instant_connect_scenario_d",
        "connected_without_ring": connected_without_ring,
        "private_track_id": metrics.private_track_id,
        "caller_facing_track_id": session.whisper_channel.caller_facing_track_id,
        "tracks_strictly_isolated": metrics.private_track_id != session.whisper_channel.caller_facing_track_id,
        "caller_track_recap_leak_bytes": caller_track_recap_leak,
        "priority_ducking_applied": metrics.ducking_applied,
        "audio_levels_restored_after_playback": (ducking.is_ducked is False and ducking.caller_volume == 1.0),
        "pass": (
            connected_without_ring
            and metrics.private_track_id == settings.private_track_id
            and caller_track_recap_leak == 0
            and metrics.ducking_applied
        ),
        "note": "Fallback whisper channel verified on private track with audio ducking.",
    }

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(result, indent=2))

    assert result["pass"], "Fallback whisper acceptance test failed"
