"""
modules/transport/session_manager.py
------------------------------------
Call Session Manager — Pair A (Transport).

Owns:
  - The LiveKit room session lifecycle (joining, track setup, participants).
  - Telephony / SIP bridge integration (or browser-simulated ring).
  - The Call State Finite State Machine (FSM):
      IDLE -> RINGING -> CONNECTED -> DISCONNECTED / COMPLETED
  - Ring-window duration tracking and latency estimation.
  - Caller ID matching against interrupted threads (is_reconnect detection).
  - Emission of typed CallStateEvent messages to downstream modules (Pair B: Signal).
  - Mid-call catch-up trigger with audio ducking support (Scenario D / delayed pickup).

Invariant (§ 06 & § 08):
  Maintains architecturally separate tracks for caller audio and private whisper.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set

from modules.transport.audio_ducking import AudioDuckingController
from modules.transport.exceptions import SessionStateError
from modules.transport.whisper_channel import PrivateWhisperChannel
from shared.config import settings
from shared.schemas import CallState, CallStateEvent, TtsRequest

logger = logging.getLogger("continuum.transport.session")


class CallSessionManager:
    """
    Coordinates LiveKit room states, telephony events, and audio routing.
    """

    VALID_TRANSITIONS: Dict[CallState, Set[CallState]] = {
        CallState.IDLE: {CallState.RINGING, CallState.CONNECTED},
        CallState.RINGING: {CallState.CONNECTED, CallState.COMPLETED, CallState.DISCONNECTED},
        CallState.CONNECTED: {CallState.DISCONNECTED, CallState.COMPLETED},
        CallState.DISCONNECTED: {CallState.IDLE, CallState.RINGING},
        CallState.COMPLETED: {CallState.IDLE, CallState.RINGING},
    }

    def __init__(
        self,
        session_id: Optional[str] = None,
        whisper_channel: Optional[PrivateWhisperChannel] = None,
        interrupted_threads_registry: Optional[Dict[str, str]] = None,
        use_mocks: Optional[bool] = None,
    ):
        """
        Args:
            session_id: Optional fixed session ID (defaults to new UUID4).
            whisper_channel: PrivateWhisperChannel instance for audio routing.
            interrupted_threads_registry: Mapping of caller_id -> thread_id for
                                          interrupted threads lookup.
            use_mocks: Flag for mock vs real LiveKit operation.
        """
        self._session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self._current_state = CallState.IDLE
        self._previous_state: Optional[CallState] = None
        self._caller_id: Optional[str] = None
        self._thread_id: Optional[str] = None
        self._is_reconnect = False

        self._ring_start_time: Optional[float] = None
        self._connected_time: Optional[float] = None
        self._estimated_ring_window_s: float = 20.0

        self._use_mocks = use_mocks if use_mocks is not None else settings.use_mocks
        self._whisper_channel = whisper_channel or PrivateWhisperChannel(use_mocks=self._use_mocks)

        # Thread registry for reconnect matching: caller_id -> thread_id
        # Seeds default synthetic contact Z if empty
        self._interrupted_threads = (
            dict(interrupted_threads_registry)
            if interrupted_threads_registry is not None
            else {"+14155550199": "mock-thread-Z-001"}
        )

        # Async subscriber queues for CallStateEvents
        self._subscribers: List[asyncio.Queue[CallStateEvent]] = []
        self._event_history: List[CallStateEvent] = []
        self._lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def current_state(self) -> CallState:
        return self._current_state

    @property
    def previous_state(self) -> Optional[CallState]:
        return self._previous_state

    @property
    def caller_id(self) -> Optional[str]:
        return self._caller_id

    @property
    def thread_id(self) -> Optional[str]:
        return self._thread_id

    @property
    def is_reconnect(self) -> bool:
        return self._is_reconnect

    @property
    def whisper_channel(self) -> PrivateWhisperChannel:
        return self._whisper_channel

    @property
    def estimated_ring_window_seconds(self) -> float:
        return self._estimated_ring_window_s

    @property
    def elapsed_ring_seconds(self) -> Optional[float]:
        if self._ring_start_time is None:
            return None
        end = self._connected_time or time.perf_counter()
        return end - self._ring_start_time

    def register_interrupted_thread(self, caller_id: str, thread_id: str) -> None:
        """Register that a thread for caller_id was interrupted and awaits reconnect."""
        self._interrupted_threads[caller_id] = thread_id
        logger.info("Registered interrupted thread %s for caller %s", thread_id, caller_id)

    def subscribe(self) -> asyncio.Queue[CallStateEvent]:
        """Subscribe to receive CallStateEvents as an async queue."""
        q: asyncio.Queue[CallStateEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[CallStateEvent]) -> None:
        """Unsubscribe an event queue."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    async def transition_to(
        self,
        new_state: CallState,
        caller_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> CallStateEvent:
        """
        Transitions the FSM to a new state and dispatches a CallStateEvent.
        Enforces valid state machine transitions.
        """
        async with self._lock:
            allowed = self.VALID_TRANSITIONS.get(self._current_state, set())
            if new_state not in allowed:
                raise SessionStateError(
                    f"Invalid call state transition from {self._current_state.value} to {new_state.value}. "
                    f"Allowed transitions: {[s.value for s in allowed]}"
                )

            self._previous_state = self._current_state
            self._current_state = new_state

            if caller_id is not None:
                self._caller_id = caller_id

            # Handle state-specific logic
            if new_state == CallState.RINGING:
                self._ring_start_time = time.perf_counter()
                self._connected_time = None
                # Caller Identity Matching: check if caller matches an interrupted thread
                if self._caller_id and self._caller_id in self._interrupted_threads:
                    self._is_reconnect = True
                    self._thread_id = thread_id or self._interrupted_threads[self._caller_id]
                    logger.info(
                        "RECONNECT DETECTED: Caller %s matches interrupted thread %s",
                        self._caller_id,
                        self._thread_id,
                    )
                else:
                    self._is_reconnect = False
                    self._thread_id = thread_id

            elif new_state == CallState.CONNECTED:
                self._connected_time = time.perf_counter()
                if self._previous_state == CallState.IDLE:
                    # Instant connect scenario (no ring window)
                    if self._caller_id and self._caller_id in self._interrupted_threads:
                        self._is_reconnect = True
                        self._thread_id = thread_id or self._interrupted_threads[self._caller_id]
                logger.info(
                    "Call CONNECTED (session=%s, caller=%s, reconnect=%s)",
                    self._session_id,
                    self._caller_id,
                    self._is_reconnect,
                )

            elif new_state in (CallState.COMPLETED, CallState.DISCONNECTED):
                if new_state == CallState.DISCONNECTED:
                    # Abrupt hangup: mark thread as interrupted so reconnect can match it
                    if not self._thread_id:
                        self._thread_id = f"thread-{uuid.uuid4().hex[:8]}"
                    if self._caller_id:
                        self.register_interrupted_thread(self._caller_id, self._thread_id)
                logger.info(
                    "Call ENDED (%s, session=%s)",
                    new_state.value,
                    self._session_id,
                )

            event = CallStateEvent(
                event_id=str(uuid.uuid4()),
                session_id=self._session_id,
                thread_id=self._thread_id,
                state=self._current_state,
                previous_state=self._previous_state,
                caller_id=self._caller_id,
                is_reconnect=self._is_reconnect,
                timestamp=datetime.now(tz=timezone.utc),
            )

            self._event_history.append(event)
            # Dispatch to subscribers
            for sub in list(self._subscribers):
                await sub.put(event)

            return event

    async def deliver_recap(
        self,
        request: TtsRequest,
        enable_audio_ducking: bool = True,
    ) -> Any:
        """
        Deliver a spoken recap via the private whisper channel.

        If the call has already progressed to CONNECTED (or user answered during ring),
        activates audio ducking to lower caller volume and boost recap voice.
        """
        is_connected = (self._current_state == CallState.CONNECTED)
        return await self._whisper_channel.play_recap(
            request=request,
            is_call_connected=is_connected,
            enable_ducking=enable_audio_ducking,
        )

    async def trigger_mid_call_catchup(
        self,
        recap_request_callback: Optional[Callable[[], TtsRequest]] = None,
    ) -> Any:
        """
        Mid-call Catch-Up Action (User feedback requirement):
        When the call is already answered/lifted (or if ring recap did not complete in time),
        the user activates this option to duck caller audio and play recap in their earpiece.

        Raises:
            SessionStateError: If the call is not currently in the CONNECTED state,
                               preventing ducking on a completed or idle call.
        """
        if self._current_state != CallState.CONNECTED:
            raise SessionStateError(
                f"Mid-call catch-up requires CONNECTED state, but current state is "
                f"{self._current_state.value!r}. Activate only while a call is in progress."
            )

        logger.info("Executing mid-call catch-up with audio ducking enabled...")

        # If custom callback provided, get the TtsRequest, else use standard thread request.
        # Supports both sync and async callbacks.
        if recap_request_callback:
            result = recap_request_callback()
            tts_req = await result if asyncio.iscoroutine(result) else result
        else:
            from mocks.mock_brain import make_recap_request
            recap_req = make_recap_request()
            tts_req = TtsRequest(
                request_id=str(uuid.uuid4()),
                session_id=self._session_id,
                thread_id=self._thread_id or "thread-mid-call",
                text=recap_req.summary.headline,
                speaker=settings.rime_default_speaker,
                private_track_id=settings.private_track_id,
                created_at=datetime.now(tz=timezone.utc),
            )

        return await self.deliver_recap(tts_req, enable_audio_ducking=True)

    async def simulate_call_lifecycle(
        self,
        scenario: str = "reconnect",
        caller_id: str = "+14155550199",
        ring_duration_s: float = 3.0,
        connected_duration_s: float = 4.0,
        tts_callback: Optional[Callable[[CallStateEvent], Any]] = None,
    ) -> List[CallStateEvent]:
        """
        Simulates a complete call scenario end-to-end for testing and demos.
        Scenarios: 'normal', 'reconnect', 'instant_connect'
        """
        events: List[CallStateEvent] = []
        self._caller_id = caller_id

        if scenario in ("normal", "reconnect"):
            if scenario == "reconnect":
                self.register_interrupted_thread(caller_id, f"thread-{uuid.uuid4().hex[:6]}")

            e_ring = await self.transition_to(CallState.RINGING, caller_id=caller_id)
            events.append(e_ring)

            if tts_callback:
                res = tts_callback(e_ring)
                if asyncio.iscoroutine(res):
                    await res

            await asyncio.sleep(ring_duration_s)

            e_conn = await self.transition_to(CallState.CONNECTED)
            events.append(e_conn)
            await asyncio.sleep(connected_duration_s)

            e_comp = await self.transition_to(CallState.COMPLETED)
            events.append(e_comp)

        elif scenario == "instant_connect":
            self.register_interrupted_thread(caller_id, f"thread-{uuid.uuid4().hex[:6]}")
            e_conn = await self.transition_to(CallState.CONNECTED, caller_id=caller_id)
            events.append(e_conn)

            if tts_callback:
                res = tts_callback(e_conn)
                if asyncio.iscoroutine(res):
                    await res

            await asyncio.sleep(connected_duration_s)
            e_comp = await self.transition_to(CallState.COMPLETED)
            events.append(e_comp)

        else:
            raise ValueError(
                f"Unknown call scenario: {scenario!r}. "
                f"Valid scenarios are: 'normal', 'reconnect', 'instant_connect'."
            )

        return events
