"""
modules/signal/tests/test_reconnect_detection.py
--------------------------------------------------
Unit tests for the ReconnectDetector FSM.

Tests cover all five call states and the reconnect detection logic:
  - Normal call (IDLE → RINGING → CONNECTED → COMPLETED)
  - Abrupt disconnect marks caller as interrupted
  - Reconnect on second RINGING from same caller
  - Transport-flagged reconnect (event.is_reconnect=True)
  - Same caller third call after successful reconnect does NOT retrigger
  - CONNECTED always starts STT; DISCONNECTED/COMPLETED always stops STT
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from modules.signal.reconnect_detector import ReconnectDetector
from shared.schemas import CallState, CallStateEvent


# ── Helpers ───────────────────────────────────────────────────────────────────

CALLER_Z = "+14155550199"
SESSION_1 = "session-001"
SESSION_2 = "session-002"
THREAD_Z = "thread-Z-001"


def _ev(
    state: CallState,
    caller_id: str | None = CALLER_Z,
    session_id: str = SESSION_1,
    thread_id: str | None = THREAD_Z,
    previous_state: CallState | None = None,
    is_reconnect: bool = False,
) -> CallStateEvent:
    return CallStateEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        thread_id=thread_id,
        state=state,
        previous_state=previous_state,
        caller_id=caller_id,
        is_reconnect=is_reconnect,
        timestamp=datetime.now(tz=timezone.utc),
    )


# ── Normal call flow ──────────────────────────────────────────────────────────


class TestNormalCallFlow:
    @pytest.fixture
    def detector(self) -> ReconnectDetector:
        return ReconnectDetector()

    @pytest.mark.asyncio
    async def test_ringing_first_contact_is_not_reconnect(
        self, detector: ReconnectDetector
    ) -> None:
        decision = await detector.on_event(_ev(CallState.RINGING))
        assert not decision.is_reconnect
        assert not decision.should_start_stt

    @pytest.mark.asyncio
    async def test_connected_starts_stt(self, detector: ReconnectDetector) -> None:
        await detector.on_event(_ev(CallState.RINGING))
        decision = await detector.on_event(_ev(CallState.CONNECTED))
        assert decision.should_start_stt
        assert not decision.should_stop_stt

    @pytest.mark.asyncio
    async def test_completed_stops_stt_cleanly(self, detector: ReconnectDetector) -> None:
        await detector.on_event(_ev(CallState.RINGING))
        await detector.on_event(_ev(CallState.CONNECTED))
        decision = await detector.on_event(_ev(CallState.COMPLETED))
        assert decision.should_stop_stt
        assert not decision.call_ended_abruptly

    @pytest.mark.asyncio
    async def test_disconnected_stops_stt_abruptly(self, detector: ReconnectDetector) -> None:
        await detector.on_event(_ev(CallState.RINGING))
        await detector.on_event(_ev(CallState.CONNECTED))
        decision = await detector.on_event(_ev(CallState.DISCONNECTED))
        assert decision.should_stop_stt
        assert decision.call_ended_abruptly

    @pytest.mark.asyncio
    async def test_idle_no_action(self, detector: ReconnectDetector) -> None:
        decision = await detector.on_event(_ev(CallState.IDLE, caller_id=None, thread_id=None))
        assert not decision.should_start_stt
        assert not decision.should_stop_stt
        assert not decision.is_reconnect


# ── Reconnect detection ───────────────────────────────────────────────────────


class TestReconnectDetection:
    @pytest.fixture
    def detector(self) -> ReconnectDetector:
        return ReconnectDetector()

    @pytest.mark.asyncio
    async def test_reconnect_detected_after_disconnect(
        self, detector: ReconnectDetector
    ) -> None:
        """Full reconnect flow: call drops, same caller rings back → reconnect detected."""
        # Session 1: call, connect, disconnect abruptly
        await detector.on_event(_ev(CallState.RINGING, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.CONNECTED, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.DISCONNECTED, session_id=SESSION_1))

        # Session 2: same caller rings again
        decision = await detector.on_event(
            _ev(CallState.RINGING, session_id=SESSION_2)
        )
        assert decision.is_reconnect, "Expected reconnect flag to be True"
        assert decision.prior_thread_id == THREAD_Z

    @pytest.mark.asyncio
    async def test_no_reconnect_after_clean_completion(
        self, detector: ReconnectDetector
    ) -> None:
        """If first call ended normally (COMPLETED), second call is fresh — no reconnect."""
        await detector.on_event(_ev(CallState.RINGING, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.CONNECTED, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.COMPLETED, session_id=SESSION_1))

        decision = await detector.on_event(
            _ev(CallState.RINGING, session_id=SESSION_2)
        )
        assert not decision.is_reconnect

    @pytest.mark.asyncio
    async def test_transport_flagged_reconnect_is_honoured(
        self, detector: ReconnectDetector
    ) -> None:
        """Transport (Pair A) may already set is_reconnect=True — we trust and forward it."""
        decision = await detector.on_event(
            _ev(CallState.RINGING, is_reconnect=True)
        )
        assert decision.is_reconnect
        assert decision.prior_thread_id == THREAD_Z

    @pytest.mark.asyncio
    async def test_reconnect_flag_cleared_after_first_reconnect(
        self, detector: ReconnectDetector
    ) -> None:
        """
        After a reconnect is handled, a THIRD call from the same number should NOT
        be treated as another reconnect (unless that call also drops and triggers a new drop).
        """
        # Session 1: drop
        await detector.on_event(_ev(CallState.RINGING, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.CONNECTED, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.DISCONNECTED, session_id=SESSION_1))

        # Session 2: reconnect (triggers is_reconnect=True), then completes cleanly
        decision_s2 = await detector.on_event(_ev(CallState.RINGING, session_id=SESSION_2))
        assert decision_s2.is_reconnect

        await detector.on_event(_ev(CallState.CONNECTED, session_id=SESSION_2))
        await detector.on_event(_ev(CallState.COMPLETED, session_id=SESSION_2))

        # Session 3: same caller again — should NOT be a reconnect
        decision_s3 = await detector.on_event(
            _ev(CallState.RINGING, session_id="session-003")
        )
        assert not decision_s3.is_reconnect

    @pytest.mark.asyncio
    async def test_different_caller_does_not_trigger_reconnect(
        self, detector: ReconnectDetector
    ) -> None:
        """Caller Z drops. Caller Y calls in. Y should not be flagged as reconnect."""
        CALLER_Y = "+19998887777"

        # Caller Z drops
        await detector.on_event(_ev(CallState.RINGING, caller_id=CALLER_Z, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.CONNECTED, caller_id=CALLER_Z, session_id=SESSION_1))
        await detector.on_event(_ev(CallState.DISCONNECTED, caller_id=CALLER_Z, session_id=SESSION_1))

        # Caller Y calls in (different number)
        decision = await detector.on_event(
            _ev(CallState.RINGING, caller_id=CALLER_Y, session_id=SESSION_2)
        )
        assert not decision.is_reconnect

    @pytest.mark.asyncio
    async def test_reconnect_prior_thread_id_forwarded(
        self, detector: ReconnectDetector
    ) -> None:
        """The prior thread_id must be accurately forwarded so Brain can hydrate the right summary."""
        custom_thread = "custom-thread-abc"

        await detector.on_event(
            _ev(CallState.RINGING, session_id=SESSION_1, thread_id=custom_thread)
        )
        await detector.on_event(_ev(CallState.CONNECTED, session_id=SESSION_1, thread_id=custom_thread))
        await detector.on_event(_ev(CallState.DISCONNECTED, session_id=SESSION_1, thread_id=custom_thread))

        decision = await detector.on_event(_ev(CallState.RINGING, session_id=SESSION_2, thread_id=None))
        assert decision.is_reconnect
        assert decision.prior_thread_id == custom_thread
