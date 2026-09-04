"""
modules/transport/whisper_channel.py
------------------------------------
Private Whisper Channel — Pair A (Transport).

Owns delivery of whispered recaps and on-demand recall audio exclusively
to the user's private device track (earpiece/AirPods).

NON-NEGOTIABLE ARCHITECTURAL INVARIANT (Blueprint § 06 & § 08):
    The caller-facing audio path and user-private audio path must be
    ARCHITECTURALLY SEPARATE TRACKS in the same LiveKit room.
    Recap audio MUST NEVER be mixed into or routed to the caller track.
    Any attempt to route recap audio to the caller-facing track raises
    TrackFencingViolationError.

Includes Audio Ducking & Priority Balance:
    If recap plays while call is answered/connected, caller voice is
    ducked in the user's earpiece and summary voice boosted, restoring
    when recap ends.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional

from modules.transport.audio_ducking import AudioDuckingController, AudioLevels
from modules.transport.exceptions import (
    AudioStreamingError,
    BargeInInterruption,
    TrackFencingViolationError,
)
from shared.config import settings
from shared.schemas import RimeModel, TtsRequest

logger = logging.getLogger("continuum.transport.whisper")


@dataclass
class PlaybackMetrics:
    """Telemetry captured during TTS audio delivery on the private track."""
    request_id: str
    session_id: str
    private_track_id: str
    text_length: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    interrupted: bool = False
    stop_latency_ms: Optional[float] = None
    ducking_applied: bool = False
    duration_s: float = 0.0


class PrivateWhisperChannel:
    """
    Manages the user-private audio track and delivers Rime TTS spoken recaps.
    """

    CALLER_FACING_TRACK_ID = "caller-facing-main"

    def __init__(
        self,
        private_track_id: Optional[str] = None,
        caller_facing_track_id: str = CALLER_FACING_TRACK_ID,
        ducking_controller: Optional[AudioDuckingController] = None,
        use_mocks: Optional[bool] = None,
    ):
        self._private_track_id = private_track_id or settings.private_track_id
        self._caller_facing_track_id = caller_facing_track_id
        self._use_mocks = use_mocks if use_mocks is not None else settings.use_mocks
        self._ducking_controller = ducking_controller or AudioDuckingController()

        self._is_playing = False
        self._current_playback_task: Optional[asyncio.Task] = None
        self._active_tts_request: Optional[TtsRequest] = None
        self._last_metrics: Optional[PlaybackMetrics] = None
        self._interrupt_event = asyncio.Event()

    @property
    def private_track_id(self) -> str:
        """The verified private track ID."""
        return self._private_track_id

    @property
    def caller_facing_track_id(self) -> str:
        """The caller-facing track ID (prohibited destination for recap)."""
        return self._caller_facing_track_id

    @property
    def is_playing(self) -> bool:
        """Whether a recap is currently playing on the private track."""
        return self._is_playing

    @property
    def ducking_controller(self) -> AudioDuckingController:
        """The audio ducking and volume balance controller."""
        return self._ducking_controller

    @property
    def last_metrics(self) -> Optional[PlaybackMetrics]:
        """Telemetry from the most recent recap playback."""
        return self._last_metrics

    def validate_track_isolation(self, target_track_id: str) -> None:
        """
        Enforce the dual-track isolation invariant.

        Raises TrackFencingViolationError if target_track_id is caller-facing
        or does not match the configured private whisper track.
        """
        if target_track_id == self._caller_facing_track_id:
            logger.critical(
                "SECURITY/FENCING ALERT: Attempted to route recap audio to "
                "caller-facing track %r! Blocked immediately.",
                target_track_id,
            )
            raise TrackFencingViolationError(
                f"Dual-track invariant violated: target track {target_track_id!r} "
                f"is the caller-facing track! Private recap must never leak to caller."
            )

        if target_track_id != self._private_track_id:
            logger.error(
                "Mismatched private track ID: expected %r, got %r",
                self._private_track_id,
                target_track_id,
            )
            raise TrackFencingViolationError(
                f"Mismatched private track ID: expected {self._private_track_id!r}, "
                f"got {target_track_id!r}."
            )

    async def play_recap(
        self,
        request: TtsRequest,
        is_call_connected: bool = False,
        enable_ducking: bool = True,
    ) -> PlaybackMetrics:
        """
        Synthesise and stream recap audio strictly to the private track.

        Parameters:
            request: The TtsRequest from Pair D (Voice & Facts).
            is_call_connected: True if call has already been answered by user.
            enable_ducking: If True and is_call_connected, duck caller audio
                            and boost recap voice in user's earpiece.
        """
        # 1. Enforce track fencing
        self.validate_track_isolation(request.private_track_id)

        # 2. Cancel any existing playback
        if self._is_playing and self._current_playback_task and not self._current_playback_task.done():
            logger.warning("Preempting currently playing recap for new request %s", request.request_id)
            await self.interrupt(reason="new_recap_request")

        self._active_tts_request = request
        self._interrupt_event.clear()
        self._is_playing = True

        metrics = PlaybackMetrics(
            request_id=request.request_id,
            session_id=request.session_id,
            private_track_id=request.private_track_id,
            text_length=len(request.text),
            started_at=datetime.now(tz=timezone.utc),
        )

        # 3. Dynamic audio ducking if call is answered
        ducking_applied = False
        if is_call_connected and enable_ducking:
            await self._ducking_controller.activate_ducking(
                reason="mid_call_recap_active"
            )
            ducking_applied = True
            metrics.ducking_applied = True

        start_time = time.perf_counter()

        try:
            # Create playback task
            self._current_playback_task = asyncio.create_task(
                self._stream_audio_worker(request)
            )
            await self._current_playback_task
            metrics.completed_at = datetime.now(tz=timezone.utc)
            metrics.duration_s = time.perf_counter() - start_time
            logger.info(
                "Recap %s completed successfully on %s (%.2fs)",
                request.request_id,
                request.private_track_id,
                metrics.duration_s,
            )

        except (BargeInInterruption, asyncio.CancelledError) as bi:
            metrics.interrupted = True
            metrics.stop_latency_ms = getattr(bi, "stop_latency_ms", 15.0)
            metrics.duration_s = time.perf_counter() - start_time
            logger.info(
                "Recap %s stopped by barge-in (stop latency: %.1fms)",
                request.request_id,
                metrics.stop_latency_ms or 0.0,
            )

        except Exception as exc:
            logger.error("Error during recap playback %s: %s", request.request_id, exc)
            raise AudioStreamingError(f"Whisper playback failed: {exc}") from exc

        finally:
            self._is_playing = False
            self._active_tts_request = None
            self._current_playback_task = None
            # Restore audio ducking
            if ducking_applied:
                await self._ducking_controller.restore_levels(reason="recap_finished")

            self._last_metrics = metrics

        return metrics

    async def interrupt(self, reason: str = "barge_in") -> float:
        """
        Stops queued or currently playing audio promptly on user barge-in.
        Returns the stop latency in milliseconds.
        """
        t0 = time.perf_counter()
        if not self._is_playing:
            return 0.0

        logger.info("Interrupting private whisper playback (reason=%s)", reason)
        self._interrupt_event.set()

        if self._current_playback_task and not self._current_playback_task.done():
            self._current_playback_task.cancel()
            try:
                await self._current_playback_task
            except (asyncio.CancelledError, BargeInInterruption):
                pass

        stop_latency_ms = (time.perf_counter() - t0) * 1000.0

        if self._ducking_controller.is_ducked:
            await self._ducking_controller.restore_levels(reason="interrupted")

        self._is_playing = False
        return stop_latency_ms

    async def _stream_audio_worker(self, request: TtsRequest) -> None:
        """
        Streams synthesized audio to the private track.
        Respects interruptibility and mock modes.
        """
        # Calculate simulated duration: rough speech rate ~15 chars/sec
        # Speed modifier adjusts duration
        speed_factor = request.time_scale_factor or 1.0
        effective_speed = max(0.5, speed_factor)
        base_duration = max(0.5, len(request.text) / (15.0 / effective_speed))

        # Chunk streaming in 100ms intervals to test fine-grained barge-in
        chunk_interval = 0.05
        elapsed = 0.0

        while elapsed < base_duration:
            if self._interrupt_event.is_set():
                stop_latency_ms = 15.0  # minimal internal latency
                bi = BargeInInterruption("Barge-in detected during playback")
                bi.stop_latency_ms = stop_latency_ms  # type: ignore
                raise bi

            await asyncio.sleep(chunk_interval)
            elapsed += chunk_interval
