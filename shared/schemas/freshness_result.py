"""
freshness_result.py
--------------------
Contract: Internal to Voice & Facts (Pair D)

Produced by the Fact-Freshness Checker after querying the mock / live data
source for each TimeSensitiveFact in a RecapRequest.

The Recap Generator (also in Pair D) merges this into the recap text:
  - If a fact changed → insert a freshness flag ("Heads up — X is now Y").
  - If a fact is unchanged → include it normally.
  - If the lookup failed → include the cached value with a caveat.

This schema does NOT cross a pair boundary directly, but it IS part of the
shared definition because the mock_brain (Pair C's mock, used by D) needs to
produce RecapRequests with facts_to_verify that match real FreshnessResult keys.

DO NOT change this schema without a heads-up in the group chat first.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FreshnessStatus(str, Enum):
    """Outcome of a single fact-freshness lookup."""

    UNCHANGED = "UNCHANGED"
    """The live value matches what was recorded in the thread."""

    CHANGED = "CHANGED"
    """The live value differs from what was recorded. Recap must flag this."""

    UNAVAILABLE = "UNAVAILABLE"
    """The data source returned an error or timed out.
    Recap should use the cached value with a spoken caveat."""


class FactCheckResult(BaseModel):
    """Result for a single TimeSensitiveFact lookup."""

    key: str = Field(..., description="Matches TimeSensitiveFact.key.")
    label: str = Field(..., description="Human-readable label for this fact.")
    cached_value: str = Field(
        ..., description="The value stored in the thread (may be stale)."
    )
    live_value: Optional[str] = Field(
        None,
        description="The value returned by the live/mock data source. "
        "None if status=UNAVAILABLE.",
    )
    status: FreshnessStatus = Field(..., description="Outcome of the freshness check.")
    checked_at: datetime = Field(
        ..., description="UTC timestamp when the lookup completed."
    )
    latency_ms: int = Field(
        ...,
        ge=0,
        description="Round-trip time of the data-source call in milliseconds. "
        "Logged to RIME_EVIDENCE.md.",
    )

    @property
    def spoken_flag(self) -> Optional[str]:
        """
        Ready-to-insert spoken flag text if the fact changed.

        Formatted per Rime prompting guide rule 5:
            "Heads up -- [old value] is now [new value]."
        Returns None if no flag is needed.
        """
        if self.status == FreshnessStatus.CHANGED and self.live_value is not None:
            return (
                f"Heads up — {self.label} was {self.cached_value}, "
                f"it's now {self.live_value}."
            )
        if self.status == FreshnessStatus.UNAVAILABLE:
            return (
                f"I couldn't verify {self.label} — "
                f"the last figure was {self.cached_value}."
            )
        return None


class FreshnessResult(BaseModel):
    """
    Aggregated results from the Fact-Freshness Checker for one RecapRequest.
    """

    request_id: str = Field(
        ...,
        description="Matches RecapRequest.request_id for correlation.",
    )
    thread_id: str = Field(..., description="Thread ID this result belongs to.")
    results: list[FactCheckResult] = Field(
        default_factory=list,
        description="One entry per fact that was checked.",
    )
    any_changed: bool = Field(
        False,
        description=(
            "True if at least one fact changed. Convenience flag for the Recap "
            "Generator — avoids iterating results just to answer 'anything changed?'"
        ),
    )
    completed_at: datetime = Field(
        ...,
        description="UTC timestamp when all checks completed.",
    )

    model_config = {"frozen": True}
