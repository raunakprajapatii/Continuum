"""
modules/signal/signal_agent.py
--------------------------------
Signal Agent — Pair B orchestrator.

Wires together the three Signal components:
  - ``ReconnectDetector`` — FSM that tracks call state and identifies reconnects
  - ``StreamingSTT``      — live/mock transcription engine
  - Brain callback        — where TranscriptEvents are forwarded

Lifecycle
---------
The agent is designed to run as a long-lived coroutine:

    agent = SignalAgent(on_transcript=brain_queue_put)
    await agent.run(call_event_stream)

It processes one ``CallStateEvent`` at a time in sequence:

  RINGING (reconnect=True)
    └─► emit reconnect notification to the recap pipeline (via on_reconnect cb)
        (STT is not started yet — ring window belongs to recap, not transcription)

  CONNECTED
    └─► create a new StreamingSTT and start streaming in a background task

  DISCONNECTED
    └─► stop STT (abrupt), mark caller interrupted, notify Brain call ended abruptly

  COMPLETED
    └─► stop STT (clean close), notify Brain call ended normally

Multiple concurrent calls are explicitly NOT supported in this implementation —
the hackathon scope is a single user session. If a second RINGING arrives while
a CONNECTED session is active, the agent logs a warning and carries on.

Callbacks
---------
All callbacks are async so they can await Brain queue operations naturally:

  on_transcript(TranscriptEvent)
      Called for every is_final=True utterance chunk during a CONNECTED session.
      Wire this to Brain's ingest endpoint or async queue.

  on_reconnect(session_id, thread_id, caller_id)
      Called when a RINGING reconnect is detected (before CONNECTED).
      Wire this to the recap pipeline — Brain + Voice & Facts need to know.

  on_call_ended(session_id, abruptly: bool)
      Called when the call session closes (DISCONNECTED or COMPLETED).
      Brain uses this to flush any in-flight transcript buffer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Awaitable, Callable, Optional

from shared.schemas import CallState, CallStateEvent, TranscriptEvent

from .reconnect_detector import ReconnectDecision, ReconnectDetector
from .stt_streamer import StreamingSTT

logger = logging.getLogger(__name__)

# ── Callback type aliases ─────────────────────────────────────────────────────

OnTranscriptCb = Callable[[TranscriptEvent], Awaitable[None]]
OnReconnectCb = Callable[[str, Optional[str], Optional[str]], Awaitable[None]]
OnCallEndedCb = Callable[[str, bool], Awaitable[None]]


# ── Agent ─────────────────────────────────────────────────────────────────────


class SignalAgent:
    """
    Pair B orchestrator — processes CallStateEvents and drives STT streaming.

    Args:
        on_transcript:
            Async callback invoked for each final TranscriptEvent emitted
            during a CONNECTED session. Required.

        on_reconnect:
            Async callback invoked when a RINGING reconnect is detected.
            Signature: ``(session_id: str, thread_id: Optional[str],
                          caller_id: Optional[str]) -> None``.
            Optional — if None, reconnect decisions are only logged.

        on_call_ended:
            Async callback invoked when a call session ends.
            Signature: ``(session_id: str, abruptly: bool) -> None``.
            Optional — if None, call-end events are only logged.

        include_partial_transcripts:
            If True, interim STT chunks are forwarded to ``on_transcript``
            as well as final ones. Default False — Brain only wants finals.

    Usage::

        async def store_transcript(event: TranscriptEvent) -> None:
            await brain_queue.put(event)

        agent = SignalAgent(on_transcript=store_transcript)

        # Feed it a live or mock CallStateEvent stream
        from mocks.mock_call_session import MockCallSession
        session = MockCallSession(scenario="reconnect")
        await agent.run(session.event_stream())
    """

    def __init__(
        self,
        on_transcript: OnTranscriptCb,
        on_reconnect: Optional[OnReconnectCb] = None,
        on_call_ended: Optional[OnCallEndedCb] = None,
        include_partial_transcripts: bool = False,
    ) -> None:
        self._on_transcript = on_transcript
        self._on_reconnect = on_reconnect
        self._on_call_ended = on_call_ended
        self._include_partial = include_partial_transcripts

        self._detector = ReconnectDetector()
        self._stt: Optional[StreamingSTT] = None
        self._stt_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._current_session_id: Optional[str] = None

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(
        self,
        event_stream: AsyncIterator[CallStateEvent],
    ) -> None:
        """
        Process a stream of ``CallStateEvent`` objects until the stream ends.

        This coroutine blocks until the event stream is exhausted (i.e. the
        call session is complete). Runs cleanly even if the stream raises.
        """
        logger.info("SignalAgent: starting — awaiting CallStateEvents")
        try:
            async for event in event_stream:
                await self._handle_event(event)
        except asyncio.CancelledError:
            logger.info("SignalAgent.run(): cancelled — cleaning up STT.")
            await self._stop_stt()
            raise
        except Exception:
            logger.exception("SignalAgent.run(): unhandled error.")
            await self._stop_stt()
            raise
        finally:
            # Ensure STT is always stopped when the event stream ends
            await self._stop_stt()
            logger.info("SignalAgent: event stream exhausted — agent stopped.")

    # ── Event dispatch ────────────────────────────────────────────────────────

    async def _handle_event(self, event: CallStateEvent) -> None:
        """Route a single CallStateEvent through the detector and act on it."""
        logger.debug(
            "SignalAgent: event state=%s session=%s caller=%s is_reconnect=%s",
            event.state,
            event.session_id,
            event.caller_id,
            event.is_reconnect,
        )

        decision: ReconnectDecision = await self._detector.on_event(event)
        self._current_session_id = event.session_id

        if decision.is_reconnect:
            await self._on_reconnect_detected(decision)

        if decision.should_start_stt:
            await self._start_stt(event)

        if decision.should_stop_stt:
            await self._stop_stt()
            await self._notify_call_ended(event, abruptly=decision.call_ended_abruptly)

    # ── Reconnect handling ────────────────────────────────────────────────────

    async def _on_reconnect_detected(self, decision: ReconnectDecision) -> None:
        """
        Handle a confirmed reconnect during RINGING.

        Notifies the recap pipeline so Brain + Voice & Facts can prepare the
        pre-answer whisper before the user picks up.
        """
        event = decision.event
        logger.info(
            "SignalAgent: RECONNECT — session=%s thread=%s caller=%s",
            event.session_id,
            decision.prior_thread_id,
            event.caller_id,
        )
        if self._on_reconnect is not None:
            try:
                await self._on_reconnect(
                    event.session_id,
                    decision.prior_thread_id,
                    event.caller_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "SignalAgent: on_reconnect callback raised (session=%s).",
                    event.session_id,
                )

    # ── STT lifecycle ─────────────────────────────────────────────────────────

    async def _start_stt(self, event: CallStateEvent) -> None:
        """
        Start a new StreamingSTT task for the current CONNECTED session.

        If STT is somehow still running from a previous session (shouldn't
        happen in normal flow), it is stopped first.
        """
        if self._stt_task is not None and not self._stt_task.done():
            logger.warning(
                "SignalAgent: STT already running when CONNECTED received — stopping old stream."
            )
            await self._stop_stt()

        logger.info(
            "SignalAgent: starting STT — session=%s thread=%s",
            event.session_id,
            event.thread_id,
        )
        self._stt = StreamingSTT(
            session_id=event.session_id,
            thread_id=event.thread_id,
            on_transcript=self._on_transcript,
            include_partial=self._include_partial,
        )
        self._stt_task = asyncio.create_task(
            self._stt.run(),
            name=f"stt-{event.session_id}",
        )

        # Attach a done-callback to log any unexpected STT crash
        def _on_stt_done(task: asyncio.Task) -> None:  # type: ignore[type-arg]
            exc = task.exception() if not task.cancelled() else None
            if exc is not None:
                logger.error(
                    "SignalAgent: STT task crashed — session=%s error=%r",
                    event.session_id,
                    exc,
                )

        self._stt_task.add_done_callback(_on_stt_done)

    async def _stop_stt(self) -> None:
        """
        Stop the current STT task gracefully.

        Idempotent — safe to call even when no STT task is running.
        """
        if self._stt is not None:
            await self._stt.stop()
            self._stt = None

        if self._stt_task is not None and not self._stt_task.done():
            self._stt_task.cancel()
            try:
                await asyncio.wait_for(self._stt_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._stt_task = None

    # ── Call-end notification ─────────────────────────────────────────────────

    async def _notify_call_ended(
        self,
        event: CallStateEvent,
        abruptly: bool,
    ) -> None:
        """Invoke the on_call_ended callback so Brain can flush its buffer."""
        logger.info(
            "SignalAgent: call ended — session=%s abruptly=%s",
            event.session_id,
            abruptly,
        )
        if self._on_call_ended is not None:
            try:
                await self._on_call_ended(event.session_id, abruptly)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "SignalAgent: on_call_ended callback raised (session=%s).",
                    event.session_id,
                )

    # ── Diagnostics ───────────────────────────────────────────────────────────

    @property
    def is_stt_active(self) -> bool:
        """True when STT is currently streaming."""
        return self._stt_task is not None and not self._stt_task.done()

    @property
    def current_session_id(self) -> Optional[str]:
        """The session_id of the most recently seen CallStateEvent."""
        return self._current_session_id
