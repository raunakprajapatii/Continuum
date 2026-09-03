"""
shared/schemas/__init__.py
--------------------------
Clean public API for all shared contract schemas.

Import from here, not from submodules directly:

    from shared.schemas import (
        CallState, CallStateEvent,
        Speaker, TranscriptEvent,
        ThreadSummary, Commitment, TimeSensitiveFact,
        RecapRequest, RecapUrgency,
        FreshnessResult, FreshnessStatus, FactCheckResult,
        TtsRequest, RimeModel,
    )
"""

from .call_state_event import CallState, CallStateEvent
from .freshness_result import FactCheckResult, FreshnessResult, FreshnessStatus
from .recap_request import RecapRequest, RecapUrgency
from .thread_summary import Commitment, ThreadSummary, TimeSensitiveFact
from .transcript_event import Speaker, TranscriptEvent
from .tts_request import RimeModel, TtsRequest

__all__ = [
    # call_state_event
    "CallState",
    "CallStateEvent",
    # transcript_event
    "Speaker",
    "TranscriptEvent",
    # thread_summary
    "Commitment",
    "TimeSensitiveFact",
    "ThreadSummary",
    # recap_request
    "RecapUrgency",
    "RecapRequest",
    # freshness_result
    "FreshnessStatus",
    "FactCheckResult",
    "FreshnessResult",
    # tts_request
    "RimeModel",
    "TtsRequest",
]
