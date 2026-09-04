"""
modules/brain/service.py
------------------------
Brain Service orchestrator for Pair C (Brain).

Connects:
  - Streaming TranscriptEvent buffering
  - ThreadMemoryStore (SQLite)
  - ConversationExtractor (Gemini / Heuristic)
  - Recap Generator (RecapRequest dispatcher)

Robustness enhancements:
  - Error isolation: exceptions in event handlers are caught and logged so
    the LiveKit / Telephony worker loop never crashes.
  - Handles missing / partial call event attributes safely.
  - Thread safety and safe turn clearing.
"""

from __future__ import annotations

import logging
from typing import Optional

from shared.schemas import (
    CallState,
    CallStateEvent,
    RecapRequest,
    ThreadSummary,
    TranscriptEvent,
)

from .extractor import ConversationExtractor
from .recap import build_recap_request
from .store import ThreadMemoryStore

logger = logging.getLogger(__name__)


class BrainService:
    """
    Central service for Brain module operations with built-in error isolation.
    """

    def __init__(
        self,
        store: Optional[ThreadMemoryStore] = None,
        extractor: Optional[ConversationExtractor] = None,
    ) -> None:
        self.store = store or ThreadMemoryStore()
        self.extractor = extractor or ConversationExtractor()

    async def init(self) -> None:
        """Initialize database store."""
        await self.store.init_db()

    async def on_transcript_event(self, event: TranscriptEvent) -> None:
        """
        Handle an incoming transcript chunk from Signal (Pair B).
        Only commit final chunks with non-empty text to the session buffer.
        """
        try:
            if not event.is_final or not event.text or not event.text.strip():
                return  # Skip interim or whitespace-only chunks

            await self.store.append_turn(event.session_id, event)
        except Exception as e:
            logger.error("BrainService error handling transcript event %s: %s", getattr(event, 'event_id', 'unknown'), e)

    async def on_call_ringing(
        self, event: CallStateEvent, estimated_ring_window_seconds: float = 20.0
    ) -> Optional[RecapRequest]:
        """
        Handle a RINGING call state event.
        If is_reconnect=True, generate a pre-answer RecapRequest before the user answers.
        """
        try:
            if event.state != CallState.RINGING or not event.is_reconnect or not event.caller_id:
                return None

            # Look up existing thread summary for this caller
            summary = await self.store.get_summary_by_caller(event.caller_id)
            if not summary:
                logger.info(
                    "Reconnect indicated for caller %s but no prior summary found in store",
                    event.caller_id,
                )
                return None

            ring_sec = getattr(event, "estimated_ring_window_seconds", None) or estimated_ring_window_seconds

            recap_req = build_recap_request(
                summary=summary,
                session_id=event.session_id,
                estimated_ring_window_seconds=ring_sec,
            )
            return recap_req
        except Exception as e:
            logger.error("BrainService error on RINGING event %s: %s", getattr(event, 'event_id', 'unknown'), e)
            return None

    async def on_call_ended(
        self, event: CallStateEvent
    ) -> Optional[ThreadSummary]:
        """
        Handle a DISCONNECTED or COMPLETED call event.
        Extracts structured memory from buffered turns, updates ThreadSummary,
        and saves it to ThreadMemoryStore.
        """
        try:
            if event.state not in (CallState.DISCONNECTED, CallState.COMPLETED) or not event.caller_id:
                return None

            # Retrieve all recorded turns for this session
            turns = await self.store.get_session_turns(event.session_id, final_only=True)
            if not turns:
                logger.info(
                    "Call ended for session %s with zero recorded turns; skipping extraction",
                    event.session_id,
                )
                return None

            is_interrupted = event.state == CallState.DISCONNECTED

            # Fetch prior summary for caller if exists
            prior = await self.store.get_summary_by_caller(event.caller_id)

            caller_name = getattr(event, "caller_name", None) or (prior.caller_name if prior else None)

            # Extract updated summary
            new_summary = await self.extractor.extract(
                turns=turns,
                caller_id=event.caller_id,
                caller_name=caller_name,
                thread_id=event.thread_id or (prior.thread_id if prior else f"thread_{event.caller_id}"),
                is_interrupted=is_interrupted,
                prior_summary=prior,
            )

            # Persist to database
            await self.store.save_summary(new_summary)

            # Clean up session turn buffer
            await self.store.clear_session_turns(event.session_id)

            return new_summary
        except Exception as e:
            logger.error("BrainService error on call ended event %s: %s", getattr(event, 'event_id', 'unknown'), e)
            return None
