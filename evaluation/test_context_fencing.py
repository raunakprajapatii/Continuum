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
@pytest.mark.skip(reason="Stub — implement in Pair C + D integration sprint")
async def test_recap_contains_only_correct_thread_content(
    mock_brain_request,
) -> None:
    """
    Verify that a recap generated for thread Z contains no content
    from a concurrent thread Y.

    Implementation approach (Pair C + D):
      1. Seed the Thread Memory Store with two separate ThreadSummary objects
         (thread Z and thread Y).
      2. Trigger a recap for thread Z.
      3. Inspect the generated recap text for any keyword from thread Y's summary.
      4. Assert zero leakage.
    """
    # ── Arrange ──────────────────────────────────────────────────────────────
    recap_request = mock_brain_request  # RecapRequest for thread Z

    # Simulated recap text (replace with real Recap Generator output when available)
    simulated_recap_text = (
        "Z wanted the Q3 number; you said you'd check with finance. "
        "Heads up — the price was four hundred dollars, it's now four twenty. "
        "Your open item: loop in finance on volume discounts."
    )

    # ── Assert no Y-thread leakage ────────────────────────────────────────────
    recap_lower = simulated_recap_text.lower()
    leaked_keywords = [kw for kw in _Y_THREAD_KEYWORDS if kw.lower() in recap_lower]

    result = {
        "test": "context_fencing",
        "thread_id": recap_request.thread_id,
        "leaked_keywords": leaked_keywords,
        "pass": len(leaked_keywords) == 0,
    }

    ARTIFACT.write_text(json.dumps(result, indent=2))

    assert len(leaked_keywords) == 0, (
        f"Cross-thread leakage detected! "
        f"Y-thread keywords found in Z's recap: {leaked_keywords}. "
        f"Recap text: {simulated_recap_text!r}"
    )
