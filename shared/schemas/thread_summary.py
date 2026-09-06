"""
thread_summary.py
-----------------
Contract: Brain's (Pair C) internal state AND the output handed to Voice&Facts (Pair D)
          via recap_request.py.

This is the canonical "what do we know about this thread" object. Brain writes
it; Voice&Facts reads it (indirectly, inside a RecapRequest). It is persisted
to the Thread Memory Store (Postgres / SQLite) keyed by thread_id.

Design note from blueprint:
    "Persists a structured, continuously-updated summary per contact:
     open asks, commitments made, numbers/names/dates mentioned,
     last-updated timestamp. Not a raw transcript dump."

DO NOT store raw transcript text in this object. Summarise it.

DO NOT change this schema without a heads-up in the group chat first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Commitment(BaseModel):
    """A promise or action item from either party."""

    owner: str = Field(
        ...,
        description="Who made the commitment: 'user' or 'caller', or a name.",
    )
    text: str = Field(..., description="Plain-language description of the commitment.")
    is_resolved: bool = Field(
        False, description="True once the commitment has been fulfilled / acknowledged."
    )


class TimeSensitiveFact(BaseModel):
    """
    A fact that may go stale (price, count, status, deadline).

    The Fact-Freshness Checker (Pair D) uses this to know what to re-verify
    before the recap is spoken.
    """

    key: str = Field(
        ...,
        description=(
            "Stable machine-readable key for this fact (e.g. 'price_usd', "
            "'ticket_status', 'inventory_count'). Used as the lookup key in the "
            "mock / live data API."
        ),
    )
    label: str = Field(
        ...,
        description="Human-readable label (e.g. 'Unit price', 'Ticket #XYZ status').",
    )
    value: str = Field(
        ...,
        description="The value as discussed in the conversation (always a string).",
    )
    recorded_at: datetime = Field(
        ...,
        description="UTC timestamp when this fact was first mentioned / last updated.",
    )


class ThreadSummary(BaseModel):
    """
    The living structured memory of a single caller thread.

    Brain updates this after every batch of is_final=True TranscriptEvents.
    It is serialised to the Thread Memory Store between calls and deserialised
    when a Reconnect is detected.
    """

    thread_id: str = Field(
        ...,
        description="Unique identifier for this thread (caller_id + user_id composite).",
    )
    caller_id: str = Field(
        ...,
        description="Caller phone number (E.164) or SIP URI that owns this thread.",
    )
    caller_name: Optional[str] = Field(
        None,
        description="Caller's name if mentioned or known from contacts.",
    )

    # ── Core structured memory ──────────────────────────────────────────────
    headline: str = Field(
        ...,
        description=(
            "One-sentence TL;DR of the last interaction. "
            "This is what Rime will speak first if the ring window is very short. "
            "Keep it under 20 words."
        ),
    )
    context: str = Field(
        default="",
        description=(
            "1-3 natural spoken sentences of real substance behind the headline "
            "(what was discussed, decided, still open). Spoken in the recap after "
            "the headline so a short call never collapses to a bare headline + "
            "interruption note. Never filler; may be empty."
        ),
    )
    language: str = Field(
        default="en",
        description=(
            "Language the conversation was actually spoken in: 'en' for English, "
            "'hi' for Hindi / Hinglish (Latin-script Hinglish counts as 'hi'). "
            "The recap builder localises its fixed frames (freshness flag, "
            "next-action lead-in, interruption note) to match."
        ),
    )
    open_items: list[str] = Field(
        default_factory=list,
        description="Unresolved questions or topics still pending from either party.",
    )
    commitments: list[Commitment] = Field(
        default_factory=list,
        description="Action items with an owner (user or caller).",
    )
    time_sensitive_facts: list[TimeSensitiveFact] = Field(
        default_factory=list,
        description=(
            "Facts that may have changed since last discussed. "
            "The Fact-Freshness Checker will re-verify these before the recap."
        ),
    )
    key_names: list[str] = Field(
        default_factory=list,
        description="People, products, or company names mentioned — used for spell() wrapping.",
    )
    last_spoken_turn_text: Optional[str] = Field(
        None,
        description=(
            "The last partial sentence spoken before an abrupt disconnect. "
            "Used to produce a 'you were mid-sentence' note if relevant."
        ),
    )

    # ── Thread metadata ──────────────────────────────────────────────────────
    created_at: datetime = Field(..., description="UTC timestamp of the first call.")
    last_updated_at: datetime = Field(
        ..., description="UTC timestamp of the last Brain write."
    )
    last_call_ended_at: Optional[datetime] = Field(
        None,
        description="UTC timestamp when the last call session ended (interrupted or completed).",
    )
    is_interrupted: bool = Field(
        False,
        description=(
            "True when the last call ended abruptly (no closing turn detected). "
            "The Reconnect Detector sets this to True on an abrupt drop."
        ),
    )
    call_count: int = Field(
        1, ge=1, description="Total number of call sessions in this thread."
    )

    model_config = {"frozen": False}  # mutable — Brain updates it continuously
