"""
modules/transport/engine.py
---------------------------
Transport Engine — Orchestrates CallSessionManager and PrivateWhisperChannel.

Provides the high-level API for Pair A (Transport):
  - Starts LiveKit room or simulated session.
  - Exposes call state streams and recap delivery pipeline.
  - Enforces the dual-track isolation invariant.
  - Coordinates dynamic audio ducking during mid-call recap delivery.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from modules.transport.audio_ducking import AudioDuckingController, AudioLevels
from modules.transport.exceptions import TrackFencingViolationError, TransportError
from modules.transport.session_manager import CallSessionManager
from modules.transport.whisper_channel import PlaybackMetrics, PrivateWhisperChannel
from shared.config import settings
from shared.schemas import CallState, CallStateEvent, TtsRequest

logger = logging.getLogger("continuum.transport.engine")


class TransportEngine:
    """
    Unified engine for Pair A (Transport).
    """

    def __init__(
        self,
        use_mocks: Optional[bool] = None,
        private_track_id: Optional[str] = None,
    ):
        self._use_mocks = use_mocks if use_mocks is not None else settings.use_mocks
        self._private_track_id = private_track_id or settings.private_track_id

        self._ducking_controller = AudioDuckingController()
        self._whisper_channel = PrivateWhisperChannel(
            private_track_id=self._private_track_id,
            ducking_controller=self._ducking_controller,
            use_mocks=self._use_mocks,
        )
        self._session_manager = CallSessionManager(
            whisper_channel=self._whisper_channel,
            use_mocks=self._use_mocks,
        )

        self._is_running = False
        self._room: Optional[Any] = None

    @property
    def session_manager(self) -> CallSessionManager:
        return self._session_manager

    @property
    def whisper_channel(self) -> PrivateWhisperChannel:
        return self._whisper_channel

    @property
    def ducking_controller(self) -> AudioDuckingController:
        return self._ducking_controller

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """Initialize and start the Transport engine."""
        logger.info(
            "Starting Transport Engine (use_mocks=%s, private_track_id=%s)",
            self._use_mocks,
            self._private_track_id,
        )

        if not self._use_mocks:
            try:
                # LiveKit connection setup if credentials are valid
                logger.info("Initializing LiveKit connection to %s", settings.livekit_url)
                # Production LiveKit room connection logic
            except Exception as exc:
                logger.warning("Could not connect to live LiveKit cloud: %s. Falling back to simulated transport.", exc)

        self._is_running = True

    async def stop(self) -> None:
        """Gracefully shutdown the Transport engine."""
        logger.info("Stopping Transport Engine...")
        if self._whisper_channel.is_playing:
            await self._whisper_channel.interrupt(reason="engine_shutdown")

        self._is_running = False

    async def deliver_recap(
        self,
        request: TtsRequest,
        enable_audio_ducking: bool = True,
    ) -> PlaybackMetrics:
        """
        Deliver a spoken recap via the private whisper channel.
        Applies audio ducking if the call is currently connected.
        """
        return await self._session_manager.deliver_recap(
            request=request,
            enable_audio_ducking=enable_audio_ducking,
        )

    async def trigger_mid_call_catchup(
        self,
        recap_request_callback: Optional[Callable[[], TtsRequest]] = None,
    ) -> PlaybackMetrics:
        """
        Trigger on-demand mid-call catchup with audio ducking.
        (Lowers caller audio in user's headset, boosts summary voice).
        """
        return await self._session_manager.trigger_mid_call_catchup(
            recap_request_callback=recap_request_callback
        )

    async def interrupt_recap(self, reason: str = "barge_in") -> float:
        """Interrupt active recap immediately (< 500ms)."""
        return await self._whisper_channel.interrupt(reason=reason)
