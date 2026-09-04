"""
evaluation/test_brain_module.py
-------------------------------
Robustness, edge-case, and stress test suite for Pair C (Brain) module:
  - ThreadMemoryStore (WAL mode, shared in-memory URI, corrupted data resilience, CRUD)
  - ConversationExtractor (Rime compliance <=20 words, multi-currency/decimals, empty turns, pronoun resolution)
  - RecapGenerator (extreme/invalid ring windows, null safety, urgency bands)
  - BrainService (lifecycle, multi-call thread evolution, error shielding)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest
import aiosqlite

from mocks.mock_stt import SCRIPTED_TURNS
from modules.brain import (
    BrainService,
    ConversationExtractor,
    ThreadMemoryStore,
    build_recap_request,
    determine_urgency,
)
from shared.schemas import (
    CallState,
    CallStateEvent,
    Commitment,
    RecapUrgency,
    Speaker,
    ThreadSummary,
    TimeSensitiveFact,
    TranscriptEvent,
)


# ── ThreadMemoryStore Robustness Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_thread_memory_store_crud(tmp_path):
    """Verify ThreadMemoryStore saves, queries, and updates ThreadSummary."""
    db_file = str(tmp_path / "brain_crud.db")
    store = ThreadMemoryStore(db_path=db_file)
    await store.init_db()

    now = datetime.now(tz=timezone.utc)
    summary = ThreadSummary(
        thread_id="t_001",
        caller_id="+15551234567",
        caller_name="Alice",
        headline="Alice discussed project roadmap.",
        open_items=["Send proposal"],
        commitments=[Commitment(owner="user", text="Send proposal by EOD", is_resolved=False)],
        time_sensitive_facts=[
            TimeSensitiveFact(key="budget", label="Budget", value="$50,000", recorded_at=now)
        ],
        key_names=["Alice", "Roadmap"],
        created_at=now,
        last_updated_at=now,
        is_interrupted=False,
        call_count=1,
    )

    await store.save_summary(summary)

    # Fetch by thread_id
    by_thread = await store.get_summary_by_thread_id("t_001")
    assert by_thread is not None
    assert by_thread.caller_name == "Alice"
    assert by_thread.headline == "Alice discussed project roadmap."

    # Fetch by caller_id
    by_caller = await store.get_summary_by_caller("+15551234567")
    assert by_caller is not None
    assert by_caller.thread_id == "t_001"

    # List summaries
    all_summaries = await store.list_summaries()
    assert len(all_summaries) >= 1
    assert any(s.thread_id == "t_001" for s in all_summaries)

    # Delete summary
    deleted = await store.delete_summary("t_001")
    assert deleted is True
    assert await store.get_summary_by_thread_id("t_001") is None


@pytest.mark.asyncio
async def test_in_memory_store_shared_cache():
    """Verify that ':memory:' uses shared cache and persists across connection openings."""
    store = ThreadMemoryStore(db_path=":memory:")
    await store.init_db()

    now = datetime.now(tz=timezone.utc)
    summary = ThreadSummary(
        thread_id="t_mem_1",
        caller_id="+15559998888",
        caller_name="MemUser",
        headline="Testing in-memory persistence across connections.",
        created_at=now,
        last_updated_at=now,
    )

    await store.save_summary(summary)

    # Next call opens a separate connection under the hood
    fetched = await store.get_summary_by_caller("+15559998888")
    assert fetched is not None
    assert fetched.thread_id == "t_mem_1"


@pytest.mark.asyncio
async def test_store_corrupted_json_defense(tmp_path):
    """Verify store handles corrupted JSON gracefully without crashing."""
    db_file = str(tmp_path / "corrupted.db")
    store = ThreadMemoryStore(db_path=db_file)
    await store.init_db()

    # Manually insert invalid JSON into the table
    async with aiosqlite.connect(db_file) as db:
        await db.execute(
            """
            INSERT INTO thread_summaries (thread_id, caller_id, caller_name, summary_json, last_updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("t_corrupt", "+1000", "Bad", "{not valid json at all", datetime.now(tz=timezone.utc).isoformat()),
        )
        await db.commit()

    # Querying should log warning and return None, not raise exception
    res = await store.get_summary_by_thread_id("t_corrupt")
    assert res is None

    # List summaries should skip corrupted row
    all_res = await store.list_summaries()
    assert not any(s.thread_id == "t_corrupt" for s in all_res)


@pytest.mark.asyncio
async def test_turn_buffering_and_ordering(tmp_path):
    """Verify session turns are buffered, filtered by finality, and retrieved in order."""
    db_file = str(tmp_path / "turns.db")
    store = ThreadMemoryStore(db_path=db_file)
    await store.init_db()

    session_id = "sess_test_1"
    now = datetime.now(tz=timezone.utc)

    turn1 = TranscriptEvent(
        event_id="e1",
        session_id=session_id,
        speaker=Speaker.CALLER,
        text="Hello there",
        is_final=True,
        start_ms=0,
        timestamp=now,
    )
    turn2 = TranscriptEvent(
        event_id="e2",
        session_id=session_id,
        speaker=Speaker.USER,
        text="Hi, I am",
        is_final=False,
        start_ms=1000,
        timestamp=now,
    )
    turn3 = TranscriptEvent(
        event_id="e3",
        session_id=session_id,
        speaker=Speaker.USER,
        text="Hi, I am available.",
        is_final=True,
        start_ms=1200,
        timestamp=now,
    )

    await store.append_turn(session_id, turn1)
    await store.append_turn(session_id, turn2)
    await store.append_turn(session_id, turn3)

    final_turns = await store.get_session_turns(session_id, final_only=True)
    assert len(final_turns) == 2
    assert final_turns[0].text == "Hello there"
    assert final_turns[1].text == "Hi, I am available."

    await store.clear_session_turns(session_id)
    cleared = await store.get_session_turns(session_id, final_only=False)
    assert len(cleared) == 0


# ── ConversationExtractor Robustness Tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_extractor_on_scripted_conversation():
    """Verify ConversationExtractor processes scripted turns and extracts facts."""
    extractor = ConversationExtractor()

    now = datetime.now(tz=timezone.utc)
    turns: list[TranscriptEvent] = []
    elapsed_ms = 0
    for idx, (speaker, text, pause_sec) in enumerate(SCRIPTED_TURNS):
        turns.append(
            TranscriptEvent(
                event_id=f"turn_{idx}",
                session_id="mock_session",
                speaker=speaker,
                text=text,
                is_final=True,
                start_ms=elapsed_ms,
                timestamp=now,
            )
        )
        elapsed_ms += int(pause_sec * 1000)

    summary = await extractor.extract(
        turns=turns,
        caller_id="+15551234567",
        caller_name="Z",
        thread_id="thread_mock",
        is_interrupted=True,
    )

    # 1. Headline validation (Rime compliance: <= 20 words)
    assert len(summary.headline.split()) <= 20
    assert "Z" in summary.headline

    # 2. Time-sensitive fact ($400)
    price_fact = next((f for f in summary.time_sensitive_facts if f.key == "price_usd"), None)
    assert price_fact is not None, "price_usd must be extracted from transcript"
    assert "$400" in price_fact.value

    # 3. Interrupted turn text preserved
    assert summary.is_interrupted is True
    assert summary.last_spoken_turn_text == "Perfect. Also, ticket XYZ-"

    # 4. Commitments
    assert len(summary.commitments) > 0
    assert any("finance" in c.text.lower() for c in summary.commitments)


@pytest.mark.asyncio
async def test_extractor_empty_and_whitespace_turns():
    """Verify extractor safely handles empty turns or whitespace-only utterances."""
    extractor = ConversationExtractor()

    # Completely empty list
    summary_empty = await extractor.extract(
        turns=[],
        caller_id="+15550001111",
        caller_name="Ghost",
        is_interrupted=False,
    )
    assert summary_empty is not None
    assert summary_empty.caller_name == "Ghost"
    assert len(summary_empty.headline.split()) <= 20

    # Whitespace turns
    now = datetime.now(tz=timezone.utc)
    ws_turns = [
        TranscriptEvent(event_id="w1", session_id="s_ws", speaker=Speaker.CALLER, text="   ", start_ms=0, timestamp=now),
        TranscriptEvent(event_id="w2", session_id="s_ws", speaker=Speaker.USER, text=" ", start_ms=500, timestamp=now),
    ]
    summary_ws = await extractor.extract(
        turns=ws_turns,
        caller_id="+15550001111",
        is_interrupted=False,
    )
    assert summary_ws is not None


@pytest.mark.asyncio
async def test_extractor_decimal_prices_and_deadlines():
    """Verify extractor captures decimal prices ($420.50) and deadlines."""
    extractor = ConversationExtractor()
    now = datetime.now(tz=timezone.utc)

    turns = [
        TranscriptEvent(
            event_id="t1",
            session_id="s1",
            speaker=Speaker.CALLER,
            text="The adjusted unit price is $420.50 as of today.",
            start_ms=0,
            timestamp=now,
        ),
        TranscriptEvent(
            event_id="t2",
            session_id="s1",
            speaker=Speaker.USER,
            text="Understood. I will submit the paperwork by Friday.",
            start_ms=1000,
            timestamp=now,
        ),
    ]

    summary = await extractor.extract(turns=turns, caller_id="+15552223333", caller_name="Bob")

    price_fact = next((f for f in summary.time_sensitive_facts if f.key == "price_usd"), None)
    assert price_fact is not None
    assert price_fact.value == "$420.50"

    deadline_fact = next((f for f in summary.time_sensitive_facts if f.key == "deadline"), None)
    assert deadline_fact is not None
    assert "Friday" in deadline_fact.value

    # Commitment detected
    assert len(summary.commitments) == 1
    assert "submit the paperwork" in summary.commitments[0].text


# ── RecapGenerator Tests ──────────────────────────────────────────────────────

def test_recap_urgency_and_extreme_windows():
    """Verify urgency logic handles normal, boundary, and extreme/invalid ring windows."""
    assert determine_urgency(0.0) == RecapUrgency.HEADLINE_ONLY
    assert determine_urgency(-5.0) == RecapUrgency.HEADLINE_ONLY
    assert determine_urgency(5.0) == RecapUrgency.HEADLINE_ONLY
    assert determine_urgency(6.0) == RecapUrgency.HEADLINE_ONLY
    assert determine_urgency(6.1) == RecapUrgency.STANDARD
    assert determine_urgency(20.0) == RecapUrgency.STANDARD
    assert determine_urgency(20.1) == RecapUrgency.EXTENDED
    assert determine_urgency(None) == RecapUrgency.STANDARD
    assert determine_urgency("invalid") == RecapUrgency.STANDARD

    now = datetime.now(tz=timezone.utc)
    summary = ThreadSummary(
        thread_id="t_1",
        caller_id="+100",
        caller_name="Z",
        headline="Z wanted the Q3 number; you said you'd check with finance.",
        time_sensitive_facts=[
            TimeSensitiveFact(key="price_usd", label="Price", value="$400", recorded_at=now)
        ],
        created_at=now,
        last_updated_at=now,
    )

    req = build_recap_request(summary, session_id="s_1", estimated_ring_window_seconds=-10.0)
    assert req.urgency == RecapUrgency.HEADLINE_ONLY
    assert req.estimated_ring_window_seconds == 0.0  # Clamped to min 0.0

    req_invalid = build_recap_request(summary, session_id="s_2", estimated_ring_window_seconds="invalid")
    assert req_invalid.urgency == RecapUrgency.STANDARD
    assert req_invalid.estimated_ring_window_seconds is None


# ── BrainService Full Call Cycle & Thread Evolution Tests ────────────────────

@pytest.mark.asyncio
async def test_brain_service_full_call_cycle(tmp_path):
    """
    Test full cycle:
    1. Incoming call turns streamed into Brain
    2. Call abruptly disconnects -> summary saved
    3. Returning call arrives (is_reconnect=True) -> RecapRequest generated
    """
    db_file = str(tmp_path / "cycle.db")
    store = ThreadMemoryStore(db_path=db_file)
    service = BrainService(store=store)
    await service.init()

    caller_id = "+15559876543"
    session_id = "sess_call_1"
    now = datetime.now(tz=timezone.utc)

    # 1. Stream turns
    for idx, (speaker, text, pause) in enumerate(SCRIPTED_TURNS):
        event = TranscriptEvent(
            event_id=f"evt_{idx}",
            session_id=session_id,
            speaker=speaker,
            text=text,
            is_final=True,
            start_ms=idx * 1000,
            timestamp=now,
        )
        await service.on_transcript_event(event)

    # 2. Call disconnects abruptly
    disconnect_event = CallStateEvent(
        event_id="disc_1",
        session_id=session_id,
        state=CallState.DISCONNECTED,
        caller_id=caller_id,
        caller_name="Z",
        is_reconnect=False,
        timestamp=now,
    )
    saved_summary = await service.on_call_ended(disconnect_event)
    assert saved_summary is not None
    assert saved_summary.is_interrupted is True

    # 3. Next day / later: Reconnecting call arrives during RINGING
    reconnect_event = CallStateEvent(
        event_id="ring_2",
        session_id="sess_call_2",
        state=CallState.RINGING,
        caller_id=caller_id,
        is_reconnect=True,
        timestamp=now,
    )
    recap = await service.on_call_ringing(reconnect_event, estimated_ring_window_seconds=15.0)

    assert recap is not None
    assert recap.session_id == "sess_call_2"
    assert recap.summary.caller_id == caller_id
    assert any(f.key == "price_usd" for f in recap.facts_to_verify)


@pytest.mark.asyncio
async def test_multi_call_thread_evolution(tmp_path):
    """
    Verify that subsequent calls for the same caller evolve the thread summary:
    call_count increments, prices update, and interrupted flag resets on completion.
    """
    db_file = str(tmp_path / "evolution.db")
    store = ThreadMemoryStore(db_path=db_file)
    service = BrainService(store=store)
    await service.init()

    caller_id = "+15557778888"
    now = datetime.now(tz=timezone.utc)

    # --- CALL 1: Interrupted call discussing $400 ---
    await service.on_transcript_event(
        TranscriptEvent(event_id="c1_1", session_id="s1", speaker=Speaker.CALLER, text="Unit price is $400.", start_ms=0, timestamp=now)
    )
    sum1 = await service.on_call_ended(
        CallStateEvent(event_id="e1", session_id="s1", state=CallState.DISCONNECTED, caller_id=caller_id, caller_name="Eve", is_reconnect=False, timestamp=now)
    )
    assert sum1 is not None
    assert sum1.call_count == 1
    assert sum1.is_interrupted is True
    assert any(f.value == "$400" for f in sum1.time_sensitive_facts)

    # --- CALL 2: Follow-up call next day where price becomes $420.50 and completes normally ---
    await service.on_transcript_event(
        TranscriptEvent(event_id="c2_1", session_id="s2", speaker=Speaker.CALLER, text="Hey Eve, the price is now $420.50.", start_ms=0, timestamp=now)
    )
    sum2 = await service.on_call_ended(
        CallStateEvent(event_id="e2", session_id="s2", state=CallState.COMPLETED, caller_id=caller_id, caller_name="Eve", is_reconnect=True, timestamp=now)
    )
    assert sum2 is not None
    assert sum2.call_count == 2
    assert sum2.is_interrupted is False  # Completed normally
    # Fact was updated to the newer price
    price_fact = next((f for f in sum2.time_sensitive_facts if f.key == "price_usd"), None)
    assert price_fact is not None
    assert price_fact.value == "$420.50"


@pytest.mark.asyncio
async def test_service_error_shielding():
    """Verify that unexpected exceptions in subcomponents do not crash BrainService."""
    # Service with uninitialized or failing store
    service = BrainService(store=None, extractor=None)

    # Calling with malformed/None event should return None without raising unhandled exception
    res = await service.on_call_ringing(
        CallStateEvent(
            event_id="bad",
            session_id="bad",
            state=CallState.IDLE,  # Not ringing
            caller_id=None,
            is_reconnect=False,
            timestamp=datetime.now(tz=timezone.utc),
        )
    )
    assert res is None
