"""
modules/signal/tests/test_stt_mock.py
---------------------------------------
Unit tests for StreamingSTT (mock path only — no external services needed).

Tests cover:
  - MockSTT produces the correct number of final TranscriptEvents
  - Speaker tags (USER / CALLER) are correctly assigned
  - All events have is_final=True when include_partial=False
  - session_id and thread_id are correctly threaded through
  - Partial chunks are emitted when include_partial=True
  - stop() halts the stream mid-flight
"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional

import pytest

# Force mocks for all tests in this module
os.environ.setdefault("USE_MOCKS", "true")

from modules.signal.stt_streamer import StreamingSTT
from shared.schemas import Speaker, TranscriptEvent

# The scripted turns from the mock — we import to know exactly what to expect
from mocks.mock_stt import SCRIPTED_TURNS


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _collect_events(stt: StreamingSTT) -> List[TranscriptEvent]:
    """Run the STT streamer and collect all emitted events."""
    events: List[TranscriptEvent] = []

    async def capture(event: TranscriptEvent) -> None:
        events.append(event)

    stt_with_capture = StreamingSTT(
        session_id=stt.session_id,
        thread_id=stt.thread_id,
        on_transcript=capture,
        include_partial=stt._include_partial,
    )
    await stt_with_capture.run()
    return events


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestStreamingSTTMock:
    @pytest.mark.asyncio
    async def test_correct_number_of_final_events(self) -> None:
        """Should emit exactly len(SCRIPTED_TURNS) final events."""
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=capture,
        )
        await stt.run()

        assert len(received) == len(SCRIPTED_TURNS), (
            f"Expected {len(SCRIPTED_TURNS)} events, got {len(received)}"
        )

    @pytest.mark.asyncio
    async def test_all_events_are_final(self) -> None:
        """With include_partial=False (default), all events must be is_final=True."""
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=capture,
        )
        await stt.run()

        for ev in received:
            assert ev.is_final, f"Non-final event slipped through: {ev.text!r}"

    @pytest.mark.asyncio
    async def test_speaker_tags_match_script(self) -> None:
        """Speaker values must exactly match the scripted turns."""
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=capture,
        )
        await stt.run()

        expected_speakers = [turn[0] for turn in SCRIPTED_TURNS]
        actual_speakers = [ev.speaker for ev in received]
        assert actual_speakers == expected_speakers, (
            f"Speaker sequence mismatch.\nExpected: {expected_speakers}\nGot: {actual_speakers}"
        )

    @pytest.mark.asyncio
    async def test_session_and_thread_ids_are_threaded(self) -> None:
        """All events must carry the session_id and thread_id provided at construction."""
        SESSION = "my-session-xyz"
        THREAD = "my-thread-abc"
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id=SESSION,
            thread_id=THREAD,
            on_transcript=capture,
        )
        await stt.run()

        for ev in received:
            assert ev.session_id == SESSION
            assert ev.thread_id == THREAD

    @pytest.mark.asyncio
    async def test_partial_events_when_requested(self) -> None:
        """With include_partial=True, we should get more events than SCRIPTED_TURNS."""
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=capture,
            include_partial=True,
        )
        await stt.run()

        finals = [ev for ev in received if ev.is_final]
        partials = [ev for ev in received if not ev.is_final]

        assert len(finals) == len(SCRIPTED_TURNS)
        # MockSTT with include_partial=True emits one partial per turn
        assert len(partials) == len(SCRIPTED_TURNS)

    @pytest.mark.asyncio
    async def test_stop_halts_stream(self) -> None:
        """
        Calling stop() mid-stream should cause run() to exit before all events are emitted.

        The mock STT has asyncio.sleep() pauses between turns (simulating real speech
        timing). stop() sets a flag; the stream checks it before forwarding each event
        to the callback. Because the sleep pauses run inside the mock generator (not the
        streamer), we stop BETWEEN turns — not mid-sleep. So we assert that the stream
        terminated early (fewer than all turns), not that exactly 1 event was delivered.
        """
        total_turns = len(SCRIPTED_TURNS)
        received: List[TranscriptEvent] = []
        call_count = 0

        # We build the stt2 first so we can reference it inside the closure
        stt2: Optional[StreamingSTT] = None

        async def stop_after_first(ev: TranscriptEvent) -> None:
            nonlocal call_count
            call_count += 1
            received.append(ev)
            if call_count == 1 and stt2 is not None:
                await stt2.stop()

        stt2 = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=stop_after_first,
        )
        await stt2.run()

        # The stream must have stopped before ALL scripted turns were delivered.
        # (If stop() had no effect, received would equal total_turns.)
        assert len(received) < total_turns, (
            f"stop() had no effect — received all {total_turns} events. "
            f"Expected fewer than {total_turns}."
        )

    @pytest.mark.asyncio
    async def test_event_ids_are_unique(self) -> None:
        """Each TranscriptEvent must have a unique event_id (UUID4)."""
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=capture,
        )
        await stt.run()

        ids = [ev.event_id for ev in received]
        assert len(ids) == len(set(ids)), "Duplicate event_ids detected"

    @pytest.mark.asyncio
    async def test_timestamps_are_utc(self) -> None:
        """All event timestamps must be timezone-aware UTC."""
        received: List[TranscriptEvent] = []

        async def capture(ev: TranscriptEvent) -> None:
            received.append(ev)

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=capture,
        )
        await stt.run()

        for ev in received:
            assert ev.timestamp.tzinfo is not None, "timestamp is naive (no tzinfo)"

    @pytest.mark.asyncio
    async def test_on_transcript_exception_does_not_crash_stream(self) -> None:
        """If the callback raises an error, StreamingSTT should log and continue."""
        received: List[TranscriptEvent] = []

        async def buggy_capture(ev: TranscriptEvent) -> None:
            received.append(ev)
            if len(received) == 1:
                raise ValueError("Simulated callback crash")

        stt = StreamingSTT(
            session_id="test-session",
            thread_id="test-thread",
            on_transcript=buggy_capture,
        )
        await stt.run()

        # Even with the crash on the first event, the stream should finish and deliver all events
        assert len(received) == len(SCRIPTED_TURNS)


class TestLiveSTT:
    def test_live_stt_unsupported_provider_raises(self) -> None:
        from unittest.mock import patch
        from shared.config import settings
        
        stt = StreamingSTT("session", "thread", on_transcript=lambda e: None)  # type: ignore
        with patch.object(settings, "use_mocks", False):
            backend = stt._make_backend()
            with patch.object(settings, "stt_provider", "unknown_xyz"):
                with pytest.raises(ValueError, match="Unknown stt_provider"):
                    backend._build_stt_plugin()  # type: ignore
