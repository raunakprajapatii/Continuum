"""
modules/transport/exceptions.py
-------------------------------
Custom exceptions for the Transport (Pair A) module.

Enforces strict domain boundaries and critical security invariants,
most notably the dual-track audio isolation invariant.
"""

from __future__ import annotations


class TransportError(Exception):
    """Base exception for all Transport module errors."""
    pass


class TrackFencingViolationError(TransportError):
    """
    CRITICAL INVARIANT VIOLATION.

    Raised when any attempt is made to route recap audio, private whispers,
    or confidential thread memory data to the caller-facing audio track.

    The Blueprint invariant (§ 06 & § 08) strictly dictates that caller-facing
    and user-private audio paths must remain architecturally separate.
    """
    pass


class SessionStateError(TransportError):
    """
    Raised when an illegal call state transition is requested in the
    CallSessionManager FSM.
    """
    pass


class AudioStreamingError(TransportError):
    """
    Raised when an error occurs during audio frame acquisition, encoding,
    or streaming to the private LiveKit track.
    """
    pass


class BargeInInterruption(TransportError):
    """
    Signaled when a user barge-in event interrupts currently playing or queued
    recap audio on the private track.
    """
    pass
