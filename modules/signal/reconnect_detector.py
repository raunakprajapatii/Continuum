"""
modules/signal/reconnect_detector.py
--------------------------------------
Disconnect / Reconnect Detector — Pair B (Signal).

Implements the call-state FSM that:
  1. Tracks transitions: IDLE → RINGING → CONNECTED → DISCONNECTED/COMPLETED.
  2. Detects abrupt disconnects (state=DISCONNECTED with no COMPLETED transition).
  3. On the next RINGING event from the same caller, marks ``is_reconnect=True``
     and resolves the thread_id from the Caller Matcher.
  4. Emits ``ReconnectDecision`` objects that the Signal Agent acts on.

State machine
-------------

        IDLE
         │
    (RINGING received)
         │
         ▼
      RINGING  ──(CONNECTED)──► CONNECTED
                                    │
                        ┌───────────┴──────────┐
                   (DISCONNECTED)         (COMPLETED)
                        │                      │
                        ▼                      ▼
                  DISCONNECTED             COMPLETED
                 (mark interrupted)    (normal close — 
                        │              no recap next time)
                        │
             (next RINGING same caller)
                        │
                        ▼
              RINGING + is_reconnect=True ──► ReconnectDecision emitted

The FSM is per-session; a new session resets the internal ``_current_state``.
The CallerMatcher persists across sessions to support the reconnect match.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from shared.schemas import CallState, CallStateEvent

from .caller_matcher import CallerMatcher

logger = logging.getLogger(__name__)


# ── Decision output type ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReconnectDecision:
    """
    The outcome of processing a single ``CallStateEvent`` through the FSM.

    Signal Agent inspects this after every event to decide what to do next.
    """

    event: CallStateEvent
    """The original event that triggered this decision."""

    is_reconnect: bool = False
    """
    True when a RINGING event was matched to a prior interrupted thread
    for the same caller. Triggers the pre-answer recap pipeline.
    """

    prior_thread_id: Optional[str] = None
    """
    Thread ID of the interrupted thread, if ``is_reconnect=True``.
    Forwarded to Brain so it can hydrate the correct ThreadSummary.
    """

    should_start_stt: bool = False
    """True when the agent should begin streaming STT (i.e. CONNECTED state)."""

    should_stop_stt: bool = False
    """True when the agent should halt STT streaming (call ended)."""

    call_ended_abruptly: bool = False
    """True when DISCONNECTED with no closing turn — marks caller as interrupted."""


# ── FSM ──────────────────────────────────────────────────────────────────────


class ReconnectDetector:
    """
    Processes ``CallStateEvent`` objects and emits ``ReconnectDecision`` results.

    One instance should be shared across the lifetime of the Signal Agent process.
    It manages both the per-session state and the cross-session CallerMatcher index.

    Usage::

        detector = ReconnectDetector()

        async for event in call_session.event_stream():
            decision = await detector.on_event(event)
            if decision.is_reconnect:
                # trigger recap pipeline for decision.prior_thread_id
                ...
            if decision.should_start_stt:
                # start streaming STT
                ...
    """

    def __init__(self, caller_matcher: Optional[CallerMatcher] = None) -> None:
        self._matcher = caller_matcher or CallerMatcher()
        self._current_state: Optional[CallState] = None
        self._session_id: Optional[str] = None
        # Flag: did the current session include a CONNECTED → COMPLETED transition
        # (i.e. a clean close)?
        self._session_closed_cleanly: bool = False

    @property
    def caller_matcher(self) -> CallerMatcher:
        """Expose the CallerMatcher so tests and the agent can inspect it."""
        return self._matcher

    async def on_event(self, event: CallStateEvent) -> ReconnectDecision:
        """
        Process one ``CallStateEvent`` and return a ``ReconnectDecision``.

        This is the single entry-point for the FSM. Call it for every event
        in order — do NOT skip events.

        Args:
            event: The incoming state-change event from Transport.

        Returns:
            A ``ReconnectDecision`` describing what the Signal Agent should do.
        """
        # ── Track the event in the caller index ──────────────────────────────
        await self._matcher.record_event(event)

        # ── New session detection ─────────────────────────────────────────────
        if event.session_id != self._session_id:
            logger.info(
                "ReconnectDetector: new session %s (was %s)",
                event.session_id,
                self._session_id,
            )
            self._session_id = event.session_id
            self._session_closed_cleanly = False

        self._current_state = event.state

        # ── Route to state handler ─────────────────────────────────────────────
        if event.state == CallState.IDLE:
            return self._handle_idle(event)
        elif event.state == CallState.RINGING:
            return await self._handle_ringing(event)
        elif event.state == CallState.CONNECTED:
            return self._handle_connected(event)
        elif event.state == CallState.DISCONNECTED:
            return await self._handle_disconnected(event)
        elif event.state == CallState.COMPLETED:
            return self._handle_completed(event)
        else:
            # Unknown state — pass through without action
            logger.warning("ReconnectDetector: unknown state %r", event.state)
            return ReconnectDecision(event=event)

    # ── State handlers ────────────────────────────────────────────────────────

    def _handle_idle(self, event: CallStateEvent) -> ReconnectDecision:
        """IDLE: reset per-session tracking. No action required."""
        self._session_closed_cleanly = False
        logger.debug("ReconnectDetector: → IDLE")
        return ReconnectDecision(event=event)

    async def _handle_ringing(self, event: CallStateEvent) -> ReconnectDecision:
        """
        RINGING: check if this is a reconnect.

        A reconnect is detected when:
          - We have a prior entry for this caller_id, AND
          - That entry is marked as ``is_interrupted=True``

        Note: Transport may already have set ``event.is_reconnect=True`` based
        on its own SIP signalling. We validate and enrich that signal here.
        """
        entry = await self._matcher.lookup(event.caller_id)

        is_reconnect = False
        prior_thread_id: Optional[str] = None

        if entry is not None and entry.is_interrupted:
            is_reconnect = True
            prior_thread_id = entry.thread_id or event.thread_id
            logger.info(
                "ReconnectDetector: RECONNECT detected — caller=%s thread_id=%s",
                event.caller_id,
                prior_thread_id,
            )
            # Clear the interrupted flag immediately to avoid triggering again
            # if the user misses this call and Z calls a third time.
            await self._matcher.clear_interrupted(event.caller_id)
        elif event.is_reconnect:
            # Transport already flagged it — trust it, use thread_id from event.
            is_reconnect = True
            prior_thread_id = event.thread_id
            logger.info(
                "ReconnectDetector: RECONNECT (Transport-flagged) — caller=%s thread_id=%s",
                event.caller_id,
                prior_thread_id,
            )

        return ReconnectDecision(
            event=event,
            is_reconnect=is_reconnect,
            prior_thread_id=prior_thread_id,
        )

    def _handle_connected(self, event: CallStateEvent) -> ReconnectDecision:
        """CONNECTED: signal agent should start streaming STT."""
        logger.info(
            "ReconnectDetector: -> CONNECTED (session=%s)", event.session_id
        )
        return ReconnectDecision(event=event, should_start_stt=True)

    async def _handle_disconnected(self, event: CallStateEvent) -> ReconnectDecision:
        """
        DISCONNECTED: abrupt drop.

        Mark the caller as interrupted so the next RINGING from the same
        number triggers the reconnect path.
        """
        logger.warning(
            "ReconnectDetector: DISCONNECTED (abrupt) -- caller=%s session=%s",
            event.caller_id,
            event.session_id,
        )
        await self._matcher.mark_interrupted(event.caller_id)
        return ReconnectDecision(
            event=event,
            should_stop_stt=True,
            call_ended_abruptly=True,
        )

    def _handle_completed(self, event: CallStateEvent) -> ReconnectDecision:
        """
        COMPLETED: clean close.

        Do NOT mark as interrupted. Next call from same number is a fresh
        thread (or a brief "last touchpoint" recap, per Scenario A).
        """
        logger.info(
            "ReconnectDetector: -> COMPLETED (clean) -- caller=%s session=%s",
            event.caller_id,
            event.session_id,
        )
        self._session_closed_cleanly = True
        return ReconnectDecision(event=event, should_stop_stt=True)
