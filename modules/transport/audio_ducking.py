"""
modules/transport/audio_ducking.py
----------------------------------
Audio Ducking and Priority Balance Controller for Continuum.

Addresses real-world call scenarios:
  - If recap didn't start within 5 seconds during the ring window,
  - Or if the call is answered instantly before the recap can play,
  - Or if the caller starts speaking immediately when answered,

The user (or system auto-trigger) can activate Priority Ducking:
  1. Ducks the caller's incoming voice volume in the user's earpiece (e.g. down to 25%).
  2. Boosts the assistant's whispered summary voice (e.g. up to 125%).
  3. Restores normal audio levels (caller 100%) immediately when recap playback completes.

CRITICAL INVARIANT PRESERVATION:
  Ducking affects ONLY what the USER hears in their own earpiece. The caller
  is NOT muted on their end and hears only the normal call. Under no
  circumstances does the recap audio leak to the caller.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("continuum.transport.ducking")


@dataclass(frozen=True)
class AudioLevels:
    """Snapshot of current audio level multipliers."""
    caller_volume: float  # Multiplier applied to incoming caller audio (0.0 to 1.0)
    recap_volume: float   # Multiplier applied to whispered recap audio (0.0 to 2.0)
    is_ducked: bool
    updated_at: datetime


class AudioDuckingController:
    """
    Controls dynamic audio balancing and ducking between caller audio and
    private recap voice in the user's headset.
    """

    DEFAULT_NORMAL_CALLER_VOLUME = 1.0
    DEFAULT_NORMAL_RECAP_VOLUME = 1.0
    DEFAULT_DUCKED_CALLER_VOLUME = 0.25  # Attenuate caller by 75%
    DEFAULT_BOOSTED_RECAP_VOLUME = 1.25  # Boost recap voice by 25%

    def __init__(
        self,
        normal_caller_volume: float = DEFAULT_NORMAL_CALLER_VOLUME,
        ducked_caller_volume: float = DEFAULT_DUCKED_CALLER_VOLUME,
        normal_recap_volume: float = DEFAULT_NORMAL_RECAP_VOLUME,
        boosted_recap_volume: float = DEFAULT_BOOSTED_RECAP_VOLUME,
        on_level_change: Optional[Callable[[AudioLevels], Any]] = None,
    ):
        self._normal_caller_volume = normal_caller_volume
        self._ducked_caller_volume = ducked_caller_volume
        self._normal_recap_volume = normal_recap_volume
        self._boosted_recap_volume = boosted_recap_volume
        self._on_level_change = on_level_change

        self._current_caller_volume = normal_caller_volume
        self._current_recap_volume = normal_recap_volume
        self._is_ducked = False
        self._lock = asyncio.Lock()

    @property
    def is_ducked(self) -> bool:
        """Whether caller audio is currently ducked in user's earpiece."""
        return self._is_ducked

    @property
    def caller_volume(self) -> float:
        """Current volume multiplier for caller voice in user earpiece."""
        return self._current_caller_volume

    @property
    def recap_volume(self) -> float:
        """Current volume multiplier for assistant recap voice."""
        return self._current_recap_volume

    def get_levels(self) -> AudioLevels:
        """Return snapshot of current audio level configuration."""
        return AudioLevels(
            caller_volume=self._current_caller_volume,
            recap_volume=self._current_recap_volume,
            is_ducked=self._is_ducked,
            updated_at=datetime.now(tz=timezone.utc),
        )

    async def activate_ducking(
        self,
        caller_volume: Optional[float] = None,
        recap_volume: Optional[float] = None,
        reason: str = "mid_call_recap",
    ) -> AudioLevels:
        """
        Ducks caller audio and elevates recap audio in user's headset.

        Called when:
          - A recap is triggered while call is already in CONNECTED state.
          - User presses mid-call catch-up button.
          - Pre-answer recap is still finishing when user answers the call.

        Args:
            caller_volume: Multiplier for caller voice in user's earpiece (0.0–1.0).
                           Defaults to DEFAULT_DUCKED_CALLER_VOLUME (0.25).
            recap_volume:  Multiplier for recap audio (0.0–2.0).
                           Defaults to DEFAULT_BOOSTED_RECAP_VOLUME (1.25).
            reason:        Logging label for this ducking event.

        Raises:
            ValueError: If caller_volume or recap_volume are outside valid ranges.
        """
        target_caller = (
            caller_volume if caller_volume is not None else self._ducked_caller_volume
        )
        target_recap = (
            recap_volume if recap_volume is not None else self._boosted_recap_volume
        )

        # Validate volume bounds before acquiring the lock
        if not (0.0 <= target_caller <= 1.0):
            raise ValueError(
                f"caller_volume must be in [0.0, 1.0]; got {target_caller!r}."
            )
        if not (0.0 <= target_recap <= 2.0):
            raise ValueError(
                f"recap_volume must be in [0.0, 2.0]; got {target_recap!r}."
            )

        async with self._lock:
            self._current_caller_volume = target_caller
            self._current_recap_volume = target_recap
            self._is_ducked = True

            levels = self.get_levels()
            logger.info(
                "Audio ducking ACTIVATED (%s): caller_volume=%.2f, recap_volume=%.2f",
                reason,
                target_caller,
                target_recap,
            )

            if self._on_level_change:
                res = self._on_level_change(levels)
                if asyncio.iscoroutine(res):
                    await res

            return levels


    async def restore_levels(self, reason: str = "recap_complete") -> AudioLevels:
        """
        Restores caller audio and recap audio back to standard 1.0 levels.
        """
        async with self._lock:
            if not self._is_ducked:
                return self.get_levels()

            self._current_caller_volume = self._normal_caller_volume
            self._current_recap_volume = self._normal_recap_volume
            self._is_ducked = False

            levels = self.get_levels()
            logger.info(
                "Audio ducking RESTORED (%s): caller_volume=%.2f, recap_volume=%.2f",
                reason,
                self._normal_caller_volume,
                self._normal_recap_volume,
            )

            if self._on_level_change:
                res = self._on_level_change(levels)
                if asyncio.iscoroutine(res):
                    await res

            return levels
