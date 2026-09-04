"""
modules/signal/__init__.py
---------------------------
Public API surface for the Signal module (Pair B).

Other modules should import from here, not from submodules directly:

    from modules.signal import SignalAgent, StreamingSTT, ReconnectDetector
    from modules.signal import CallerMatcher, ReconnectDecision

This keeps internal refactors transparent to consumers.
"""

from __future__ import annotations

from .caller_matcher import CallerMatchEntry, CallerMatcher, normalise_caller_id
from .reconnect_detector import ReconnectDecision, ReconnectDetector
from .signal_agent import SignalAgent
from .stt_streamer import STT_CONFIDENCE_THRESHOLD, StreamingSTT

__all__ = [
    # Core agent
    "SignalAgent",
    # STT
    "StreamingSTT",
    "STT_CONFIDENCE_THRESHOLD",
    # Reconnect detector
    "ReconnectDetector",
    "ReconnectDecision",
    # Caller matching
    "CallerMatcher",
    "CallerMatchEntry",
    "normalise_caller_id",
]
