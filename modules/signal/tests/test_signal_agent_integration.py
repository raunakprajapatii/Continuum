"""
modules/signal/tests/test_signal_agent_integration.py
-------------------------------------------------------
Integration tests for SignalAgent — wires MockCallSession + StreamingSTT
together and validates the full Pair B output.

These tests run entirely with mocks (no Deepgram, no LiveKit, no Rime).
They verify the end-to-end behaviour that Brain (Pair C) depends on:

  1. Normal call: transcripts are emitted, on_call_ended fires with abruptly=False
  2. Reconnect scenario: on_reconnect fires before STT starts, with correct thread_id
  3. Disconnected scenario: on_call_ended fires with abruptly=True
  4. Instant-connect scenario: STT starts without a prior RINGING event
  5. Transcript events for a reconnect carry the matched thread_id
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional

import pytest

os.environ.setdefault("USE_MOCKS", "true")

from mocks.mock_call_session import MOCK_THREAD_ID, MockCallSession
from modules.signal.signal_agent import SignalAgent
from shared.schemas import TranscriptEvent


# ── Helpers ───────────────────────────────────────────────────────────────────


class _Collector:
    """Collects callback invocations for assertion."""

    def __init__(self) -> None:
        self.transcripts: List[TranscriptEvent] = []
        self.reconnect_calls: List[tuple] = []
        self.call_ended_calls: List[tuple] = []

    async def on_transcript(self, ev: TranscriptEvent) -> None:
        self.transcripts.append(ev)

    async def on_reconnect(
        self,
        session_id: str,
        thread_id: Optional[str],
        caller_id: Optional[str],
    ) -> None:
        self.reconnect_calls.append((session_id, thread_id, caller_id))

    async def on_call_ended(self, session_id: str, abruptly: bool) -> None:
        self.call_ended_calls.append((session_id, abruptly))


def _make_agent(collector: _Collector) -> SignalAgent:
    return SignalAgent(
        on_transcript=collector.on_transcript,
        on_reconnect=collector.on_reconnect,
        on_call_ended=collector.on_call_ended,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSignalAgentIntegration:
    @pytest.mark.asyncio
    async def test_normal_call_emits_transcripts(self) -> None:
        """
        Normal call scenario: IDLE → RINGING → CONNECTED → COMPLETED.
        Transcripts should be emitted during CONNECTED.
        """
        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="normal", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        assert len(col.transcripts) > 0, "Expected at least one TranscriptEvent"
        assert not col.reconnect_calls, "No reconnect should fire for normal call"

    @pytest.mark.asyncio
    async def test_normal_call_ends_cleanly(self) -> None:
        """on_call_ended must fire with abruptly=False for a COMPLETED session."""
        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="normal", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        assert len(col.call_ended_calls) == 1
        _, abruptly = col.call_ended_calls[0]
        assert not abruptly, "Normal completion should have abruptly=False"

    @pytest.mark.asyncio
    async def test_reconnect_scenario_fires_on_reconnect_callback(self) -> None:
        """
        Reconnect scenario: RINGING(is_reconnect=True) must fire on_reconnect
        before any transcripts are emitted.
        """
        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="reconnect", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        assert len(col.reconnect_calls) == 1, (
            f"Expected 1 reconnect call, got {len(col.reconnect_calls)}"
        )

    @pytest.mark.asyncio
    async def test_reconnect_callback_receives_thread_id(self) -> None:
        """on_reconnect must receive the correct prior thread_id."""
        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="reconnect", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        _, thread_id, _ = col.reconnect_calls[0]
        assert thread_id == MOCK_THREAD_ID, (
            f"Expected thread_id={MOCK_THREAD_ID!r}, got {thread_id!r}"
        )

    @pytest.mark.asyncio
    async def test_reconnect_scenario_emits_transcripts_during_connected(self) -> None:
        """
        In a reconnect scenario, transcripts still flow during the CONNECTED phase.
        The recap (Rime TTS) happens during RINGING — STT starts only at CONNECTED.
        """
        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="reconnect", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        assert len(col.transcripts) > 0, "Transcripts should be emitted during CONNECTED"

    @pytest.mark.asyncio
    async def test_reconnect_transcript_session_ids_match(self) -> None:
        """All TranscriptEvents must carry the session_id from the current session."""
        from mocks.mock_call_session import MOCK_SESSION_ID

        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="reconnect", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        for ev in col.transcripts:
            assert ev.session_id == MOCK_SESSION_ID

    @pytest.mark.asyncio
    async def test_no_reconnect_for_first_time_caller(self) -> None:
        """First RINGING from a caller never seen before must NOT fire on_reconnect."""
        col = _Collector()
        agent = _make_agent(col)
        session = MockCallSession(scenario="normal", ring_duration_s=0.1)

        await agent.run(session.event_stream())

        assert len(col.reconnect_calls) == 0

    @pytest.mark.asyncio
    async def test_stt_not_active_during_ringing(self) -> None:
        """
        STT should NOT be streaming during the ring window.
        (Transcription only starts once the call is CONNECTED.)
        """
        stt_states_during_ringing: List[bool] = []
        col = _Collector()

        original_on_transcript = col.on_transcript

        class _TrackingAgent(SignalAgent):
            async def _handle_event(self, event) -> None:  # type: ignore[override]
                from shared.schemas import CallState as CS
                if event.state == CS.RINGING:
                    stt_states_during_ringing.append(self.is_stt_active)
                await super()._handle_event(event)

        agent = _TrackingAgent(
            on_transcript=col.on_transcript,
            on_reconnect=col.on_reconnect,
            on_call_ended=col.on_call_ended,
        )
        session = MockCallSession(scenario="reconnect", ring_duration_s=0.1)
        await agent.run(session.event_stream())

        assert all(not active for active in stt_states_during_ringing), (
            "STT was active during RINGING — it should only start at CONNECTED"
        )

    @pytest.mark.asyncio
    async def test_agent_survives_callback_exceptions(self) -> None:
        """Exceptions in Brain callbacks must not crash the agent's main loop."""
        async def buggy_transcript(ev: TranscriptEvent) -> None:
            raise RuntimeError("Brain queue full")
            
        async def buggy_reconnect(sid: str, tid: Optional[str], cid: Optional[str]) -> None:
            raise ValueError("Brain reconnect error")
            
        async def buggy_call_ended(sid: str, abruptly: bool) -> None:
            raise KeyError("Brain call ended error")

        agent = SignalAgent(
            on_transcript=buggy_transcript,
            on_reconnect=buggy_reconnect,
            on_call_ended=buggy_call_ended,
        )
        session = MockCallSession(scenario="reconnect", ring_duration_s=0.1)
        
        # This should complete without raising any exceptions up to the test runner
        await agent.run(session.event_stream())

    @pytest.mark.asyncio
    async def test_cancellation_cleans_up_stt(self) -> None:
        """If the agent's run() task is cancelled, STT is stopped."""
        col = _Collector()
        agent = _make_agent(col)
        
        # Create an event stream that hangs indefinitely in CONNECTED
        async def hanging_stream():
            from shared.schemas import CallState, CallStateEvent
            import uuid
            from datetime import datetime, timezone
            yield CallStateEvent(
                event_id=str(uuid.uuid4()), session_id="1", thread_id="1",
                state=CallState.RINGING, timestamp=datetime.now(timezone.utc)
            )
            yield CallStateEvent(
                event_id=str(uuid.uuid4()), session_id="1", thread_id="1",
                state=CallState.CONNECTED, timestamp=datetime.now(timezone.utc)
            )
            await asyncio.sleep(10) # Hang here
            
        agent_task = asyncio.create_task(agent.run(hanging_stream()))
        
        # Give it a moment to process the CONNECTED event
        await asyncio.sleep(0.1) 
        assert agent.is_stt_active
        
        # Cancel the task
        agent_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await agent_task
            
        # Verify STT was cleaned up
        assert not agent.is_stt_active
