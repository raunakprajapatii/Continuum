"""
mocks/mock_stt.py
-----------------
Pair B (Signal) mock — used by Pair C (Brain) during development.

Replays a scripted conversation transcript as a stream of TranscriptEvents
without requiring a live STT provider or audio input.

Usage:
    from mocks.mock_stt import MockSTT

    stt = MockSTT()
    async for event in stt.transcript_stream():
        print(event)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from shared.schemas import Speaker, TranscriptEvent

# Reuse the stable IDs from the call-session mock
from .mock_call_session import MOCK_SESSION_ID, MOCK_THREAD_ID

# ── Scripted conversation (Scenario C: reconnect next day, stale price) ────────
# Mirrors blueprint § 09, Scenario C. Price discussed is $400; mock API returns $420.
SCRIPTED_TURNS: list[tuple[Speaker, str, float]] = [
    # (speaker, text, pause_before_next_seconds)
    (Speaker.CALLER, "Hey, so I wanted to follow up on the Q3 numbers.", 1.5),
    (Speaker.USER, "Sure, yeah — the unit price we discussed was four hundred dollars.", 1.2),
    (Speaker.CALLER, "Right, and you were going to check with finance on volume discounts?", 1.0),
    (Speaker.USER, "Yes, I'll loop them in today and get back to you.", 1.5),
    (Speaker.CALLER, "Perfect. Also, ticket XYZ-", 0.3),
    # Abrupt disconnect mid-sentence
]


class MockSTT:
    """
    Replays SCRIPTED_TURNS as a stream of is_final=True TranscriptEvents.

    Brain should persist these to the Thread Memory Store. The last turn
    is intentionally cut off to simulate an interrupted disconnect
    (matching mock_call_session scenario='reconnect').
    """

    def __init__(self, include_partial: bool = False):
        """
        Args:
            include_partial: If True, emit an interim (is_final=False) chunk
                             before each final chunk, to test Brain's filtering.
        """
        self.include_partial = include_partial
        self._start_ms: int = 0
        self._elapsed_ms: int = 0

    def _make_event(
        self,
        speaker: Speaker,
        text: str,
        is_final: bool = True,
        duration_ms: int = 1000,
    ) -> TranscriptEvent:
        event = TranscriptEvent(
            event_id=str(uuid.uuid4()),
            session_id=MOCK_SESSION_ID,
            thread_id=MOCK_THREAD_ID,
            speaker=speaker,
            text=text,
            is_final=is_final,
            confidence=0.97 if is_final else 0.6,
            start_ms=self._elapsed_ms,
            end_ms=self._elapsed_ms + duration_ms if is_final else None,
            timestamp=datetime.now(tz=timezone.utc),
        )
        if is_final:
            self._elapsed_ms += duration_ms
        return event

    async def transcript_stream(self) -> AsyncIterator[TranscriptEvent]:
        self._elapsed_ms = 0

        for i, (speaker, text, pause) in enumerate(SCRIPTED_TURNS):
            # Optionally emit a partial first
            if self.include_partial:
                partial_text = text[: max(1, len(text) // 2)] + "..."
                yield self._make_event(speaker, partial_text, is_final=False)
                await asyncio.sleep(0.1)

            # Final chunk
            duration_ms = int(len(text) * 60)  # rough ~60ms per character
            yield self._make_event(speaker, text, is_final=True, duration_ms=duration_ms)

            # Last turn is mid-sentence (abrupt disconnect) — no pause after
            if i < len(SCRIPTED_TURNS) - 1:
                await asyncio.sleep(pause)
