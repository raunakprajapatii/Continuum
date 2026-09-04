"""
modules/transport/__init__.py
-----------------------------
Pair A — Transport module public API.

Owns:
  - Call Session Manager (LiveKit room lifecycle, call states, ring window)
  - Private Whisper Channel (Rime audio delivery to private track only)
  - Audio Ducking Controller (Priority balance for mid-call recap delivery)
  - Transport Engine (Integrated orchestrator)
"""

from .audio_ducking import AudioDuckingController, AudioLevels
from .engine import TransportEngine
from .exceptions import (
    AudioStreamingError,
    BargeInInterruption,
    SessionStateError,
    TrackFencingViolationError,
    TransportError,
)
from .session_manager import CallSessionManager
from .whisper_channel import PlaybackMetrics, PrivateWhisperChannel

__all__ = [
    "AudioDuckingController",
    "AudioLevels",
    "AudioStreamingError",
    "BargeInInterruption",
    "CallSessionManager",
    "PlaybackMetrics",
    "PrivateWhisperChannel",
    "SessionStateError",
    "TrackFencingViolationError",
    "TransportEngine",
    "TransportError",
]
