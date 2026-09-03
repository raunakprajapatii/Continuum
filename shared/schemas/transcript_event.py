"""
transcript_event.py
--------------------
Contract: Signal (Pair B) → Brain (Pair C)

Emitted by the Streaming STT module for every utterance chunk it produces.
Brain consumes this stream to maintain a rolling structured Thread Memory.

Speaker tagging is essential — the recap generator needs to distinguish
"user said X" from "caller said X" to summarise commitments accurately.

DO NOT change this schema without a heads-up in the group chat first.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Speaker(str, Enum):
    """Who is speaking on a given transcript chunk."""

    USER = "USER"
    """The Continuum user (the person who will receive the recap)."""

    CALLER = "CALLER"
    """The remote party (Z in the blueprint scenarios)."""

    UNKNOWN = "UNKNOWN"
    """Speaker diarization could not determine the speaker. Treat with caution."""


class TranscriptEvent(BaseModel):
    """
    One chunk of transcribed speech from the STT module.

    Brain must buffer these and periodically flush them into the Thread Memory
    Store as structured summaries (open items, commitments, numbers, names).
    Storing the raw transcript indefinitely is explicitly NOT the design —
    see thread_summary.py for the target structure.
    """

    event_id: str = Field(
        ...,
        description="Unique ID for this transcript chunk (UUID4).",
    )
    session_id: str = Field(
        ...,
        description="Call session ID — must match the CallStateEvent.session_id.",
    )
    thread_id: Optional[str] = Field(
        None,
        description=(
            "Thread ID from the Thread Memory Store, if the caller was matched. "
            "None on first contact."
        ),
    )
    speaker: Speaker = Field(..., description="Who produced this utterance.")
    text: str = Field(
        ...,
        description="Transcribed text for this chunk. May be partial if is_final=False.",
        min_length=1,
    )
    is_final: bool = Field(
        True,
        description=(
            "True when the STT provider has committed this text (won't revise it). "
            "False for interim/streaming chunks that may be corrected. "
            "Brain should only persist is_final=True chunks to the Thread Memory Store."
        ),
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="STT confidence score [0, 1]. None if the provider doesn't emit one.",
    )
    start_ms: int = Field(
        ...,
        ge=0,
        description="Start of this utterance in milliseconds from call-session start.",
    )
    end_ms: Optional[int] = Field(
        None,
        ge=0,
        description="End of utterance in ms. None for interim chunks still in progress.",
    )
    timestamp: datetime = Field(
        ...,
        description="UTC wall-clock time when this event was emitted.",
    )

    model_config = {"frozen": True}
