"""
tests/test_transport.py
-----------------------
Unit tests for Continuum Pair A (Transport) module:
  - CallSessionManager FSM & transitions
  - Reconnect detection & thread matching
  - Dual-track isolation & TrackFencingViolationError
  - PrivateWhisperChannel playback & metrics
  - AudioDuckingController (caller volume reduction & recap voice boost)
  - Barge-in interruptibility (< 500ms latency)
  - Mid-call catch-up trigger with ducking
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

import pytest

from modules.transport import (
    AudioDuckingController,
    CallSessionManager,
    PrivateWhisperChannel,
    SessionStateError,
    TrackFencingViolationError,
    TransportEngine,
)
from shared.config import settings
from shared.schemas import CallState, RimeModel, TtsRequest


def _make_sample_tts_request(
    private_track_id: str = settings.private_track_id,
    text: str = "Z wanted the Q3 number; you said you'd check with finance.",
) -> TtsRequest:
    return TtsRequest(
        request_id=str(uuid.uuid4()),
        session_id="test-session-001",
        thread_id="mock-thread-Z-001",
        text=text,
        model=RimeModel.CODA,
        speaker=settings.rime_default_speaker,
        private_track_id=private_track_id,
        created_at=datetime.now(tz=timezone.utc),
    )


# ── FSM & Session Manager Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_manager_fsm_lifecycle() -> None:
    session = CallSessionManager(session_id="test-sess-123")
    assert session.current_state == CallState.IDLE

    # IDLE -> RINGING
    evt_ring = await session.transition_to(CallState.RINGING, caller_id="+14155550199")
    assert session.current_state == CallState.RINGING
    assert session.caller_id == "+14155550199"
    assert evt_ring.state == CallState.RINGING
    assert evt_ring.is_reconnect is True  # Default contact Z is pre-seeded
    assert session.thread_id == "mock-thread-Z-001"

    # RINGING -> CONNECTED
    evt_conn = await session.transition_to(CallState.CONNECTED)
    assert session.current_state == CallState.CONNECTED
    assert evt_conn.state == CallState.CONNECTED

    # CONNECTED -> COMPLETED
    evt_comp = await session.transition_to(CallState.COMPLETED)
    assert session.current_state == CallState.COMPLETED
    assert evt_comp.state == CallState.COMPLETED


@pytest.mark.asyncio
async def test_session_manager_rejects_invalid_transitions() -> None:
    session = CallSessionManager()
    assert session.current_state == CallState.IDLE

    # IDLE cannot jump directly to COMPLETED or DISCONNECTED
    with pytest.raises(SessionStateError) as exc_info:
        await session.transition_to(CallState.COMPLETED)
    assert "Invalid call state transition" in str(exc_info.value)


@pytest.mark.asyncio
async def test_session_manager_event_subscription() -> None:
    session = CallSessionManager()
    queue = session.subscribe()

    await session.transition_to(CallState.RINGING, caller_id="+14155550199")
    await session.transition_to(CallState.CONNECTED)

    evt1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt1.state == CallState.RINGING

    evt2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt2.state == CallState.CONNECTED

    session.unsubscribe(queue)


# ── Dual-Track Invariant & Fencing Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_dual_track_fencing_rejects_caller_facing_destination() -> None:
    channel = PrivateWhisperChannel()
    caller_track = channel.caller_facing_track_id

    # Construct illegal TtsRequest targeted at caller-facing track
    bad_request = _make_sample_tts_request(private_track_id=caller_track)

    with pytest.raises(TrackFencingViolationError) as exc_info:
        await channel.play_recap(bad_request)

    assert "Dual-track invariant violated" in str(exc_info.value)


@pytest.mark.asyncio
async def test_dual_track_fencing_rejects_arbitrary_unauthorized_track() -> None:
    channel = PrivateWhisperChannel()
    bad_request = _make_sample_tts_request(private_track_id="rogue-track-external")

    with pytest.raises(TrackFencingViolationError) as exc_info:
        await channel.play_recap(bad_request)

    assert "Mismatched private track ID" in str(exc_info.value)


# ── Audio Ducking & Volume Balancing Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_audio_ducking_controller_flow() -> None:
    ducking = AudioDuckingController(
        normal_caller_volume=1.0,
        ducked_caller_volume=0.25,
        normal_recap_volume=1.0,
        boosted_recap_volume=1.25,
    )

    assert ducking.is_ducked is False
    assert ducking.caller_volume == 1.0
    assert ducking.recap_volume == 1.0

    # User lifts call / requests catch-up -> ducking activated
    levels = await ducking.activate_ducking(reason="test_mid_call")
    assert levels.is_ducked is True
    assert levels.caller_volume == 0.25
    assert levels.recap_volume == 1.25
    assert ducking.is_ducked is True

    # Recap finished -> levels restored
    restored = await ducking.restore_levels(reason="test_recap_complete")
    assert restored.is_ducked is False
    assert restored.caller_volume == 1.0
    assert restored.recap_volume == 1.0


# ── Barge-In Interruptibility Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_barge_in_interrupt_latency() -> None:
    channel = PrivateWhisperChannel()
    req = _make_sample_tts_request(text="A long recap sentence that takes several seconds to play out completely.")

    # Start playback task
    play_task = asyncio.create_task(channel.play_recap(req))
    await asyncio.sleep(0.1)  # Let playback begin

    assert channel.is_playing is True

    # User barges in ("skip, I remember")
    t0 = time.perf_counter()
    stop_latency_ms = await channel.interrupt(reason="user_barge_in")
    metrics = await play_task

    assert stop_latency_ms < 500.0, f"Barge-in latency {stop_latency_ms}ms exceeded 500ms limit"
    assert metrics.interrupted is True
    assert channel.is_playing is False


# ── Mid-Call Catch-Up & Integration Tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_mid_call_catch_up_activates_ducking() -> None:
    engine = TransportEngine()
    session = engine.session_manager

    # Transition to CONNECTED
    await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")

    # Mid-call catch-up triggered
    metrics = await engine.trigger_mid_call_catchup()

    assert metrics.ducking_applied is True
    # Ducking should be restored after recap completion
    assert engine.ducking_controller.is_ducked is False
    assert engine.ducking_controller.caller_volume == 1.0
