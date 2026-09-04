"""
mocks/mock_brain.py
--------------------
Pair C (Brain) mock — used by Pair D (Voice & Facts) during development.

Returns a deterministic RecapRequest instantly without requiring a running
Thread Memory Store or LLM. The request mirrors Scenario C from the blueprint
(reconnect next day, $400 price that the freshness check will find is now $420).

Usage:
    from mocks.mock_brain import make_recap_request

    request = make_recap_request()  # RecapRequest
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from shared.schemas import (
    Commitment,
    RecapRequest,
    RecapUrgency,
    ThreadSummary,
    TimeSensitiveFact,
)

from .mock_call_session import MOCK_CALLER_ID, MOCK_SESSION_ID, MOCK_THREAD_ID

# ── Canned ThreadSummary (what Brain would have persisted after the first call) ──

_MOCK_SUMMARY = ThreadSummary(
    thread_id=MOCK_THREAD_ID,
    caller_id=MOCK_CALLER_ID,
    caller_name="Z",
    headline="Z wanted the Q3 number; you said you'd check with finance.",
    open_items=[
        "Check with finance team on volume discounts",
        "Follow up on ticket XYZ (Z was mid-sentence when call dropped)",
    ],
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
            recorded_at=datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc),
        )
    ],
    key_names=["Z", "Q3", "finance"],
    last_spoken_turn_text="Also, ticket XYZ-",
    created_at=datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc),
    last_updated_at=datetime(2026, 9, 3, 10, 15, 0, tzinfo=timezone.utc),
    last_call_ended_at=datetime(2026, 9, 3, 10, 15, 0, tzinfo=timezone.utc),
    is_interrupted=True,
    call_count=1,
)


def make_recap_request(
    urgency: RecapUrgency = RecapUrgency.STANDARD,
    estimated_ring_window_seconds: float = 20.0,
) -> RecapRequest:
    """
    Return a deterministic RecapRequest that Pair D can build against.

    The price_usd fact ($400) is included in facts_to_verify so the
    FreshnessChecker will query the mock API and discover it's now $420.
    """
    summary = _MOCK_SUMMARY.model_copy(deep=True)
    return RecapRequest(
        request_id=str(uuid.uuid4()),
        session_id=MOCK_SESSION_ID,
        thread_id=MOCK_THREAD_ID,
        summary=summary,
        facts_to_verify=list(summary.time_sensitive_facts),
        urgency=urgency,
        estimated_ring_window_seconds=estimated_ring_window_seconds,
        created_at=datetime.now(tz=timezone.utc),
    )
