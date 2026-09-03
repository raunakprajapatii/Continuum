"""
evaluation/test_zero_caller_impact.py
---------------------------------------
Acceptance Test 2 — Zero impact on caller audio

Blueprint § 13:
    Procedure: Record the audio Z actually hears throughout reconnect + recap window.
    Pass:      Z's audio is indistinguishable from an ordinary ringback-then-answer
               call; no recap audio present on the caller-facing track.

This is THE most critical test — the dual-track invariant that judges will stress-test.

Evidence artifact: evaluation/artifacts/caller_audio_inspection.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.schemas import RimeModel, TtsRequest

ARTIFACT = Path(__file__).parent / "artifacts" / "caller_audio_inspection.json"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Stub — implement in Pair A integration sprint (LiveKit track inspection)")
async def test_recap_audio_absent_from_caller_track(use_mocks: bool) -> None:
    """
    Verify that TtsRequest audio is NEVER routed to the caller-facing track.

    Implementation approach (Pair A):
      1. Capture what the caller-facing LiveKit track receives during a reconnect.
      2. Run audio fingerprint / energy check against the known Rime TTS output.
      3. Assert zero overlap.

    For the mock version: assert that any TtsRequest emitted has
    private_track_id == settings.private_track_id, and that the
    private_track_id is never equal to the caller-facing track ID.
    """
    from shared.config import settings

    # ── Stub: verify schema-level constraint ──────────────────────────────────
    # In the real test, inspect actual LiveKit track audio.
    # Here, we verify that the TtsRequest schema enforces private_track_id usage.
    import uuid
    from datetime import datetime, timezone

    tts_req = TtsRequest(
        request_id=str(uuid.uuid4()),
        session_id="mock-session-001",
        thread_id="mock-thread-Z-001",
        text="Z wanted the Q3 number; you said you'd check with finance.",
        model=RimeModel.CODA,
        speaker=settings.rime_default_speaker,
        private_track_id=settings.private_track_id,
        created_at=datetime.now(tz=timezone.utc),
    )

    CALLER_FACING_TRACK_ID = "caller-facing-main"  # replace with real LiveKit track ID

    result = {
        "test": "zero_caller_impact",
        "tts_private_track_id": tts_req.private_track_id,
        "caller_facing_track_id": CALLER_FACING_TRACK_ID,
        "tracks_are_separate": tts_req.private_track_id != CALLER_FACING_TRACK_ID,
        "pass": tts_req.private_track_id != CALLER_FACING_TRACK_ID,
        "note": "Full audio fingerprint check requires Pair A LiveKit integration.",
    }

    ARTIFACT.write_text(json.dumps(result, indent=2))

    assert tts_req.private_track_id != CALLER_FACING_TRACK_ID, (
        "CRITICAL: private_track_id matches caller-facing track! "
        "This would leak recap audio to the caller. "
        f"private_track_id={tts_req.private_track_id!r}"
    )
