"""
recap_request.py
----------------
Contract: Brain (Pair C) → Voice & Facts (Pair D)

Fired when the Reconnect Detector (Pair B) emits is_reconnect=True on a
CallStateEvent, initiating the pre-answer recap sequence.

Timing constraint (from blueprint):
    The recap must begin speaking within the first 1–2 rings of the call.
    Brain should pre-compute and emit this request as soon as a RINGING +
    is_reconnect=True event arrives — don't wait for the call to be CONNECTED.

Voice & Facts will:
  1. Pass time_sensitive_facts to the Fact-Freshness Checker.
  2. Combine the ThreadSummary + FreshnessResult → final recap text.
  3. Hand the text to Rime TTS for synthesis on the private track.

DO NOT change this schema without a heads-up in the group chat first.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .thread_summary import ThreadSummary, TimeSensitiveFact


class RecapUrgency(str, Enum):
    """
    How aggressively Voice & Facts should compress the recap.

    Driven by how many rings have already elapsed (estimated by Transport).
    """

    HEADLINE_ONLY = "HEADLINE_ONLY"
    """Ring window is very short (≤ 1 ring elapsed). Speak only the headline."""

    STANDARD = "STANDARD"
    """Normal ring window (2–3 rings). Headline + key details."""

    EXTENDED = "EXTENDED"
    """Long ring window (4+ rings / user hasn't answered). Full recap with freshness flag."""


class RecapRequest(BaseModel):
    """
    Request from Brain to Voice & Facts to produce and speak a recap.

    Brain populates this from the latest ThreadSummary and emits it on the
    message bus as soon as a reconnect is detected during RINGING.
    """

    request_id: str = Field(
        ...,
        description="Unique ID for this recap request (UUID4). "
        "Used to correlate the TtsRequest that comes back.",
    )
    session_id: str = Field(
        ...,
        description="Call session ID — same as CallStateEvent.session_id.",
    )
    thread_id: str = Field(
        ...,
        description="Thread ID this recap is for.",
    )

    # ── Summary data ──────────────────────────────────────────────────────────
    summary: ThreadSummary = Field(
        ...,
        description="The latest ThreadSummary from Brain.",
    )
    facts_to_verify: list[TimeSensitiveFact] = Field(
        default_factory=list,
        description=(
            "Subset of summary.time_sensitive_facts that the Fact-Freshness "
            "Checker should re-verify before speaking. Brain decides which facts "
            "are worth verifying based on age (last_updated_at vs. now)."
        ),
    )

    # ── Delivery context ──────────────────────────────────────────────────────
    urgency: RecapUrgency = Field(
        RecapUrgency.STANDARD,
        description="How much time Voice & Facts has to generate and stream the recap.",
    )
    estimated_ring_window_seconds: Optional[float] = Field(
        None,
        ge=0.0,
        description=(
            "Transport's best estimate of how long the ring window will last. "
            "Voice & Facts uses this to decide how much content to include."
        ),
    )

    created_at: datetime = Field(
        ...,
        description="UTC timestamp when Brain emitted this request.",
    )

    model_config = {"frozen": True}
