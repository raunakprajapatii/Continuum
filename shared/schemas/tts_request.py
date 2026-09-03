"""
tts_request.py
--------------
Contract: Voice & Facts (Pair D) → Transport (Pair A)

Transport's private whisper channel streams this audio to the user's earpiece
ONLY — never to the caller-facing track.

This is the last message that crosses a pair boundary before audio plays.
It carries the final spoken text (formatted per Rime's prompting guide) and
the exact Rime model/voice parameters to use.

Blueprint invariant (§ 06, "Design invariant that judges will stress-test"):
    The caller-facing audio path and the user-private audio path must be
    ARCHITECTURALLY SEPARATE TRACKS in the same LiveKit room.
    Transport must enforce this — it is never acceptable to play this audio
    on the caller-facing track, even at zero volume.

DO NOT change this schema without a heads-up in the group chat first.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RimeModel(str, Enum):
    """
    Rime TTS model options, per blueprint § 12 and docs.rime.ai/docs/models.

    Selection guide:
      - CODA:     Natural / expressive default. Use for standard recap delivery.
      - MIST_V2:  Use when per-word inlineSpeedAlpha control is needed on a
                  specific number or name. Also required for spell() processing.
      - MIST_V3:  Like v2 but groups spell() output in threes; slightly more
                  natural for long alphanumeric strings.
    """

    CODA = "coda"
    MIST_V2 = "mist_v2"
    MIST_V3 = "mist_v3"


class TtsRequest(BaseModel):
    """
    Request from Voice & Facts to Transport to synthesise and stream a recap
    on the user's PRIVATE audio track only.

    Voice & Facts must:
      1. Format `text` per Rime prompting guide rules (short sentences, no SSML,
         spell() for IDs, punctuation-only prosody).
      2. Choose model and speed parameters based on content.
      3. Emit this request; Transport owns the actual Rime API call and
         private-track routing.
    """

    request_id: str = Field(
        ...,
        description="Matches RecapRequest.request_id for full-pipeline correlation.",
    )
    session_id: str = Field(..., description="Call session ID.")
    thread_id: str = Field(..., description="Thread ID this recap is for.")

    # ── Spoken content ────────────────────────────────────────────────────────
    text: str = Field(
        ...,
        description=(
            "Final spoken text, formatted per Rime prompting guide:\n"
            "  • Short sentences (< 20 words each)\n"
            "  • No SSML, no HTML tags\n"
            "  • IDs / ticket numbers wrapped in spell(...)\n"
            "  • Freshness flags early: 'Heads up — X is now Y.'\n"
            "  • Headline first, no preamble\n"
            "This text must pass the prompting-guide lint check before emitting."
        ),
    )

    # ── Rime model & voice parameters ─────────────────────────────────────────
    model: RimeModel = Field(
        RimeModel.CODA,
        description="Rime model to use. Default CODA for standard delivery.",
    )
    speaker: str = Field(
        ...,
        description=(
            "Voice ID from the live Rime catalog "
            "(users.rime.ai/data/voices/all-v2.json). "
            "Must be verified against the live catalog at build time — do not "
            "hard-code a stale voice ID."
        ),
    )
    language: str = Field(
        "en",
        description="BCP-47 language code for the recap (default English).",
    )

    # ── Speed control ─────────────────────────────────────────────────────────
    # See docs.rime.ai/docs/speed for full reference.
    time_scale_factor: Optional[float] = Field(
        None,
        gt=0.0,
        description=(
            "CODA / Mist v3: Global speed multiplier. "
            "< 1.0 speeds up; > 1.0 slows down. "
            "Blueprint suggests ~0.85 for connective filler in a recap. "
            "None → Rime default."
        ),
    )
    speed_alpha: Optional[float] = Field(
        None,
        gt=0.0,
        description=(
            "Mist v2 only: Global speed control. Lower = faster. "
            "Mutually exclusive with time_scale_factor."
        ),
    )
    # inlineSpeedAlpha is embedded in the text via bracket syntax, e.g.
    # "The price is now [four hundred twenty dollars]" with the value specified
    # in the API call. See Rime docs for exact format.

    # ── Delivery metadata ─────────────────────────────────────────────────────
    private_track_id: str = Field(
        ...,
        description=(
            "LiveKit track ID of the user's private earpiece track. "
            "Transport MUST route audio exclusively to this track. "
            "Reject / log an error if this track ID is the caller-facing track."
        ),
    )
    is_interruptible: bool = Field(
        True,
        description=(
            "If True, Transport should stop playback immediately if the user "
            "speaks on the private mic path ('skip, I remember'). "
            "Queued audio must not continue playing after interruption."
        ),
    )

    created_at: datetime = Field(
        ..., description="UTC timestamp when Voice & Facts emitted this request."
    )

    model_config = {"frozen": True}
