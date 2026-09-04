"""
evaluation/test_context_fencing.py
------------------------------------
Acceptance Test 3 — Context fencing

Blueprint § 13:
    Procedure: Run two simulated threads (Z and a second contact) in parallel;
               verify recap for Z never includes content from the other thread.
    Pass:      Zero cross-thread leakage in transcript review.

Evidence artifact: evaluation/artifacts/context_fencing.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.schemas import ThreadSummary

ARTIFACT = Path(__file__).parent / "artifacts" / "context_fencing.json"

# ── Scripted thread data ───────────────────────────────────────────────────────

_Z_THREAD_KEYWORDS = {"Q3", "finance", "volume discounts", "price", "400", "420"}
_Y_THREAD_KEYWORDS = {"project", "deadline", "contract", "legal", "Friday"}


@pytest.mark.asyncio
async def test_recap_contains_only_correct_thread_content(
    tmp_path,
) -> None:
    """
    Verify that a recap generated for thread Z contains no content
    from a concurrent thread Y using the real ThreadMemoryStore and BrainService.
    """
    from datetime import datetime, timezone
    from modules.brain import BrainService, ThreadMemoryStore
    from shared.schemas import (
        CallState,
        CallStateEvent,
        Commitment,
        ThreadSummary,
        TimeSensitiveFact,
    )

    db_file = str(tmp_path / "test_continuum.db")
    store = ThreadMemoryStore(db_path=db_file)
    service = BrainService(store=store)
    await service.init()

    now = datetime.now(tz=timezone.utc)

    # 1. Seed Thread Z (Caller Z)
    summary_z = ThreadSummary(
        thread_id="thread_Z_123",
        caller_id="+15550000001",
        caller_name="Z",
        headline="Z wanted the Q3 number; you said you'd check with finance.",
        open_items=["Check with finance team on volume discounts"],
        commitments=[
            Commitment(
                owner="user",
                text="Loop in finance today and get back to Z on volume discounts.",
                is_resolved=False,
            )
        ],
        time_sensitive_facts=[
            TimeSensitiveFact(
                key="price_usd",
                label="Unit price",
                value="$400",
                recorded_at=now,
            )
        ],
        key_names=["Z", "Q3", "finance"],
        last_spoken_turn_text="Also, ticket XYZ-",
        created_at=now,
        last_updated_at=now,
        last_call_ended_at=now,
        is_interrupted=True,
        call_count=1,
    )
    await store.save_summary(summary_z)

    # 2. Seed Thread Y (Caller Y with totally separate topics)
    summary_y = ThreadSummary(
        thread_id="thread_Y_456",
        caller_id="+15550000002",
        caller_name="Y",
        headline="Y discussed the project contract deadline with legal for Friday.",
        open_items=["Review contract before Friday deadline"],
        commitments=[
            Commitment(
                owner="user",
                text="Send contract to legal team by Thursday.",
                is_resolved=False,
            )
        ],
        time_sensitive_facts=[
            TimeSensitiveFact(
                key="contract_deadline",
                label="Contract deadline",
                value="Friday 5pm",
                recorded_at=now,
            )
        ],
        key_names=["Y", "project", "contract", "legal", "Friday"],
        created_at=now,
        last_updated_at=now,
        last_call_ended_at=now,
        is_interrupted=False,
        call_count=1,
    )
    await store.save_summary(summary_y)

    # 3. Trigger reconnect recap for Caller Z
    ring_event_z = CallStateEvent(
        event_id="evt_ring_z",
        session_id="session_z_new",
        state=CallState.RINGING,
        caller_id="+15550000001",
        caller_name="Z",
        is_reconnect=True,
        estimated_ring_window_seconds=18.0,
        timestamp=now,
    )

    recap_request_z = await service.on_call_ringing(ring_event_z)
    assert recap_request_z is not None, "BrainService should emit a RecapRequest for reconnecting caller Z"
    assert recap_request_z.thread_id == "thread_Z_123"

    # 4. Assert zero leakage of Y-thread keywords into Z's recap summary or facts
    z_content = " ".join([
        recap_request_z.summary.headline,
        " ".join(recap_request_z.summary.open_items),
        " ".join(c.text for c in recap_request_z.summary.commitments),
        " ".join(f.value for f in recap_request_z.facts_to_verify),
    ]).lower()

    leaked_keywords = [kw for kw in _Y_THREAD_KEYWORDS if kw.lower() in z_content]

    result = {
        "test": "context_fencing",
        "thread_id": recap_request_z.thread_id,
        "leaked_keywords": leaked_keywords,
        "pass": len(leaked_keywords) == 0,
    }

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(result, indent=2))

    assert len(leaked_keywords) == 0, (
        f"Cross-thread leakage detected! "
        f"Y-thread keywords found in Z's recap: {leaked_keywords}. "
        f"Content inspected: {z_content!r}"
    )
