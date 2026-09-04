"""
tests/test_transport.py
-----------------------
Comprehensive unit tests for Continuum Pair A (Transport) module.

Coverage areas:
  1.  CallSessionManager FSM — valid lifecycle transitions
  2.  CallSessionManager FSM — invalid / illegal transitions
  3.  Reconnect detection — known caller
  4.  Reconnect detection — unknown caller (no false positives)
  5.  DISCONNECTED -> RINGING re-registration of interrupted thread
  6.  CallStateEvent subscription, delivery, and unsubscribe safety
  7.  Unsubscribing a never-registered queue is safe
  8.  Event history records all transitions
  9.  elapsed_ring_seconds is None before RINGING
  10. elapsed_ring_seconds grows during RINGING
  11. Dual-track isolation — caller-facing destination blocked
  12. Dual-track isolation — arbitrary unauthorized track blocked
  13. PrivateWhisperChannel — successful playback + metrics
  14. PrivateWhisperChannel — interrupt when not playing returns 0.0
  15. PrivateWhisperChannel — preempt in-progress recap with new one
  16. AudioDuckingController — activate -> restore cycle
  17. AudioDuckingController — restore when not ducked is a no-op
  18. AudioDuckingController — async on_level_change callback is awaited
  19. AudioDuckingController — negative caller_volume raises ValueError
  20. AudioDuckingController — caller_volume > 1.0 raises ValueError
  21. AudioDuckingController — recap_volume > 2.0 raises ValueError
  22. AudioDuckingController — concurrent activate_ducking calls are safe
  23. Barge-in latency < 500 ms invariant
  24. Mid-call catch-up — happy path with ducking applied and restored
  25. Mid-call catch-up raises SessionStateError when call is IDLE
  26. Mid-call catch-up raises SessionStateError after call COMPLETES
  27. Mid-call catch-up accepts an async callback
  28. TransportEngine — start() is idempotent (double-call safe)
  29. TransportEngine — stop() interrupts active playback
  30. TransportEngine — deliver_recap ducks when CONNECTED
  31. TransportEngine — deliver_recap does NOT duck when RINGING
  32. simulate_call_lifecycle — unknown scenario raises ValueError
  33. simulate_call_lifecycle — reconnect scenario end-to-end
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tts(
    private_track_id: str = settings.private_track_id,
    text: str = "Z wanted the Q3 number; you said you'd check with finance.",
    session_id: str = "test-session-001",
) -> TtsRequest:
    return TtsRequest(
        request_id=str(uuid.uuid4()),
        session_id=session_id,
        thread_id="mock-thread-Z-001",
        text=text,
        model=RimeModel.CODA,
        speaker=settings.rime_default_speaker,
        private_track_id=private_track_id,
        created_at=datetime.now(tz=timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FSM — valid lifecycle transitions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_manager_fsm_lifecycle() -> None:
    """Full happy-path IDLE -> RINGING -> CONNECTED -> COMPLETED."""
    session = CallSessionManager(session_id="test-sess-lifecycle")
    assert session.current_state == CallState.IDLE

    # IDLE -> RINGING (contact Z pre-seeded -> reconnect detected)
    evt_ring = await session.transition_to(CallState.RINGING, caller_id="+14155550199")
    assert session.current_state == CallState.RINGING
    assert session.caller_id == "+14155550199"
    assert evt_ring.state == CallState.RINGING
    assert evt_ring.is_reconnect is True
    assert session.thread_id == "mock-thread-Z-001"

    # RINGING -> CONNECTED
    evt_conn = await session.transition_to(CallState.CONNECTED)
    assert session.current_state == CallState.CONNECTED
    assert evt_conn.state == CallState.CONNECTED
    assert evt_conn.previous_state == CallState.RINGING

    # CONNECTED -> COMPLETED
    evt_comp = await session.transition_to(CallState.COMPLETED)
    assert session.current_state == CallState.COMPLETED
    assert evt_comp.state == CallState.COMPLETED


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FSM — invalid/illegal transitions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_manager_rejects_idle_to_completed() -> None:
    """IDLE cannot jump directly to COMPLETED."""
    session = CallSessionManager()
    with pytest.raises(SessionStateError) as exc_info:
        await session.transition_to(CallState.COMPLETED)
    assert "Invalid call state transition" in str(exc_info.value)


@pytest.mark.asyncio
async def test_session_manager_rejects_idle_to_disconnected() -> None:
    """IDLE -> DISCONNECTED is an illegal jump."""
    session = CallSessionManager()
    with pytest.raises(SessionStateError):
        await session.transition_to(CallState.DISCONNECTED)


@pytest.mark.asyncio
async def test_session_manager_rejects_connected_to_ringing() -> None:
    """CONNECTED -> RINGING is not a valid transition."""
    session = CallSessionManager()
    await session.transition_to(CallState.CONNECTED, caller_id="+10000000001")
    with pytest.raises(SessionStateError):
        await session.transition_to(CallState.RINGING)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Reconnect detection — known caller
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reconnect_detection_known_caller() -> None:
    """Known caller triggers is_reconnect=True and retrieves the correct thread_id."""
    session = CallSessionManager()
    session.register_interrupted_thread("+15551234567", "thread-vip-001")

    evt = await session.transition_to(CallState.RINGING, caller_id="+15551234567")
    assert evt.is_reconnect is True
    assert session.thread_id == "thread-vip-001"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Reconnect detection — unknown caller must NOT be a false positive
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reconnect_detection_unknown_caller_no_false_positive() -> None:
    """Unknown caller yields is_reconnect=False — no false positives."""
    # Empty registry ensures no pre-seeds
    session = CallSessionManager(interrupted_threads_registry={})
    evt = await session.transition_to(CallState.RINGING, caller_id="+19999999999")
    assert evt.is_reconnect is False
    assert session.thread_id is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DISCONNECTED -> RINGING re-registration
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_disconnected_registers_thread_for_future_reconnect() -> None:
    """Abrupt DISCONNECTED auto-re-registers the thread so a callback is matched."""
    session = CallSessionManager(
        interrupted_threads_registry={"+15550001111": "thread-abc"}
    )
    await session.transition_to(CallState.RINGING, caller_id="+15550001111")
    await session.transition_to(CallState.CONNECTED)
    await session.transition_to(CallState.DISCONNECTED)

    # Thread should be re-registered so the next RINGING from same number reconnects
    assert "+15550001111" in session._interrupted_threads


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Subscription, delivery, and unsubscribe
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_manager_event_subscription() -> None:
    """Subscribers receive events in order; after unsubscribe no more events arrive."""
    session = CallSessionManager()
    queue = session.subscribe()

    await session.transition_to(CallState.RINGING, caller_id="+14155550199")
    await session.transition_to(CallState.CONNECTED)

    evt1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt1.state == CallState.RINGING

    evt2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt2.state == CallState.CONNECTED

    session.unsubscribe(queue)

    # Further transitions must NOT put to the now-removed queue
    await session.transition_to(CallState.COMPLETED)
    assert queue.empty()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Unsubscribing a never-registered queue is safe
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_queue_is_safe() -> None:
    session = CallSessionManager()
    ghost: asyncio.Queue = asyncio.Queue()
    session.unsubscribe(ghost)  # Must not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Event history records all transitions
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_event_history_records_all_transitions() -> None:
    session = CallSessionManager()
    await session.transition_to(CallState.RINGING, caller_id="+14155550199")
    await session.transition_to(CallState.CONNECTED)
    await session.transition_to(CallState.COMPLETED)

    states = [e.state for e in session._event_history]
    assert states == [CallState.RINGING, CallState.CONNECTED, CallState.COMPLETED]


# ═══════════════════════════════════════════════════════════════════════════════
# 9 & 10. elapsed_ring_seconds timing
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_elapsed_ring_seconds_none_before_ringing() -> None:
    session = CallSessionManager()
    assert session.elapsed_ring_seconds is None


@pytest.mark.asyncio
async def test_elapsed_ring_seconds_grows_during_ringing() -> None:
    session = CallSessionManager()
    await session.transition_to(CallState.RINGING, caller_id="+14155550199")
    await asyncio.sleep(0.05)
    elapsed = session.elapsed_ring_seconds
    assert elapsed is not None
    assert elapsed >= 0.04, f"Expected >=40ms, got {elapsed:.3f}s"


# ═══════════════════════════════════════════════════════════════════════════════
# 11 & 12. Dual-track fencing
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dual_track_fencing_rejects_caller_facing_destination() -> None:
    """Routing recap to the caller-facing track raises TrackFencingViolationError."""
    channel = PrivateWhisperChannel()
    bad_req = _make_tts(private_track_id=channel.caller_facing_track_id)

    with pytest.raises(TrackFencingViolationError) as exc_info:
        await channel.play_recap(bad_req)
    assert "Dual-track invariant violated" in str(exc_info.value)


@pytest.mark.asyncio
async def test_dual_track_fencing_rejects_arbitrary_unauthorized_track() -> None:
    """Any unrecognised track ID also raises TrackFencingViolationError."""
    channel = PrivateWhisperChannel()
    bad_req = _make_tts(private_track_id="rogue-external-track")

    with pytest.raises(TrackFencingViolationError) as exc_info:
        await channel.play_recap(bad_req)
    assert "Mismatched private track ID" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. PrivateWhisperChannel — successful playback
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_whisper_channel_playback_returns_valid_metrics() -> None:
    """Short text recap completes and returns coherent PlaybackMetrics."""
    channel = PrivateWhisperChannel()
    req = _make_tts(text="Hi.")  # very short -> near-instant in mock

    metrics = await channel.play_recap(req)

    assert metrics.interrupted is False
    assert metrics.completed_at is not None
    assert metrics.duration_s >= 0.0
    assert metrics.request_id == req.request_id
    assert metrics.private_track_id == req.private_track_id
    assert channel.is_playing is False
    assert channel.last_metrics is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 14. interrupt() when not playing returns 0.0 ms
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_interrupt_when_not_playing_returns_zero() -> None:
    channel = PrivateWhisperChannel()
    latency = await channel.interrupt(reason="user_barge_in")
    assert latency == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Preempt an in-progress recap with a new one
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_new_recap_preempts_existing_recap() -> None:
    """A second play_recap() while one is running cancels and marks the first interrupted."""
    channel = PrivateWhisperChannel()
    long_req = _make_tts(
        text="A very long recap that would take many seconds to finish completely in full."
    )
    short_req = _make_tts(text="Short follow-up.")

    long_task = asyncio.create_task(channel.play_recap(long_req))
    await asyncio.sleep(0.1)  # let it start
    assert channel.is_playing

    metrics_short = await channel.play_recap(short_req)
    long_metrics = await long_task

    assert long_metrics.interrupted is True
    assert metrics_short.interrupted is False


# ═══════════════════════════════════════════════════════════════════════════════
# 16 & 17. AudioDuckingController — core flow
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_audio_ducking_controller_flow() -> None:
    """Activate lowers caller volume and boosts recap; restore returns everything to 1.0."""
    ducking = AudioDuckingController(
        normal_caller_volume=1.0,
        ducked_caller_volume=0.25,
        normal_recap_volume=1.0,
        boosted_recap_volume=1.25,
    )

    assert ducking.is_ducked is False
    assert ducking.caller_volume == 1.0
    assert ducking.recap_volume == 1.0

    levels = await ducking.activate_ducking(reason="test")
    assert levels.is_ducked is True
    assert levels.caller_volume == 0.25
    assert levels.recap_volume == 1.25
    assert ducking.is_ducked is True

    restored = await ducking.restore_levels(reason="done")
    assert restored.is_ducked is False
    assert restored.caller_volume == 1.0
    assert restored.recap_volume == 1.0
    assert ducking.is_ducked is False


@pytest.mark.asyncio
async def test_restore_when_not_ducked_is_noop() -> None:
    """restore_levels() at normal levels must not raise or mutate state."""
    ducking = AudioDuckingController()
    levels = await ducking.restore_levels(reason="spurious_restore")
    assert levels.is_ducked is False
    assert levels.caller_volume == ducking.DEFAULT_NORMAL_CALLER_VOLUME


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Async on_level_change callback is properly awaited
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ducking_async_callback_is_awaited() -> None:
    calls = []

    async def async_cb(levels):
        calls.append(levels)

    ducking = AudioDuckingController(on_level_change=async_cb)
    await ducking.activate_ducking()
    await ducking.restore_levels()

    assert len(calls) == 2
    assert calls[0].is_ducked is True
    assert calls[1].is_ducked is False


# ═══════════════════════════════════════════════════════════════════════════════
# 19-22. Volume bounds validation
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ducking_rejects_negative_caller_volume() -> None:
    ducking = AudioDuckingController()
    with pytest.raises(ValueError, match="caller_volume must be in"):
        await ducking.activate_ducking(caller_volume=-0.1)


@pytest.mark.asyncio
async def test_ducking_rejects_caller_volume_above_one() -> None:
    ducking = AudioDuckingController()
    with pytest.raises(ValueError, match="caller_volume must be in"):
        await ducking.activate_ducking(caller_volume=1.5)


@pytest.mark.asyncio
async def test_ducking_rejects_recap_volume_above_two() -> None:
    ducking = AudioDuckingController()
    with pytest.raises(ValueError, match="recap_volume must be in"):
        await ducking.activate_ducking(recap_volume=3.0)


@pytest.mark.asyncio
async def test_ducking_rejects_negative_recap_volume() -> None:
    ducking = AudioDuckingController()
    with pytest.raises(ValueError, match="recap_volume must be in"):
        await ducking.activate_ducking(recap_volume=-1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 22. Concurrent ducking calls are safe (asyncio.Lock)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_ducking_calls_are_safe() -> None:
    """Multiple concurrent activate_ducking() calls must leave a consistent state."""
    ducking = AudioDuckingController()
    await asyncio.gather(
        ducking.activate_ducking(reason="caller_a"),
        ducking.activate_ducking(reason="caller_b"),
        ducking.activate_ducking(reason="caller_c"),
    )
    # After all concurrent calls the controller must be in a valid state
    assert ducking.is_ducked is True
    assert 0.0 <= ducking.caller_volume <= 1.0
    assert 0.0 <= ducking.recap_volume <= 2.0


# ═══════════════════════════════════════════════════════════════════════════════
# 23. Barge-in interruptibility (< 500 ms invariant)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_barge_in_interrupt_latency() -> None:
    """User barge-in stops recap within < 500 ms (Blueprint invariant)."""
    channel = PrivateWhisperChannel()
    req = _make_tts(
        text="A long recap sentence that takes several seconds to play out completely."
    )

    play_task = asyncio.create_task(channel.play_recap(req))
    await asyncio.sleep(0.1)
    assert channel.is_playing is True

    stop_latency_ms = await channel.interrupt(reason="user_barge_in")
    metrics = await play_task

    assert stop_latency_ms < 500.0, (
        f"Barge-in latency {stop_latency_ms:.1f}ms exceeded 500ms Blueprint requirement"
    )
    assert metrics.interrupted is True
    assert channel.is_playing is False


# ═══════════════════════════════════════════════════════════════════════════════
# 24. Mid-call catch-up — happy path
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mid_call_catch_up_activates_ducking() -> None:
    """trigger_mid_call_catchup ducks audio and restores levels after playback."""
    engine = TransportEngine()
    session = engine.session_manager

    await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")
    metrics = await engine.trigger_mid_call_catchup()

    assert metrics.ducking_applied is True
    # Ducking MUST be fully restored after recap finishes
    assert engine.ducking_controller.is_ducked is False
    assert engine.ducking_controller.caller_volume == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 25 & 26. Mid-call catch-up raises SessionStateError on wrong state
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mid_call_catch_up_raises_when_idle() -> None:
    """trigger_mid_call_catchup must raise SessionStateError when call is IDLE."""
    session = CallSessionManager()
    with pytest.raises(SessionStateError, match="CONNECTED state"):
        await session.trigger_mid_call_catchup()


@pytest.mark.asyncio
async def test_mid_call_catch_up_raises_after_call_completes() -> None:
    """Once COMPLETED, mid-call catch-up must be denied."""
    session = CallSessionManager()
    await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")
    await session.transition_to(CallState.COMPLETED)

    with pytest.raises(SessionStateError, match="CONNECTED state"):
        await session.trigger_mid_call_catchup()


# ═══════════════════════════════════════════════════════════════════════════════
# 27. Mid-call catch-up with async callback
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mid_call_catch_up_with_async_callback() -> None:
    """Async recap_request_callback is properly awaited."""
    engine = TransportEngine()
    session = engine.session_manager
    await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")

    async def async_callback() -> TtsRequest:
        await asyncio.sleep(0)  # simulate async I/O
        return _make_tts(text="Async callback recap.")

    metrics = await engine.trigger_mid_call_catchup(recap_request_callback=async_callback)
    assert metrics.ducking_applied is True
    assert engine.ducking_controller.is_ducked is False


# ═══════════════════════════════════════════════════════════════════════════════
# 28. TransportEngine — start() is idempotent
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_engine_start_is_idempotent() -> None:
    """Calling start() twice must not raise; engine stays running."""
    engine = TransportEngine()
    await engine.start()
    assert engine.is_running is True

    await engine.start()  # second call — must be a no-op
    assert engine.is_running is True


# ═══════════════════════════════════════════════════════════════════════════════
# 29. TransportEngine — stop() interrupts active playback
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_engine_stop_interrupts_active_playback() -> None:
    """stop() cancels any in-progress recap and sets is_running=False."""
    engine = TransportEngine()
    await engine.start()
    session = engine.session_manager
    await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")

    req = _make_tts(
        text="A very long recap that should be interrupted by engine shutdown."
    )
    play_task = asyncio.create_task(engine.deliver_recap(req))
    await asyncio.sleep(0.1)

    await engine.stop()
    metrics = await play_task

    assert engine.is_running is False
    assert metrics.interrupted is True


# ═══════════════════════════════════════════════════════════════════════════════
# 30. deliver_recap ducks when CONNECTED
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_engine_deliver_recap_applies_ducking_when_connected() -> None:
    engine = TransportEngine()
    session = engine.session_manager
    await session.transition_to(CallState.CONNECTED, caller_id="+14155550199")

    req = _make_tts(text="Quick recap.")
    metrics = await engine.deliver_recap(req, enable_audio_ducking=True)

    assert metrics.ducking_applied is True
    assert engine.ducking_controller.is_ducked is False  # restored after playback


# ═══════════════════════════════════════════════════════════════════════════════
# 31. deliver_recap does NOT duck when RINGING
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_engine_deliver_recap_no_ducking_when_ringing() -> None:
    """During RINGING the caller can't hear the recap so no ducking needed."""
    engine = TransportEngine()
    session = engine.session_manager
    await session.transition_to(CallState.RINGING, caller_id="+14155550199")

    req = _make_tts(text="Ring-window recap.")
    metrics = await engine.deliver_recap(req, enable_audio_ducking=True)

    assert metrics.ducking_applied is False


# ═══════════════════════════════════════════════════════════════════════════════
# 32. simulate_call_lifecycle — unknown scenario raises ValueError
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_simulate_unknown_scenario_raises_value_error() -> None:
    session = CallSessionManager()
    with pytest.raises(ValueError, match="Unknown call scenario"):
        await session.simulate_call_lifecycle(scenario="totally_fake_scenario")


# ═══════════════════════════════════════════════════════════════════════════════
# 33. simulate_call_lifecycle — reconnect scenario end-to-end
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_simulate_reconnect_scenario_end_to_end() -> None:
    """simulate_call_lifecycle('reconnect') produces correct state sequence."""
    session = CallSessionManager(interrupted_threads_registry={})

    events = await session.simulate_call_lifecycle(
        scenario="reconnect",
        caller_id="+14155550199",
        ring_duration_s=0.05,
        connected_duration_s=0.05,
    )

    states = [e.state for e in events]
    assert states == [CallState.RINGING, CallState.CONNECTED, CallState.COMPLETED]
    # reconnect scenario pre-registers the thread, so is_reconnect is True on RINGING
    assert events[0].is_reconnect is True
