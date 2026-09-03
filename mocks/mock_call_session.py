"""
mocks/mock_call_session.py
--------------------------
Pair A (Transport) mock — used by Pair B (Signal) during development.

Emits a scripted sequence of CallStateEvents without requiring a real LiveKit
room or SIP trunk. Toggle with USE_MOCKS=true in your .env.

Usage:
    from mocks.mock_call_session import MockCallSession

    session = MockCallSession(scenario="reconnect")
    async for event in session.event_stream():
        print(event)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

from shared.schemas import CallState, CallStateEvent

# Stable IDs used across the mock so events correlate correctly
MOCK_SESSION_ID = "mock-session-001"
MOCK_THREAD_ID = "mock-thread-Z-001"
MOCK_CALLER_ID = "+14155550199"  # Z's number (E.164 synthetic)

Scenario = Literal["normal", "reconnect", "instant_connect"]


def _event(
    state: CallState,
    previous: CallState | None = None,
    is_reconnect: bool = False,
) -> CallStateEvent:
    return CallStateEvent(
        event_id=str(uuid.uuid4()),
        session_id=MOCK_SESSION_ID,
        thread_id=MOCK_THREAD_ID if state != CallState.IDLE else None,
        state=state,
        previous_state=previous,
        caller_id=MOCK_CALLER_ID if state != CallState.IDLE else None,
        is_reconnect=is_reconnect,
        timestamp=datetime.now(tz=timezone.utc),
    )


class MockCallSession:
    """
    Emits canned CallStateEvent sequences for local development.

    Scenarios
    ---------
    normal        — IDLE → RINGING → CONNECTED → COMPLETED
    reconnect     — IDLE → RINGING(is_reconnect=True) → CONNECTED → COMPLETED
                    (simulates Scenario B/C from the blueprint)
    instant_connect — IDLE → CONNECTED directly (no ring window / fallback scenario)
    """

    def __init__(self, scenario: Scenario = "reconnect", ring_duration_s: float = 5.0):
        self.scenario = scenario
        self.ring_duration_s = ring_duration_s

    async def event_stream(self) -> AsyncIterator[CallStateEvent]:
        if self.scenario == "normal":
            yield _event(CallState.RINGING, CallState.IDLE)
            await asyncio.sleep(self.ring_duration_s)
            yield _event(CallState.CONNECTED, CallState.RINGING)
            await asyncio.sleep(8.0)
            yield _event(CallState.COMPLETED, CallState.CONNECTED)

        elif self.scenario == "reconnect":
            # Simulate Z calling back after a previous interrupted thread
            yield _event(CallState.RINGING, CallState.IDLE, is_reconnect=True)
            await asyncio.sleep(self.ring_duration_s)
            yield _event(CallState.CONNECTED, CallState.RINGING)
            await asyncio.sleep(10.0)
            yield _event(CallState.COMPLETED, CallState.CONNECTED)

        elif self.scenario == "instant_connect":
            # No ring window — fallback whisper scenario
            yield _event(CallState.CONNECTED, CallState.IDLE, is_reconnect=True)
            await asyncio.sleep(12.0)
            yield _event(CallState.COMPLETED, CallState.CONNECTED)

        else:
            raise ValueError(f"Unknown scenario: {self.scenario!r}")
