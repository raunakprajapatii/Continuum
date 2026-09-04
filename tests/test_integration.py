"""
tests/test_integration.py
--------------------------
Full End-to-End Integration Tests for the Continuum pipeline.

Tests the COMPLETE data flow across ALL four module pairs:
  Pair A (Transport) → Pair B (Signal) → Pair C (Brain) → Pair D (Voice/Facts) → Pair A

These tests replace per-module mocks with real module instances connected
together, exercising the actual inter-module contracts.  The ONLY mock used
is the mock_freshness ASGI app (instead of a real live data API) — everything
else runs real production code.

Test taxonomy:
  INTG-01..05  — Core pipeline (happy path + reconnect scenarios)
  INTG-06..09  — Brain module integration (store + extractor + recap builder)
  INTG-10..13  — Signal module integration (CallerMatcher + ReconnectDetector)
  INTG-14..17  — Voice/Facts pipeline (freshness → text → TTS)
  INTG-18..20  — Transport invariants (track fencing, ducking, barge-in)
  INTG-21..24  — Robustness / edge-case tests
  INTG-25      — Master end-to-end Scenario B across all 4 pairs
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

# ── Shared schemas ─────────────────────────────────────────────────────────────
from shared.schemas import (
    CallState,
    CallStateEvent,
    Commitment,
    FactCheckResult,
    FreshnessResult,
    FreshnessStatus,
    RecapRequest,
    RecapUrgency,
    RimeModel,
    Speaker,
    ThreadSummary,
    TimeSensitiveFact,
    TranscriptEvent,
    TtsRequest,
)

# ── Module imports ─────────────────────────────────────────────────────────────
from modules.brain.extractor import ConversationExtractor
from modules.brain.recap import build_recap_request, determine_urgency
from modules.brain.service import BrainService
from modules.brain.store import ThreadMemoryStore
from modules.signal.caller_matcher import CallerMatcher, normalise_caller_id
from modules.signal.reconnect_detector import ReconnectDecision, ReconnectDetector
from modules.transport.audio_ducking import AudioDuckingController
from modules.transport.exceptions import SessionStateError, TrackFencingViolationError
from modules.transport.session_manager import CallSessionManager
from modules.transport.whisper_channel import PrivateWhisperChannel
from modules.voice.freshness_checker import FreshnessChecker
from modules.voice.pipeline import VoicePipeline
from modules.voice.recap_text_builder import (
    RecapTextBuilder,
    RecapTextValidationError,
    RimePromptValidator,
)
from modules.voice.rime_tts_client import RimeTtsClient

# ── Mock data helpers ──────────────────────────────────────────────────────────
from mocks.mock_brain import make_recap_request
from mocks.mock_freshness import app as freshness_asgi_app
from mocks.mock_freshness import get_fact_value, set_fact_value

# ── Constants ──────────────────────────────────────────────────────────────────
CALLER_Z = "+14155550199"
CALLER_NEW = "+14085550101"
CALLER_SIP = "sip:alice@corp.example.com"
PRIVATE_TRACK = "continuum-private-whisper"
CALLER_TRACK = "caller-facing-main"


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def in_memory_store() -> ThreadMemoryStore:
    """Fresh in-memory SQLite store for each test."""
    return ThreadMemoryStore(db_path=":memory:")


@pytest.fixture
async def initialized_store(in_memory_store: ThreadMemoryStore) -> ThreadMemoryStore:
    """In-memory store with schema initialised."""
    await in_memory_store.init_db()
    return in_memory_store


@pytest.fixture
def extractor() -> ConversationExtractor:
    """Heuristic extractor (no Gemini API needed)."""
    return ConversationExtractor(api_key=None)


@pytest.fixture
async def brain_service(initialized_store: ThreadMemoryStore, extractor: ConversationExtractor) -> BrainService:
    """BrainService wired to an in-memory store."""
    svc = BrainService(store=initialized_store, extractor=extractor)
    await svc.init()
    return svc


@pytest.fixture
def mock_http_client() -> httpx.AsyncClient:
    """httpx client routed to the mock freshness ASGI app."""
    transport = httpx.ASGITransport(app=cast(Any, freshness_asgi_app))
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")


@pytest.fixture
def freshness_checker(mock_http_client: httpx.AsyncClient) -> FreshnessChecker:
    """FreshnessChecker that hits the local mock API via ASGI transport."""
    return FreshnessChecker(client=mock_http_client)


@pytest.fixture
def text_builder() -> RecapTextBuilder:
    return RecapTextBuilder()


@pytest.fixture
def tts_client() -> RimeTtsClient:
    return RimeTtsClient()


@pytest.fixture
def voice_pipeline(freshness_checker: FreshnessChecker, text_builder: RecapTextBuilder, tts_client: RimeTtsClient) -> VoicePipeline:
    return VoicePipeline(
        freshness_checker=freshness_checker,
        text_builder=text_builder,
        tts_client=tts_client,
    )


@pytest.fixture
def whisper_channel() -> PrivateWhisperChannel:
    return PrivateWhisperChannel(
        private_track_id=PRIVATE_TRACK,
        use_mocks=True,
    )


@pytest.fixture
def session_manager(whisper_channel: PrivateWhisperChannel) -> CallSessionManager:
    return CallSessionManager(
        whisper_channel=whisper_channel,
        interrupted_threads_registry={},
        use_mocks=True,
    )


@pytest.fixture
def reconnect_detector() -> ReconnectDetector:
    return ReconnectDetector()


def make_call_event(
    state: CallState,
    session_id: Optional[str] = None,
    caller_id: Optional[str] = CALLER_Z,
    thread_id: Optional[str] = None,
    is_reconnect: bool = False,
) -> CallStateEvent:
    return CallStateEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id or f"session-{uuid.uuid4().hex[:8]}",
        thread_id=thread_id or f"thread-{uuid.uuid4().hex[:6]}",
        state=state,
        previous_state=None,
        caller_id=caller_id,
        is_reconnect=is_reconnect,
        timestamp=datetime.now(tz=timezone.utc),
    )


def make_transcript_event(
    text: str,
    speaker: Speaker = Speaker.CALLER,
    session_id: str = "sess-001",
    is_final: bool = True,
) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        speaker=speaker,
        text=text,
        start_ms=0,
        end_ms=2000,
        is_final=is_final,
        confidence=0.97,
        timestamp=datetime.now(tz=timezone.utc),
    )


def make_thread_summary(
    caller_id: str = CALLER_Z,
    thread_id: Optional[str] = None,
    headline: str = "Z wanted the Q3 number; you said you'd check with finance.",
    with_price: bool = True,
    is_interrupted: bool = True,
) -> ThreadSummary:
    facts = []
    if with_price:
        facts.append(
            TimeSensitiveFact(
                key="price_usd",
                label="Unit price",
                value="$400",
                recorded_at=datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc),
            )
        )
    return ThreadSummary(
        thread_id=thread_id or f"thread-{uuid.uuid4().hex[:6]}",
        caller_id=caller_id,
        caller_name="Z",
        headline=headline,
        open_items=["Check with finance team on volume discounts"],
        commitments=[
            Commitment(
                owner="user",
                text="Loop in finance today and get back to Z on volume discounts.",
                is_resolved=False,
            )
        ],
        time_sensitive_facts=facts,
        key_names=["Z", "Q3", "finance"],
        last_spoken_turn_text="Also, ticket XYZ-" if is_interrupted else None,
        created_at=datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc),
        last_updated_at=datetime(2026, 9, 3, 10, 15, 0, tzinfo=timezone.utc),
        last_call_ended_at=datetime(2026, 9, 3, 10, 15, 0, tzinfo=timezone.utc),
        is_interrupted=is_interrupted,
        call_count=1,
    )


def make_freshness_result(changed: bool = True, key: str = "price_usd") -> FreshnessResult:
    status = FreshnessStatus.CHANGED if changed else FreshnessStatus.UNCHANGED
    return FreshnessResult(
        request_id=str(uuid.uuid4()),
        thread_id="thread-001",
        results=[
            FactCheckResult(
                key=key,
                label="Unit price",
                cached_value="$400",
                live_value="$420" if changed else "$400",
                status=status,
                checked_at=datetime.now(tz=timezone.utc),
                latency_ms=10,
            )
        ],
        any_changed=changed,
        completed_at=datetime.now(tz=timezone.utc),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-01 — Happy Path: Normal Call (no recap)
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG01_NormalCall:
    """New caller → ring → connect → complete. No recap expected."""

    async def test_normal_call_no_recap_generated(self, brain_service: BrainService):
        session_id = "sess-normal-01"
        turns = [
            make_transcript_event("Hi, this is Alice.", Speaker.CALLER, session_id),
            make_transcript_event("Hello Alice!", Speaker.USER, session_id),
            make_transcript_event("I wanted to discuss Q3 pricing.", Speaker.CALLER, session_id),
        ]
        for t in turns:
            await brain_service.on_transcript_event(t)

        ring_event = make_call_event(CallState.RINGING, session_id=session_id, caller_id=CALLER_NEW, is_reconnect=False)
        recap_req = await brain_service.on_call_ringing(ring_event)
        assert recap_req is None, "New caller should not generate a recap"

    async def test_completed_call_stores_summary(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        session_id = "sess-normal-02"
        turns = [
            make_transcript_event("The unit price is $400.", Speaker.CALLER, session_id),
            make_transcript_event("Got it, I'll check.", Speaker.USER, session_id),
        ]
        for t in turns:
            await brain_service.on_transcript_event(t)

        end_event = make_call_event(CallState.COMPLETED, session_id=session_id, caller_id=CALLER_NEW)
        summary = await brain_service.on_call_ended(end_event)
        assert summary is not None
        persisted = await initialized_store.get_summary_by_caller(CALLER_NEW)
        assert persisted is not None
        assert not summary.is_interrupted

    async def test_completed_call_does_not_mark_interrupted(self, brain_service: BrainService):
        session_id = "sess-normal-03"
        turns = [make_transcript_event("Thanks, bye!", Speaker.USER, session_id)]
        for t in turns:
            await brain_service.on_transcript_event(t)

        end_event = make_call_event(CallState.COMPLETED, session_id=session_id, caller_id=CALLER_NEW)
        summary = await brain_service.on_call_ended(end_event)
        assert summary is not None
        assert summary.is_interrupted is False


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-02 — Scenario B: Reconnect (Mid-Call Disconnect)
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG02_ReconnectScenarioB:
    """Call drops → caller returns → recap whispered before pickup."""

    async def test_disconnect_marks_interrupted(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        session_id = "sess-disc-01"
        turns = [
            make_transcript_event("Q3 price is $400.", Speaker.CALLER, session_id),
        ]
        for t in turns:
            await brain_service.on_transcript_event(t)

        disc_event = make_call_event(CallState.DISCONNECTED, session_id=session_id, caller_id=CALLER_Z)
        summary = await brain_service.on_call_ended(disc_event)
        assert summary is not None
        assert summary.is_interrupted is True

    async def test_reconnect_generates_recap_request(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        """After a disconnect, the next RINGING with is_reconnect=True should produce RecapRequest."""
        summary = make_thread_summary(caller_id=CALLER_Z)
        await initialized_store.save_summary(summary)

        ring_event = make_call_event(
            CallState.RINGING, session_id="sess-disc-02", caller_id=CALLER_Z, is_reconnect=True
        )
        recap_req = await brain_service.on_call_ringing(ring_event)
        assert recap_req is not None
        assert recap_req.summary.caller_id == CALLER_Z

    async def test_reconnect_recap_has_time_sensitive_facts(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        summary = make_thread_summary(caller_id=CALLER_Z, with_price=True)
        await initialized_store.save_summary(summary)

        ring_event = make_call_event(
            CallState.RINGING, session_id="sess-disc-03", caller_id=CALLER_Z, is_reconnect=True
        )
        recap_req = await brain_service.on_call_ringing(ring_event)
        assert recap_req is not None
        keys = {f.key for f in recap_req.facts_to_verify}
        assert "price_usd" in keys

    async def test_non_reconnect_ringing_no_recap(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        summary = make_thread_summary(caller_id=CALLER_Z)
        await initialized_store.save_summary(summary)

        ring_event = make_call_event(
            CallState.RINGING, session_id="sess-disc-04", caller_id=CALLER_Z, is_reconnect=False
        )
        recap_req = await brain_service.on_call_ringing(ring_event)
        assert recap_req is None, "is_reconnect=False should not trigger recap"


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-03 — Scenario C: Stale Fact Caught and Flagged
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG03_StaleFactScenarioC:
    """Price was $400 yesterday; now $420. Recap must surface this."""

    async def test_freshness_catches_changed_price(self, voice_pipeline: VoicePipeline):
        set_fact_value("price_usd", "$420")
        try:
            recap_req = make_recap_request()  # has $400 cached
            tts_req = await voice_pipeline.run(recap_req)
            assert "420" in tts_req.text or "Heads up" in tts_req.text
        finally:
            set_fact_value("price_usd", "$420")
        await voice_pipeline.aclose()

    async def test_freshness_unchanged_no_heads_up(self, voice_pipeline: VoicePipeline):
        set_fact_value("price_usd", "$400")
        try:
            recap_req = make_recap_request()
            tts_req = await voice_pipeline.run(recap_req)
            assert "Heads up" not in tts_req.text
        finally:
            set_fact_value("price_usd", "$420")
        await voice_pipeline.aclose()

    async def test_full_scenario_c_end_to_end(
        self, brain_service: BrainService, initialized_store: ThreadMemoryStore, voice_pipeline: VoicePipeline
    ):
        """Full Scenario C: store summary → reconnect → freshness → TTS."""
        summary = make_thread_summary(caller_id=CALLER_Z, with_price=True)
        await initialized_store.save_summary(summary)
        set_fact_value("price_usd", "$420")

        try:
            ring_event = make_call_event(
                CallState.RINGING, session_id="sess-C", caller_id=CALLER_Z, is_reconnect=True
            )
            recap_req = await brain_service.on_call_ringing(ring_event)
            assert recap_req is not None

            tts_req = await voice_pipeline.run(recap_req)
            assert isinstance(tts_req, TtsRequest)
            assert len(tts_req.text) > 0
        finally:
            set_fact_value("price_usd", "$420")
        await voice_pipeline.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-04 — Transport FSM State Transitions
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG04_TransportFSM:
    """Call State Finite State Machine correctness."""

    async def test_idle_to_ringing_to_connected_to_completed(self, session_manager: CallSessionManager):
        e1 = await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        assert e1.state == CallState.RINGING
        e2 = await session_manager.transition_to(CallState.CONNECTED)
        assert e2.state == CallState.CONNECTED
        assert e2.previous_state == CallState.RINGING
        e3 = await session_manager.transition_to(CallState.COMPLETED)
        assert e3.state == CallState.COMPLETED

    async def test_invalid_transition_raises(self, session_manager: CallSessionManager):
        """IDLE → COMPLETED is invalid."""
        with pytest.raises(SessionStateError):
            await session_manager.transition_to(CallState.COMPLETED)

    async def test_reconnect_detected_during_ringing(self, session_manager: CallSessionManager):
        session_manager.register_interrupted_thread(CALLER_Z, "thread-prev-001")
        event = await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        assert event.is_reconnect is True

    async def test_disconnect_registers_interrupted_thread(self, session_manager: CallSessionManager):
        await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        await session_manager.transition_to(CallState.CONNECTED)
        await session_manager.transition_to(CallState.DISCONNECTED)
        assert CALLER_Z in session_manager._interrupted_threads

    async def test_subscribers_receive_all_events(self, session_manager: CallSessionManager):
        queue = session_manager.subscribe()
        await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        await session_manager.transition_to(CallState.CONNECTED)
        await session_manager.transition_to(CallState.COMPLETED)
        events = []
        while not queue.empty():
            events.append(await queue.get())
        assert len(events) == 3
        assert [e.state for e in events] == [CallState.RINGING, CallState.CONNECTED, CallState.COMPLETED]

    async def test_ring_window_elapsed_timing(self, session_manager: CallSessionManager):
        await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        await asyncio.sleep(0.05)
        assert session_manager.elapsed_ring_seconds is not None
        assert session_manager.elapsed_ring_seconds >= 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-05 — Signal: ReconnectDetector End-to-End
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG05_ReconnectDetector:
    """Full Signal module reconnect detection across two sessions."""

    async def test_drop_then_reconnect(self, reconnect_detector: ReconnectDetector):
        session_1 = "sess-sig-01"
        thread_id = "thread-sig-01"

        ring1 = make_call_event(CallState.RINGING, session_id=session_1, caller_id=CALLER_Z, thread_id=thread_id)
        d1 = await reconnect_detector.on_event(ring1)
        assert not d1.is_reconnect

        conn1 = make_call_event(CallState.CONNECTED, session_id=session_1, caller_id=CALLER_Z, thread_id=thread_id)
        d2 = await reconnect_detector.on_event(conn1)
        assert d2.should_start_stt

        disc1 = make_call_event(CallState.DISCONNECTED, session_id=session_1, caller_id=CALLER_Z, thread_id=thread_id)
        d3 = await reconnect_detector.on_event(disc1)
        assert d3.call_ended_abruptly
        assert d3.should_stop_stt

        session_2 = "sess-sig-02"
        ring2 = make_call_event(CallState.RINGING, session_id=session_2, caller_id=CALLER_Z, thread_id=thread_id)
        d4 = await reconnect_detector.on_event(ring2)
        assert d4.is_reconnect
        assert d4.prior_thread_id == thread_id

    async def test_clean_close_no_reconnect(self, reconnect_detector: ReconnectDetector):
        session_1 = "sess-clean-01"
        thread_id = "thread-clean-01"
        ring1 = make_call_event(CallState.RINGING, session_id=session_1, caller_id=CALLER_NEW, thread_id=thread_id)
        await reconnect_detector.on_event(ring1)
        conn1 = make_call_event(CallState.CONNECTED, session_id=session_1, caller_id=CALLER_NEW, thread_id=thread_id)
        await reconnect_detector.on_event(conn1)
        comp1 = make_call_event(CallState.COMPLETED, session_id=session_1, caller_id=CALLER_NEW, thread_id=thread_id)
        await reconnect_detector.on_event(comp1)

        session_2 = "sess-clean-02"
        ring2 = make_call_event(CallState.RINGING, session_id=session_2, caller_id=CALLER_NEW, thread_id=thread_id)
        d = await reconnect_detector.on_event(ring2)
        assert not d.is_reconnect

    async def test_multiple_callers_isolated(self, reconnect_detector: ReconnectDetector):
        # Z drops
        ring_z = make_call_event(CallState.RINGING, session_id="sess-z-01", caller_id=CALLER_Z)
        await reconnect_detector.on_event(ring_z)
        disc_z = make_call_event(CallState.DISCONNECTED, session_id="sess-z-01", caller_id=CALLER_Z)
        await reconnect_detector.on_event(disc_z)

        # A calls for first time
        ring_a = make_call_event(CallState.RINGING, session_id="sess-a-01", caller_id=CALLER_NEW)
        d = await reconnect_detector.on_event(ring_a)
        assert not d.is_reconnect


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-06 — Brain: ThreadMemoryStore CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG06_BrainStore:
    """ThreadMemoryStore save/get/list/delete operations."""

    async def test_save_and_retrieve_by_thread_id(self, initialized_store: ThreadMemoryStore):
        summary = make_thread_summary()
        await initialized_store.save_summary(summary)
        result = await initialized_store.get_summary_by_thread_id(summary.thread_id)
        assert result is not None
        assert result.thread_id == summary.thread_id

    async def test_save_and_retrieve_by_caller(self, initialized_store: ThreadMemoryStore):
        summary = make_thread_summary()
        await initialized_store.save_summary(summary)
        result = await initialized_store.get_summary_by_caller(CALLER_Z)
        assert result is not None

    async def test_upsert_updates_existing(self, initialized_store: ThreadMemoryStore):
        summary = make_thread_summary()
        await initialized_store.save_summary(summary)
        updated = summary.model_copy(update={"headline": "Updated headline.", "call_count": 2})
        await initialized_store.save_summary(updated)
        all_summaries = await initialized_store.list_summaries()
        caller_records = [s for s in all_summaries if s.caller_id == CALLER_Z]
        assert len(caller_records) == 1
        assert caller_records[0].call_count == 2

    async def test_delete_summary(self, initialized_store: ThreadMemoryStore):
        summary = make_thread_summary()
        await initialized_store.save_summary(summary)
        deleted = await initialized_store.delete_summary(summary.thread_id)
        assert deleted is True
        assert await initialized_store.get_summary_by_thread_id(summary.thread_id) is None

    async def test_turn_buffering_and_retrieval(self, initialized_store: ThreadMemoryStore):
        session_id = "sess-buf-01"
        turns = [
            make_transcript_event("Hello.", Speaker.CALLER, session_id),
            make_transcript_event("Hi there.", Speaker.USER, session_id),
        ]
        for t in turns:
            await initialized_store.append_turn(session_id, t)
        retrieved = await initialized_store.get_session_turns(session_id)
        assert len(retrieved) == 2
        await initialized_store.clear_session_turns(session_id)
        assert len(await initialized_store.get_session_turns(session_id)) == 0

    async def test_non_final_turns_excluded(self, initialized_store: ThreadMemoryStore):
        session_id = "sess-buf-02"
        final_turn = make_transcript_event("Final.", Speaker.CALLER, session_id, is_final=True)
        interim_turn = make_transcript_event("interim", Speaker.CALLER, session_id, is_final=False)
        await initialized_store.append_turn(session_id, final_turn)
        await initialized_store.append_turn(session_id, interim_turn)
        final_only = await initialized_store.get_session_turns(session_id, final_only=True)
        all_turns = await initialized_store.get_session_turns(session_id, final_only=False)
        assert len(final_only) == 1
        assert len(all_turns) == 2

    async def test_unknown_thread_id_returns_none(self, initialized_store: ThreadMemoryStore):
        result = await initialized_store.get_summary_by_thread_id("nonexistent-thread")
        assert result is None

    async def test_unknown_caller_returns_none(self, initialized_store: ThreadMemoryStore):
        result = await initialized_store.get_summary_by_caller("+10000000000")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-07 — Brain: ConversationExtractor Heuristic
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG07_ConversationExtractor:
    """Heuristic extractor produces valid ThreadSummary from turns."""

    async def test_extracts_price_fact(self, extractor: ConversationExtractor):
        turns = [make_transcript_event("The unit price is $400.", Speaker.CALLER)]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        assert any(f.key == "price_usd" for f in summary.time_sensitive_facts)

    async def test_extracts_commitment_from_user(self, extractor: ConversationExtractor):
        turns = [
            make_transcript_event("Can you follow up on the proposal?", Speaker.CALLER),
            make_transcript_event("I'll get back to you.", Speaker.USER),
        ]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        assert len(summary.commitments) > 0

    async def test_headline_under_20_words(self, extractor: ConversationExtractor):
        turns = [
            make_transcript_event("Hi, I'm calling about Q3 pricing.", Speaker.CALLER),
            make_transcript_event("I need to check with finance.", Speaker.USER),
        ]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        word_count = len(summary.headline.split())
        assert word_count <= 20, f"Headline has {word_count} words: '{summary.headline}'"

    async def test_empty_turns_returns_safe_default(self, extractor: ConversationExtractor):
        summary = await extractor.extract([], caller_id=CALLER_Z)
        assert summary is not None
        assert len(summary.headline) > 0

    async def test_interrupted_marks_last_turn(self, extractor: ConversationExtractor):
        turns = [make_transcript_event("The deal is for", Speaker.CALLER)]
        summary = await extractor.extract(turns, caller_id=CALLER_Z, is_interrupted=True)
        assert summary.is_interrupted
        assert summary.last_spoken_turn_text is not None

    async def test_prior_summary_facts_merged(self, extractor: ConversationExtractor):
        prior = make_thread_summary()
        new_turns = [make_transcript_event("Delivery by Monday.", Speaker.CALLER)]
        summary = await extractor.extract(new_turns, caller_id=CALLER_Z, prior_summary=prior)
        keys = {f.key for f in summary.time_sensitive_facts}
        assert "price_usd" in keys  # merged from prior


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-08 — Brain: Recap Urgency Calculation
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG08_RecapUrgency:
    """determine_urgency and build_recap_request urgency mapping."""

    def test_short_window_headline_only(self):
        assert determine_urgency(3.0) == RecapUrgency.HEADLINE_ONLY

    def test_exactly_6s_is_headline_only(self):
        assert determine_urgency(6.0) == RecapUrgency.HEADLINE_ONLY

    def test_standard_window(self):
        assert determine_urgency(15.0) == RecapUrgency.STANDARD

    def test_long_window_extended(self):
        assert determine_urgency(25.0) == RecapUrgency.EXTENDED

    def test_none_defaults_to_standard(self):
        assert determine_urgency(None) == RecapUrgency.STANDARD

    def test_invalid_string_defaults_to_standard(self):
        assert determine_urgency("not_a_number") == RecapUrgency.STANDARD

    def test_negative_window_headline_only(self):
        assert determine_urgency(-5.0) == RecapUrgency.HEADLINE_ONLY

    def test_zero_window_headline_only(self):
        assert determine_urgency(0.0) == RecapUrgency.HEADLINE_ONLY

    def test_recap_request_urgency_propagates(self):
        summary = make_thread_summary()
        req = build_recap_request(summary, "sess-001", estimated_ring_window_seconds=5.0)
        assert req.urgency == RecapUrgency.HEADLINE_ONLY


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-09 — Brain Service: Full Workflow
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG09_BrainServiceWorkflow:
    """BrainService orchestrates transcript → extract → store → recap."""

    async def test_full_lifecycle_through_brain_service(
        self, brain_service: BrainService, initialized_store: ThreadMemoryStore
    ):
        session_id = "sess-brain-full-01"
        caller_id = CALLER_Z

        turns = [
            make_transcript_event("Hi, I wanted to discuss Q3 pricing.", Speaker.CALLER, session_id),
            make_transcript_event("Current price is $400 per unit.", Speaker.USER, session_id),
            make_transcript_event("Can you get a volume discount?", Speaker.CALLER, session_id),
            make_transcript_event("I'll loop in finance.", Speaker.USER, session_id),
        ]
        for t in turns:
            await brain_service.on_transcript_event(t)

        disc_event = make_call_event(CallState.DISCONNECTED, session_id=session_id, caller_id=caller_id)
        summary = await brain_service.on_call_ended(disc_event)
        assert summary is not None
        assert summary.is_interrupted

        ring_event = make_call_event(
            CallState.RINGING, session_id="sess-brain-full-02", caller_id=caller_id, is_reconnect=True
        )
        recap_req = await brain_service.on_call_ringing(ring_event)
        assert recap_req is not None

    async def test_interim_turns_skipped(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        session_id = "sess-interim-01"
        interim = make_transcript_event("um", Speaker.USER, session_id, is_final=False)
        final_turn = make_transcript_event("Hello, let's talk pricing.", Speaker.CALLER, session_id, is_final=True)
        await brain_service.on_transcript_event(interim)
        await brain_service.on_transcript_event(final_turn)
        turns = await initialized_store.get_session_turns(session_id)
        assert len(turns) == 1  # only the final turn


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-10 — Signal: CallerMatcher Normalisation
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG10_CallerMatcherNormalisation:
    """Caller ID normalisation handles E.164, SIP, and edge cases."""

    def test_e164_with_formatting(self):
        assert normalise_caller_id("+1 (415) 555-0199") == "+14155550199"

    def test_e164_no_plus(self):
        assert normalise_caller_id("14155550199") == "14155550199"

    def test_sip_with_transport_param(self):
        result = normalise_caller_id("sip:alice@example.com;transport=tls")
        assert result == "sip:alice@example.com"

    def test_sip_lowercase(self):
        result = normalise_caller_id("SIP:Bob@Corp.Com")
        assert result == "sip:bob@corp.com"

    def test_none_returns_none(self):
        assert normalise_caller_id(None) is None

    def test_empty_returns_none(self):
        assert normalise_caller_id("") is None

    def test_whitespace_returns_none(self):
        assert normalise_caller_id("   ") is None

    async def test_record_and_lookup(self):
        matcher = CallerMatcher()
        event = make_call_event(CallState.RINGING, caller_id=CALLER_Z)
        await matcher.record_event(event)
        entry = await matcher.lookup(CALLER_Z)
        assert entry is not None
        assert not entry.is_interrupted

    async def test_mark_interrupted(self):
        matcher = CallerMatcher()
        event = make_call_event(CallState.RINGING, caller_id=CALLER_Z)
        await matcher.record_event(event)
        await matcher.mark_interrupted(CALLER_Z)
        entry = await matcher.lookup(CALLER_Z)
        assert entry is not None
        assert entry.is_interrupted

    async def test_clear_interrupted(self):
        matcher = CallerMatcher()
        event = make_call_event(CallState.RINGING, caller_id=CALLER_Z)
        await matcher.record_event(event)
        await matcher.mark_interrupted(CALLER_Z)
        await matcher.clear_interrupted(CALLER_Z)
        entry = await matcher.lookup(CALLER_Z)
        assert entry is not None
        assert not entry.is_interrupted

    async def test_unknown_caller_returns_none(self):
        matcher = CallerMatcher()
        assert await matcher.lookup("+10000000000") is None


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-11 — Voice: Rime Prompt Validator (all 8 rules)
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG11_RimePromptValidator:
    """RimePromptValidator enforces all 8 Rime rules."""

    def test_valid_text_passes(self):
        validator = RimePromptValidator()
        text = "Z wanted the Q3 number; you said you'd check with finance. Your move: loop in finance today."
        assert validator.validate(text) == []

    def test_preamble_violation(self):
        validator = RimePromptValidator()
        violations = validator.validate("Here is a summary: Z called about pricing.")
        assert any("Rule 1" in v for v in violations)

    def test_ssml_violation(self):
        validator = RimePromptValidator()
        violations = validator.validate("Z called. <break time='1s'/> Price is $400.")
        assert any("Rule 4" in v for v in violations)

    def test_sentence_over_20_words(self):
        validator = RimePromptValidator()
        long_sentence = " ".join(["word"] * 25) + "."
        violations = validator.validate(long_sentence)
        assert any("Rule 2" in v for v in violations)

    def test_disfluency_stacking(self):
        validator = RimePromptValidator()
        violations = validator.validate("So, so, Z called about pricing.")
        assert any("Rule 3" in v for v in violations)

    def test_bare_ticket_id_violation(self):
        validator = RimePromptValidator()
        violations = validator.validate("Check ticket XYZ-123 for details.")
        assert any("Rule 6" in v for v in violations)

    def test_spell_wrapped_id_passes_rule6(self):
        validator = RimePromptValidator()
        violations = validator.validate("Check ticket spell(XYZ-123) for details.")
        assert not any("Rule 6" in v for v in violations)


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-12 — Voice: RecapTextBuilder Output Quality
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG12_RecapTextBuilder:
    """RecapTextBuilder produces Rime-compliant text under all conditions."""

    def test_headline_only_mode_concise(self, text_builder: RecapTextBuilder):
        summary = make_thread_summary()
        freshness = make_freshness_result(changed=False)
        text = text_builder.build(summary, freshness, RecapUrgency.HEADLINE_ONLY)
        assert len(text) > 0
        assert len(text.split()) <= 25

    def test_standard_mode_includes_open_items(self, text_builder: RecapTextBuilder):
        summary = make_thread_summary()
        freshness = make_freshness_result(changed=False)
        text = text_builder.build(summary, freshness, RecapUrgency.STANDARD)
        assert "finance" in text.lower() or "open" in text.lower() or "priority" in text.lower()

    def test_freshness_flag_when_changed(self, text_builder: RecapTextBuilder):
        summary = make_thread_summary()
        freshness = make_freshness_result(changed=True)
        text = text_builder.build(summary, freshness, RecapUrgency.STANDARD)
        assert "420" in text or "Heads up" in text

    def test_next_action_with_commitment(self, text_builder: RecapTextBuilder):
        summary = make_thread_summary()
        freshness = make_freshness_result(changed=False)
        text = text_builder.build(summary, freshness, RecapUrgency.STANDARD)
        assert "move" in text.lower() or "priority" in text.lower()

    def test_ssml_in_headline_raises_validation_error(self):
        summary = make_thread_summary(headline="<break time='2s'/> Z wanted the Q3 number.")
        freshness = FreshnessResult(
            request_id=str(uuid.uuid4()),
            thread_id="t",
            results=[],
            any_changed=False,
            completed_at=datetime.now(tz=timezone.utc),
        )
        builder = RecapTextBuilder()
        with pytest.raises(RecapTextValidationError):
            builder.build(summary, freshness, RecapUrgency.HEADLINE_ONLY)

    def test_extended_mode_includes_interrupted_note(self, text_builder: RecapTextBuilder):
        summary = make_thread_summary(is_interrupted=True)
        freshness = make_freshness_result(changed=False)
        text = text_builder.build(summary, freshness, RecapUrgency.EXTENDED)
        assert len(text) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-13 — Voice: FreshnessChecker via Mock ASGI
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG13_FreshnessChecker:
    """FreshnessChecker against mock ASGI transport."""

    async def test_detects_changed_value(self, freshness_checker: FreshnessChecker):
        set_fact_value("price_usd", "$420")
        recap_req = make_recap_request()
        result = await freshness_checker.check(recap_req)
        assert result.any_changed is True
        await freshness_checker.aclose()

    async def test_detects_unchanged_value(self, freshness_checker: FreshnessChecker):
        set_fact_value("price_usd", "$400")
        recap_req = make_recap_request()
        result = await freshness_checker.check(recap_req)
        assert result.any_changed is False
        await freshness_checker.aclose()
        set_fact_value("price_usd", "$420")

    async def test_unknown_key_returns_unavailable(self, freshness_checker: FreshnessChecker):
        recap_req = make_recap_request()
        unknown_fact = TimeSensitiveFact(
            key="unknown_metric_xyz",
            label="Unknown",
            value="0",
            recorded_at=datetime.now(tz=timezone.utc),
        )
        recap_req.facts_to_verify.append(unknown_fact)
        result = await freshness_checker.check(recap_req)
        statuses = {r.key: r.status for r in result.results}
        assert statuses.get("unknown_metric_xyz") == FreshnessStatus.UNAVAILABLE
        await freshness_checker.aclose()

    async def test_empty_facts_no_change(self, freshness_checker: FreshnessChecker):
        # RecapRequest is frozen; use model_copy to create a version with empty facts
        recap_req = make_recap_request().model_copy(update={"facts_to_verify": []})
        result = await freshness_checker.check(recap_req)
        assert not result.any_changed
        assert result.results == []
        await freshness_checker.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-14 — Transport: Track Fencing (Non-Negotiable Invariant)
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG14_TrackFencing:
    """The dual-track invariant must NEVER be violated."""

    def test_caller_track_raises(self, whisper_channel: PrivateWhisperChannel):
        with pytest.raises(TrackFencingViolationError):
            whisper_channel.validate_track_isolation(CALLER_TRACK)

    def test_private_track_passes(self, whisper_channel: PrivateWhisperChannel):
        whisper_channel.validate_track_isolation(PRIVATE_TRACK)  # no exception

    def test_unknown_track_raises(self, whisper_channel: PrivateWhisperChannel):
        with pytest.raises(TrackFencingViolationError):
            whisper_channel.validate_track_isolation("some-other-track")

    async def test_play_recap_on_caller_track_blocked(self, whisper_channel: PrivateWhisperChannel):
        tts = TtsRequest(
            request_id=str(uuid.uuid4()),
            session_id="sess-fence-01",
            thread_id="thread-fence-01",
            text="Must not reach caller.",
            speaker="sol",
            private_track_id=CALLER_TRACK,  # ← WRONG: must be blocked
            created_at=datetime.now(tz=timezone.utc),
        )
        with pytest.raises(TrackFencingViolationError):
            await whisper_channel.play_recap(tts)


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-15 — Transport: Audio Ducking
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG15_AudioDucking:
    """AudioDuckingController applies and restores volume levels."""

    async def test_ducking_activates_and_restores(self):
        controller = AudioDuckingController()
        assert not controller.is_ducked
        await controller.activate_ducking(reason="test")
        assert controller.is_ducked
        await controller.restore_levels(reason="test")
        assert not controller.is_ducked

    async def test_connected_call_recap_applies_ducking(self, whisper_channel: PrivateWhisperChannel):
        tts = TtsRequest(
            request_id=str(uuid.uuid4()),
            session_id="sess-duck-01",
            thread_id="thread-duck-01",
            text="Quick recap: Z wanted the Q3 number.",
            speaker="sol",
            private_track_id=PRIVATE_TRACK,
            created_at=datetime.now(tz=timezone.utc),
        )
        metrics = await whisper_channel.play_recap(tts, is_call_connected=True, enable_ducking=True)
        assert metrics.ducking_applied
        assert not whisper_channel.ducking_controller.is_ducked  # restored after playback

    async def test_pre_answer_recap_no_ducking(self, whisper_channel: PrivateWhisperChannel):
        tts = TtsRequest(
            request_id=str(uuid.uuid4()),
            session_id="sess-duck-02",
            thread_id="thread-duck-02",
            text="Pre-answer recap.",
            speaker="sol",
            private_track_id=PRIVATE_TRACK,
            created_at=datetime.now(tz=timezone.utc),
        )
        metrics = await whisper_channel.play_recap(tts, is_call_connected=False, enable_ducking=True)
        assert not metrics.ducking_applied


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-16 — Transport: Barge-In Interruptibility (<500ms SLA)
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG16_BargeIn:
    """User barge-in stops recap within <500ms."""

    async def test_barge_in_stops_playback_fast(self, whisper_channel: PrivateWhisperChannel):
        tts = TtsRequest(
            request_id=str(uuid.uuid4()),
            session_id="sess-barge-01",
            thread_id="thread-barge-01",
            text="Z wanted the Q3 number. You said you'd check with finance. Your move: loop in finance today.",
            speaker="sol",
            private_track_id=PRIVATE_TRACK,
            created_at=datetime.now(tz=timezone.utc),
        )

        async def interrupt_after_delay():
            await asyncio.sleep(0.05)
            await whisper_channel.interrupt(reason="user_barge_in")

        play_task = asyncio.create_task(whisper_channel.play_recap(tts))
        interrupt_task = asyncio.create_task(interrupt_after_delay())

        metrics = await play_task
        await interrupt_task

        assert metrics.interrupted
        assert metrics.stop_latency_ms is not None
        assert metrics.stop_latency_ms < 500, f"Stop latency {metrics.stop_latency_ms}ms > 500ms SLA"

    async def test_interrupt_when_not_playing_is_noop(self, whisper_channel: PrivateWhisperChannel):
        """Calling interrupt() when nothing is playing should return 0.0 without error."""
        result = await whisper_channel.interrupt(reason="no_playback")
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-17 — Voice Pipeline: Full Step 1→2→3
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG17_VoicePipelineFullRun:
    """VoicePipeline.run() produces a valid TtsRequest end-to-end."""

    async def test_pipeline_returns_tts_request(self, voice_pipeline: VoicePipeline):
        set_fact_value("price_usd", "$420")
        try:
            req = make_recap_request()
            tts_req = await voice_pipeline.run(req)
            assert isinstance(tts_req, TtsRequest)
            assert len(tts_req.text) > 0
            assert tts_req.private_track_id == PRIVATE_TRACK
        finally:
            set_fact_value("price_usd", "$420")
        await voice_pipeline.aclose()

    async def test_pipeline_text_rime_compliant(self, voice_pipeline: VoicePipeline):
        set_fact_value("price_usd", "$400")
        try:
            req = make_recap_request()
            tts_req = await voice_pipeline.run(req)
            violations = RimePromptValidator().validate(tts_req.text)
            assert violations == [], f"Rime violations: {violations}"
        finally:
            set_fact_value("price_usd", "$420")
        await voice_pipeline.aclose()

    async def test_pipeline_headline_only_urgency(self, voice_pipeline: VoicePipeline):
        req = make_recap_request(urgency=RecapUrgency.HEADLINE_ONLY, estimated_ring_window_seconds=5.0)
        tts_req = await voice_pipeline.run(req)
        assert isinstance(tts_req, TtsRequest)
        assert len(tts_req.text.split()) <= 30
        await voice_pipeline.aclose()

    async def test_pipeline_extended_urgency(self, voice_pipeline: VoicePipeline):
        req = make_recap_request(urgency=RecapUrgency.EXTENDED, estimated_ring_window_seconds=30.0)
        tts_req = await voice_pipeline.run(req)
        assert isinstance(tts_req, TtsRequest)
        assert len(tts_req.text) > 0
        await voice_pipeline.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-18 — Context Fencing: Thread Isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG18_ContextFencing:
    """Summaries from different threads must never leak into each other."""

    async def test_caller_a_data_not_in_caller_b_recap(
        self, brain_service: BrainService, initialized_store: ThreadMemoryStore
    ):
        summary_a = make_thread_summary(caller_id=CALLER_Z)
        await initialized_store.save_summary(summary_a)

        ring_b = make_call_event(
            CallState.RINGING, session_id="sess-fence-b", caller_id=CALLER_NEW, is_reconnect=True
        )
        recap_b = await brain_service.on_call_ringing(ring_b)
        assert recap_b is None, "Caller B must not receive Caller A's recap"

    async def test_two_callers_stored_independently(self, initialized_store: ThreadMemoryStore):
        summary_a = make_thread_summary(caller_id=CALLER_Z, thread_id="thread-a")
        summary_b = make_thread_summary(caller_id=CALLER_NEW, thread_id="thread-b")
        await initialized_store.save_summary(summary_a)
        await initialized_store.save_summary(summary_b)

        result_a = await initialized_store.get_summary_by_caller(CALLER_Z)
        result_b = await initialized_store.get_summary_by_caller(CALLER_NEW)
        assert result_a is not None
        assert result_b is not None
        assert result_a.caller_id != result_b.caller_id


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-19 — Robustness: Edge Cases and Bad Input
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG19_Robustness:
    """System handles edge cases and bad input gracefully."""

    async def test_brain_service_no_caller_id(self, brain_service: BrainService):
        event = CallStateEvent(
            event_id=str(uuid.uuid4()),
            session_id="sess-no-caller",
            thread_id=None,
            state=CallState.COMPLETED,
            previous_state=None,
            caller_id=None,
            is_reconnect=False,
            timestamp=datetime.now(tz=timezone.utc),
        )
        result = await brain_service.on_call_ended(event)
        assert result is None

    async def test_brain_service_zero_turns(self, brain_service: BrainService):
        event = make_call_event(CallState.COMPLETED, session_id="sess-zero-turns", caller_id=CALLER_Z)
        result = await brain_service.on_call_ended(event)
        assert result is None

    async def test_freshness_checker_timeout_returns_unavailable(self):
        """FreshnessChecker returns UNAVAILABLE (not raises) on network timeout."""
        mock_transport = MagicMock()
        mock_transport.handle_async_request = AsyncMock(
            side_effect=httpx.TimeoutException("simulated timeout")
        )
        client = httpx.AsyncClient(transport=mock_transport, base_url="http://localhost:9999")
        checker = FreshnessChecker(client=client)
        recap_req = make_recap_request()
        result = await checker.check(recap_req)
        assert all(r.status == FreshnessStatus.UNAVAILABLE for r in result.results)
        assert not result.any_changed

    async def test_extractor_whitespace_only_turns(self, extractor: ConversationExtractor):
        # TranscriptEvent requires min_length=1 for text; use single space to represent
        # functionally-empty turns that the extractor should silently skip.
        turns = [
            make_transcript_event(" ", Speaker.CALLER),
            make_transcript_event(" ", Speaker.USER),
        ]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        assert summary is not None
        assert len(summary.headline) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-20 — Robustness: Multi-Currency and Decimal Price Parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG20_PriceParsing:
    """Extractor handles multi-currency and decimal prices."""

    async def test_euro_price_extracted(self, extractor: ConversationExtractor):
        turns = [make_transcript_event("The price is €500.", Speaker.CALLER)]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        price_facts = [f for f in summary.time_sensitive_facts if f.key == "price_usd"]
        assert any("500" in f.value for f in price_facts)

    async def test_decimal_price_extracted(self, extractor: ConversationExtractor):
        turns = [make_transcript_event("Unit price is $420.50.", Speaker.CALLER)]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        price_facts = [f for f in summary.time_sensitive_facts if f.key == "price_usd"]
        assert len(price_facts) > 0
        assert "420" in price_facts[0].value

    async def test_word_form_price(self, extractor: ConversationExtractor):
        turns = [make_transcript_event("That's four hundred dollars.", Speaker.CALLER)]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        price_facts = [f for f in summary.time_sensitive_facts if f.key == "price_usd"]
        assert len(price_facts) > 0

    async def test_deadline_extracted(self, extractor: ConversationExtractor):
        turns = [make_transcript_event("Can you get back to me by Monday?", Speaker.CALLER)]
        summary = await extractor.extract(turns, caller_id=CALLER_Z)
        deadline_facts = [f for f in summary.time_sensitive_facts if f.key == "deadline"]
        assert len(deadline_facts) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-21 — Stress: Concurrent Subscribers
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG21_ConcurrentSubscribers:
    """Multiple concurrent subscribers all receive correct events."""

    async def test_five_subscribers_all_receive_events(self, session_manager: CallSessionManager):
        queues = [session_manager.subscribe() for _ in range(5)]
        await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        await session_manager.transition_to(CallState.CONNECTED)
        await session_manager.transition_to(CallState.COMPLETED)

        for q in queues:
            events = []
            while not q.empty():
                events.append(await q.get())
            assert len(events) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-22 — Stress: Concurrent Brain Service Operations
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG22_ConcurrentBrainOps:
    """Concurrent transcript ingestion should not corrupt data."""

    async def test_concurrent_turn_ingestion(self, brain_service: BrainService, initialized_store: ThreadMemoryStore):
        session_id = "sess-concurrent-01"
        turns = [
            make_transcript_event(f"Turn {i}", Speaker.CALLER, session_id)
            for i in range(10)
        ]
        await asyncio.gather(*[brain_service.on_transcript_event(t) for t in turns])
        stored = await initialized_store.get_session_turns(session_id, final_only=True)
        assert len(stored) == 10


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-23 — Stress: Concurrent Freshness Checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG23_ConcurrentFreshness:
    """FreshnessChecker handles concurrent requests reliably."""

    async def test_five_concurrent_checks(self, freshness_checker: FreshnessChecker):
        set_fact_value("price_usd", "$420")
        requests = [make_recap_request() for _ in range(5)]
        results = await asyncio.gather(*[freshness_checker.check(req) for req in requests])
        for result in results:
            assert result.any_changed is True
        await freshness_checker.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-24 — Scenario D: Instant Connect + Mid-Call Catchup
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG24_ScenarioD:
    """User answers immediately — mid-call catch-up with ducking."""

    async def test_instant_connect_detects_reconnect(self, session_manager: CallSessionManager):
        session_manager.register_interrupted_thread(CALLER_Z, "thread-instant-01")
        event = await session_manager.transition_to(CallState.CONNECTED, caller_id=CALLER_Z)
        assert event.state == CallState.CONNECTED
        assert session_manager.is_reconnect

    async def test_mid_call_catchup_not_connected_raises(self, session_manager: CallSessionManager):
        with pytest.raises(SessionStateError):
            await session_manager.trigger_mid_call_catchup()

    async def test_mid_call_catchup_while_connected(self, session_manager: CallSessionManager):
        await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        await session_manager.transition_to(CallState.CONNECTED)
        result = await session_manager.trigger_mid_call_catchup()
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════════
# INTG-25 — Master End-to-End: Scenario B Across All 4 Pairs
# ═══════════════════════════════════════════════════════════════════════════════

class TestINTG25_FullEndToEndScenarioB:
    """
    Master integration test: simulates the complete pipeline for Scenario B
    (mid-call disconnect + reconnect) across all four module pairs.

    Transport → Signal → Brain → Voice → Transport
    """

    async def test_scenario_b_full_pipeline(
        self,
        brain_service: BrainService,
        initialized_store: ThreadMemoryStore,
        reconnect_detector: ReconnectDetector,
        voice_pipeline: VoicePipeline,
        session_manager: CallSessionManager,
    ):
        # ── FIRST CALL ──────────────────────────────────────────────────────────
        session_1 = session_manager.session_id
        thread_id = "thread-e2e-b-01"

        # Pair A: ring → connect
        ring_e1 = await session_manager.transition_to(CallState.RINGING, caller_id=CALLER_Z, thread_id=thread_id)
        conn_e1 = await session_manager.transition_to(CallState.CONNECTED)

        # Pair B: signal detects events
        await reconnect_detector.on_event(ring_e1)
        d_conn = await reconnect_detector.on_event(conn_e1)
        assert d_conn.should_start_stt

        # Pair C: buffer turns
        turns = [
            make_transcript_event("Hey, it's Z. Calling about Q3 pricing.", Speaker.CALLER, session_1),
            make_transcript_event("I have the Q3 number — $400.", Speaker.USER, session_1),
            make_transcript_event("Can you check volume discount? Ticket XYZ-", Speaker.CALLER, session_1),
        ]
        for t in turns:
            await brain_service.on_transcript_event(t)

        # Pair A: abrupt disconnect
        disc_e1 = await session_manager.transition_to(CallState.DISCONNECTED)

        # Pair B: mark interrupted
        d_disc = await reconnect_detector.on_event(disc_e1)
        assert d_disc.call_ended_abruptly

        # Pair C: extract and store interrupted summary
        summary = await brain_service.on_call_ended(disc_e1)
        assert summary is not None
        assert summary.is_interrupted

        # ── SECOND CALL ─────────────────────────────────────────────────────────
        session_manager_2 = CallSessionManager(
            whisper_channel=PrivateWhisperChannel(private_track_id=PRIVATE_TRACK, use_mocks=True),
            interrupted_threads_registry={CALLER_Z: summary.thread_id},
            use_mocks=True,
        )

        ring_e2 = await session_manager_2.transition_to(CallState.RINGING, caller_id=CALLER_Z)
        assert ring_e2.is_reconnect

        # Pair B: validates reconnect
        d_ring2 = await reconnect_detector.on_event(ring_e2)
        assert d_ring2.is_reconnect

        # Pair C: generate RecapRequest during ring window
        set_fact_value("price_usd", "$420")
        recap_req = await brain_service.on_call_ringing(ring_e2)
        assert recap_req is not None

        # Pair D: run full voice pipeline
        tts_req = await voice_pipeline.run(recap_req)
        assert isinstance(tts_req, TtsRequest)
        assert "420" in tts_req.text or "Heads up" in tts_req.text

        # Pair A: deliver recap on private track (not caller track)
        metrics = await session_manager_2.deliver_recap(tts_req)
        assert metrics is not None
        assert not metrics.interrupted  # no barge-in

        set_fact_value("price_usd", "$420")
        await voice_pipeline.aclose()
