"""
modules/brain/recap.py
----------------------
Recap Generator for Pair C (Brain).

Builds a RecapRequest from a stored ThreadSummary, calculating urgency from
the estimated ring window and selecting time-sensitive facts for Pair D
(Voice & Facts) to verify against live data.

Robustness enhancements:
  - Guard against negative, zero, or excessively large ring windows
  - Null-safe fact list handling
  - Automatic fallback urgency
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.schemas import (
    RecapRequest,
    RecapUrgency,
    ThreadSummary,
    TimeSensitiveFact,
)


def determine_urgency(
    estimated_ring_window_seconds: Optional[float | str] = None,
) -> RecapUrgency:
    """
    Determine recap compression urgency based on available ring time.

    - <= 6s or negative/zero: HEADLINE_ONLY (extremely brief)
    - 6s < time <= 20s: STANDARD (normal ring buffer)
    - > 20s: EXTENDED (long ring buffer, more context)
    """
    if estimated_ring_window_seconds is None:
        return RecapUrgency.STANDARD

    try:
        sec = float(estimated_ring_window_seconds)
    except (TypeError, ValueError):
        return RecapUrgency.STANDARD

    if sec <= 6.0:
        return RecapUrgency.HEADLINE_ONLY
    elif sec <= 20.0:
        return RecapUrgency.STANDARD
    else:
        return RecapUrgency.EXTENDED


def build_recap_request(
    summary: ThreadSummary,
    session_id: str,
    estimated_ring_window_seconds: Optional[float | str] = 20.0,
    force_verify_all_facts: bool = True,
) -> RecapRequest:
    """
    Construct a validated RecapRequest to be sent to Pair D (Voice & Facts).

    Args:
        summary: The ThreadSummary retrieved from ThreadMemoryStore.
        session_id: Current incoming call session ID.
        estimated_ring_window_seconds: Ring window length estimated by Transport.
        force_verify_all_facts: If True, include all time_sensitive_facts
                                for the FreshnessChecker to verify.
    """
    urgency = determine_urgency(estimated_ring_window_seconds)

    # In HEADLINE_ONLY, if not forcing verification, we can omit facts to minimize latency
    if urgency == RecapUrgency.HEADLINE_ONLY and not force_verify_all_facts:
        facts_to_verify: list[TimeSensitiveFact] = []
    else:
        facts_to_verify = list(summary.time_sensitive_facts or [])

    safe_window = (
        max(0.0, float(estimated_ring_window_seconds))
        if estimated_ring_window_seconds is not None
        else None
    )

    return RecapRequest(
        request_id=str(uuid.uuid4()),
        session_id=session_id,
        thread_id=summary.thread_id,
        summary=summary,
        facts_to_verify=facts_to_verify,
        urgency=urgency,
        estimated_ring_window_seconds=safe_window,
        created_at=datetime.now(tz=timezone.utc),
    )
