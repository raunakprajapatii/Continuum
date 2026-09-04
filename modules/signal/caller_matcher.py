"""
modules/signal/caller_matcher.py
---------------------------------
Caller-ID normalisation and in-memory matching store.

Pair B owns this file. It provides a lightweight, thread-safe index that
maps a normalised caller identifier to the most recent ``CallStateEvent``
seen for that caller.

The Reconnect Detector queries this to decide:
  - "Have we seen this caller before?"
  - "Did their last session end abruptly (is_interrupted)?"
  - "What thread_id should we attach to the new session?"

Normalisation rules
-------------------
E.164 phone numbers (e.g. +14155550199):
  - Strip whitespace, dashes, parentheses.
  - Keep the leading '+' and all digits.
  - Lower-case (no effect on digits, but defensive).

SIP URIs (e.g. sip:alice@example.com):
  - Lower-case the entire string.
  - Strip any trailing parameters (;transport=tls etc.).

Unknown / None:
  - Return None; the detector treats this as "first contact".
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from shared.schemas import CallStateEvent

logger = logging.getLogger(__name__)

# ── Normalisation helpers ─────────────────────────────────────────────────────

_E164_STRIP = re.compile(r"[\s\-().]+")
_SIP_PARAMS = re.compile(r";.*$")


def normalise_caller_id(raw: Optional[str]) -> Optional[str]:
    """
    Return a canonical, comparable caller identifier.

    Args:
        raw: The raw caller_id string from the ``CallStateEvent`` (E.164 or SIP URI).
             May be None for IDLE state events.

    Returns:
        A normalised string suitable for use as a dict key, or ``None`` if
        the input is empty / None.

    Examples:
        >>> normalise_caller_id("+1 (415) 555-0199")
        '+14155550199'
        >>> normalise_caller_id("sip:alice@example.com;transport=tls")
        'sip:alice@example.com'
        >>> normalise_caller_id(None)
        None
    """
    if not raw:
        return None

    raw = raw.strip()
    if not raw:  # whitespace-only input
        return None

    if raw.lower().startswith("sip:") or raw.lower().startswith("sips:"):
        # SIP URI — lower-case, strip transport params
        return _SIP_PARAMS.sub("", raw.lower())

    # Treat everything else as a phone number
    stripped = _E164_STRIP.sub("", raw)
    # Ensure leading '+' is preserved if present in the original
    if raw.startswith("+") and not stripped.startswith("+"):
        stripped = "+" + stripped
    return stripped.lower()


# ── Caller store ─────────────────────────────────────────────────────────────


class CallerMatchEntry:
    """
    One slot in the caller index.

    Attributes:
        caller_id_raw:   The original (un-normalised) caller ID from the event.
        last_event:      The most recent ``CallStateEvent`` for this caller.
        thread_id:       The thread_id from that event, or None if first contact.
        is_interrupted:  Whether the last session ended abruptly.
    """

    __slots__ = ("caller_id_raw", "last_event", "thread_id", "is_interrupted")

    def __init__(self, event: CallStateEvent) -> None:
        self.caller_id_raw: str = event.caller_id or ""
        self.last_event: CallStateEvent = event
        self.thread_id: Optional[str] = event.thread_id
        self.is_interrupted: bool = False


class CallerMatcher:
    """
    Thread-safe, in-memory caller-ID index.

    All public methods are async-safe and internally protected by an
    ``asyncio.Lock`` so they can be called concurrently from the agent.

    Lifecycle:
        1. Signal Agent calls ``record_event(event)`` on every ``CallStateEvent``.
        2. When a new RINGING event arrives, the agent calls ``lookup(caller_id)``
           to find a prior interrupted entry.
        3. On DISCONNECTED, the agent calls ``mark_interrupted(caller_id)`` to
           set the ``is_interrupted`` flag for the next lookup.
    """

    def __init__(self) -> None:
        # Keyed by normalised caller ID
        self._store: dict[str, CallerMatchEntry] = {}
        self._lock = asyncio.Lock()

    async def record_event(self, event: CallStateEvent) -> None:
        """
        Upsert the caller's entry with the latest event.

        Should be called for every non-IDLE event so the index stays current.
        """
        key = normalise_caller_id(event.caller_id)
        if key is None:
            return  # IDLE events have no caller_id; skip

        async with self._lock:
            if key in self._store:
                self._store[key].last_event = event
                if event.thread_id:
                    self._store[key].thread_id = event.thread_id
            else:
                self._store[key] = CallerMatchEntry(event)
                logger.debug("CallerMatcher: new entry for %s", key)

    async def lookup(self, caller_id: Optional[str]) -> Optional[CallerMatchEntry]:
        """
        Return the stored entry for *caller_id*, or ``None`` if unknown.

        Args:
            caller_id: Raw caller ID from an incoming RINGING event.

        Returns:
            ``CallerMatchEntry`` if the caller has a prior record; ``None`` otherwise.
        """
        key = normalise_caller_id(caller_id)
        if key is None:
            return None
        async with self._lock:
            return self._store.get(key)

    async def mark_interrupted(self, caller_id: Optional[str]) -> None:
        """
        Flag the caller's last session as abruptly interrupted.

        Called by the Reconnect Detector when a DISCONNECTED event arrives
        with no preceding closing turn (i.e. the call was not COMPLETED).
        """
        key = normalise_caller_id(caller_id)
        if key is None:
            return
        async with self._lock:
            if key in self._store:
                self._store[key].is_interrupted = True
                logger.info(
                    "CallerMatcher: marked %s as interrupted (thread_id=%s)",
                    key,
                    self._store[key].thread_id,
                )

    async def clear_interrupted(self, caller_id: Optional[str]) -> None:
        """
        Reset the interrupted flag once a reconnect has been successfully handled.

        Called by the agent after the RINGING reconnect path has been triggered,
        so a third call from the same number doesn't falsely appear as a reconnect.
        """
        key = normalise_caller_id(caller_id)
        if key is None:
            return
        async with self._lock:
            if key in self._store:
                self._store[key].is_interrupted = False

    async def all_entries(self) -> list[CallerMatchEntry]:
        """Return a snapshot of all current entries (for diagnostics / dashboards)."""
        async with self._lock:
            return list(self._store.values())
