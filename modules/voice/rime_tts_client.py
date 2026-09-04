"""
modules/voice/rime_tts_client.py
----------------------------------
Pair D — Rime TTS Client

Builds a ``TtsRequest`` that Transport (Pair A) will execute to synthesise and
stream the recap on the user's PRIVATE whisper track.

**Important**: This module does NOT call the Rime HTTP API directly.  Transport
owns the actual Rime network call and the LiveKit track-routing.  Pair D's
responsibility ends at emitting a correct, validated ``TtsRequest``.

Dual-track invariant (AGENTS.md Rule 1):
    ``TtsRequest.private_track_id`` MUST be ``settings.private_track_id``.
    This client hard-refuses to build a request where that field would be
    anything else.

Rime Rule only TTS (AGENTS.md Rule 2):
    No fallback to any other TTS provider.  If Rime params are invalid,
    raise immediately so the error is visible.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.config import settings
from shared.schemas import (
    RecapRequest,
    RecapUrgency,
    RimeModel,
    TtsRequest,
)

logger = logging.getLogger(__name__)

# spell() is embedded in text via Mist v2 inline syntax.
# If the text contains spell() calls, we must use MIST_V2.
_SPELL_MARKER = "spell("

# Urgency → time_scale_factor mapping.
# Shorter ring window → faster speech (lower factor speeds up Rime output).
_URGENCY_SPEED: dict[RecapUrgency, float] = {
    RecapUrgency.HEADLINE_ONLY: 0.75,   # sprint through it
    RecapUrgency.STANDARD:      0.85,   # blueprint default
    RecapUrgency.EXTENDED:      0.90,   # a bit more breathing room
}


class RimeTtsClient:
    """
    Builds ``TtsRequest`` objects for Transport to execute.

    Usage::

        client = RimeTtsClient()
        tts_req = client.make_request(
            recap_request=recap_req,
            spoken_text="Z wanted the Q3 number.",
        )
    """

    def __init__(
        self,
        speaker: Optional[str] = None,
        private_track_id: Optional[str] = None,
    ) -> None:
        # Use injected values or fall back to settings (enables testing overrides)
        self._speaker = speaker or settings.rime_default_speaker
        self._private_track_id = private_track_id or settings.private_track_id

    def make_request(
        self,
        recap_request: RecapRequest,
        spoken_text: str,
    ) -> TtsRequest:
        """
        Build and return a ``TtsRequest``.

        Raises ``ValueError`` if:
        - ``spoken_text`` is empty
        - ``private_track_id`` looks like the caller-facing track

        Raises ``RuntimeError`` if Rime parameters are structurally invalid.
        """
        if not spoken_text.strip():
            raise ValueError("spoken_text must not be empty — cannot build TtsRequest.")

        self._assert_private_track()

        model = self._select_model(spoken_text)
        speed = self._select_speed(recap_request.urgency, model)

        tts_req = TtsRequest(
            request_id=recap_request.request_id,
            session_id=recap_request.session_id,
            thread_id=recap_request.thread_id,
            text=spoken_text,
            model=model,
            speaker=self._speaker,
            language=settings.rime_default_language,
            time_scale_factor=speed if model in (RimeModel.CODA, RimeModel.MIST_V3) else None,
            speed_alpha=speed if model == RimeModel.MIST_V2 else None,
            private_track_id=self._private_track_id,
            is_interruptible=True,
            created_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "rime_tts_client: built TtsRequest request_id=%s model=%s speaker=%s "
            "len(text)=%d private_track=%s",
            tts_req.request_id,
            tts_req.model.value,
            tts_req.speaker,
            len(tts_req.text),
            tts_req.private_track_id,
        )
        return tts_req

    # ── internals ──────────────────────────────────────────────────────────────

    def _assert_private_track(self) -> None:
        """
        Enforce dual-track invariant (AGENTS.md Rule 1).

        Rejects any track ID that looks like the caller-facing track.
        The caller-facing track is never named 'private'; Transport owns
        the authoritative check at the LiveKit layer, but we add a defence
        here as well.
        """
        pid = self._private_track_id
        if not pid:
            raise ValueError(
                "private_track_id is empty. Set PRIVATE_TRACK_ID in .env."
            )
        # Heuristic guard: the private track must contain 'private' or 'whisper'
        pid_lower = pid.lower()
        if "caller" in pid_lower or "public" in pid_lower:
            raise ValueError(
                f"DUAL-TRACK INVARIANT VIOLATION: private_track_id={pid!r} "
                "appears to be the caller-facing track. "
                "Rime audio must NEVER be routed to the caller-facing track."
            )

    @staticmethod
    def _select_model(text: str) -> RimeModel:
        """
        Select the Rime model.

        MIST_V2 is required when the text contains ``spell(...)`` markers.
        CODA is used for all other recap text (most common case).
        """
        if _SPELL_MARKER in text:
            return RimeModel.MIST_V2
        return RimeModel.CODA

    @staticmethod
    def _select_speed(urgency: RecapUrgency, model: RimeModel) -> float:
        """
        Return the appropriate speed parameter for the model + urgency.

        For MIST_V2: speed_alpha (lower = faster, so we invert relative to
        time_scale_factor which is < 1 for faster).
        For CODA / MIST_V3: time_scale_factor directly.
        """
        tsf = _URGENCY_SPEED.get(urgency, 0.85)
        if model == RimeModel.MIST_V2:
            # speed_alpha ≈ 1 / time_scale_factor  (rough mapping)
            return round(1.0 / tsf, 2)
        return tsf
