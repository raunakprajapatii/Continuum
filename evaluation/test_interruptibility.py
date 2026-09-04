"""
evaluation/test_interruptibility.py
-------------------------------------
Acceptance Test 5 — Interruptibility

Blueprint § 13:
    Procedure: User barges in mid-recap ("skip, I remember").
    Pass:      Queued Rime audio stops promptly (< 500ms); no orphaned audio continues playing.

Evidence artifact: evaluation/artifacts/interruptibility.json
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modules.transport import PrivateWhisperChannel
from shared.config import settings
from shared.schemas import RimeModel, TtsRequest

ARTIFACT = Path(__file__).parent / "artifacts" / "interruptibility.json"


@pytest.mark.asyncio
async def test_recap_stops_on_barge_in(use_mocks: bool) -> None:
    """
    Verify that when the user speaks on the private mic path during recap,
    Rime TTS playback stops within an acceptable window (< 500ms).
    """
    channel = PrivateWhisperChannel()

    tts_req = TtsRequest(
        request_id=str(uuid.uuid4()),
        session_id="mock-session-bargein",
        thread_id="mock-thread-Z-001",
        text="A long recap sentence that would normally play for several seconds across the ring window.",
        model=RimeModel.CODA,
        speaker=settings.rime_default_speaker,
        private_track_id=settings.private_track_id,
        is_interruptible=True,
        created_at=datetime.now(tz=timezone.utc),
    )

    # 1. Start playback on private track
    playback_task = asyncio.create_task(channel.play_recap(tts_req))
    await asyncio.sleep(0.1)  # allow streaming to begin

    assert channel.is_playing is True, "Playback should be active before barge-in"

    # 2. Simulate barge-in signal ("skip, I remember")
    t0 = time.perf_counter()
    stop_latency_ms = await channel.interrupt(reason="user_barge_in")
    metrics = await playback_task
    measured_stop_latency_ms = max(stop_latency_ms, (time.perf_counter() - t0) * 1000.0)

    # 3. Assertions
    assert channel.is_playing is False, "Audio is still marked as playing after barge-in!"
    assert metrics.interrupted is True, "Metrics did not record interrupted=True"
    assert measured_stop_latency_ms <= 500.0, f"Barge-in latency {measured_stop_latency_ms:.1f}ms exceeded 500ms threshold!"

    result = {
        "test": "interruptibility",
        "stop_latency_ms": round(measured_stop_latency_ms, 2),
        "threshold_ms": 500.0,
        "is_interruptible_flag_honored": True,
        "orphaned_audio_remaining": False,
        "pass": measured_stop_latency_ms <= 500.0 and channel.is_playing is False,
        "note": "Barge-in cancellation stopped playback promptly without orphan audio.",
    }

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(result, indent=2))

    assert result["pass"]
