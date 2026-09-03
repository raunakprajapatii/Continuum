"""
call_state_event.py
-------------------
Contract: Transport (Pair A) → Signal (Pair B)

Emitted whenever the call session state changes. Signal consumes this to:
  - Start / stop streaming STT
  - Trigger the Disconnect / Reconnect detector
  - Kick off caller-identity matching on RINGING → CONNECTED transitions

DO NOT change this schema without a heads-up in the group chat first.
All 4 pairs' mocks depend on the shape defined here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CallState(str, Enum):
    """Lifecycle states of a single call leg."""

    IDLE = "IDLE"
    """No active call; session manager is standing by."""

    RINGING = "RINGING"
    """Incoming call detected; ring window is open for pre-answer recap."""

    CONNECTED = "CONNECTED"
    """Call is live; both legs are streaming audio."""

    DISCONNECTED = "DISCONNECTED"
    """Call ended abruptly (no closing turn detected → interrupted thread)."""

    COMPLETED = "COMPLETED"
    """Call ended normally (closing turn detected → no recap needed next time,
    or only a brief 'last touchpoint' note)."""


class CallStateEvent(BaseModel):
    """
    Emitted by the Call Session Manager every time the call state changes.

    Signal must treat every event as authoritative — do not cache state
    client-side; always react to the latest event.
    """

    event_id: str = Field(
        ...,
        description="Unique ID for this specific state-change event (UUID4).",
    )
    session_id: str = Field(
        ...,
        description=(
            "Stable identifier for the entire call session (persists across "
            "reconnects for the same thread). Used to correlate events in logs."
        ),
    )
    thread_id: Optional[str] = Field(
        None,
        description=(
            "If the caller matched a paused thread, this is the thread ID from "
            "the Thread Memory Store. None when the caller is unknown / first contact."
        ),
    )
    state: CallState = Field(..., description="New call state after this event.")
    previous_state: Optional[CallState] = Field(
        None, description="State before this transition. None for the first event."
    )
    caller_id: Optional[str] = Field(
        None,
        description=(
            "Caller identifier: phone number (E.164) or SIP URI. "
            "Available from RINGING onward. None while IDLE."
        ),
    )
    is_reconnect: bool = Field(
        False,
        description=(
            "True when this RINGING event follows an INTERRUPTED thread for this "
            "caller — i.e., the Reconnect Detector already matched the caller. "
            "Signal should prioritise transcript streaming immediately when True."
        ),
    )
    timestamp: datetime = Field(
        ...,
        description="UTC timestamp of the state transition (ISO-8601).",
    )

    model_config = {"frozen": True}
