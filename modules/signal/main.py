"""
modules/signal/main.py
------------------------
Entry point for running the Signal module as a standalone process.

Run with mocks (no external services needed — for local development):
    USE_MOCKS=true python -m modules.signal.main

Run against live services (requires .env with real credentials):
    python -m modules.signal.main

The process:
  1. Loads settings from .env
  2. Creates a SignalAgent with a simple logging on_transcript callback
  3. Connects to the event source (MockCallSession or a real LiveKit room)
  4. Runs until the call session completes

For the hackathon demo:
  - Use USE_MOCKS=true to run the full Scenario C replay end-to-end.
  - The output shows every TranscriptEvent emitted to Brain.
  - Reconnect detection is logged clearly so judges can see it fire.

LiveKit integration note:
  When USE_MOCKS=False, this main.py is the entrypoint for the LiveKit Agents
  worker process. Pair A's CallSessionManager will feed real CallStateEvents
  into the agent via an asyncio queue that replaces the MockCallSession stream.
  The wiring point is marked with TODO(Pair A integration).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import timezone
from typing import AsyncIterator, Optional

from shared.config import settings
from shared.schemas import CallStateEvent, TranscriptEvent

from .signal_agent import SignalAgent

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("signal.main")


# ── Callbacks (replace with real Brain integration in full pipeline) ───────────


async def _on_transcript(event: TranscriptEvent) -> None:
    """
    Receive a final TranscriptEvent from the STT streamer.

    In the full pipeline this would push to Brain's async queue.
    Here we just log it so the demo output is clear.
    """
    ts = event.timestamp.astimezone(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    logger.info(
        "[TRANSCRIPT] %s  [%s]  %s",
        ts,
        event.speaker.value,
        event.text,
    )


async def _on_reconnect(
    session_id: str,
    thread_id: Optional[str],
    caller_id: Optional[str],
) -> None:
    """
    Reconnect detected during ring window.

    In the full pipeline this triggers the recap pipeline:
      Brain.get_thread_summary(thread_id) → RecapGenerator → Voice & Facts → Rime TTS
    Here we log the notification so it's visible in the demo.
    """
    logger.info(
        "RECONNECT DETECTED -- session=%s  thread_id=%s  caller=%s",
        session_id,
        thread_id,
        caller_id,
    )
    logger.info(
        "   -> In the full pipeline: Brain would now generate recap text for "
        "thread %s and send it to Rime TTS on the private track.",
        thread_id,
    )


async def _on_call_ended(session_id: str, abruptly: bool) -> None:
    """
    Call session ended.

    In the full pipeline Brain flushes its in-flight transcript buffer here.
    """
    status = "ABRUPTLY (interrupted)" if abruptly else "normally (COMPLETED)"
    logger.info("CALL ENDED %s -- session=%s", status, session_id)


# ── Event source ─────────────────────────────────────────────────────────────


async def _get_event_stream() -> AsyncIterator[CallStateEvent]:
    """
    Return the appropriate CallStateEvent stream based on USE_MOCKS.

    Mock path: Uses MockCallSession(scenario='reconnect') which simulates
               Scenario C — the most interesting demo scenario.

    Live path: TODO(Pair A integration) — replace with the real LiveKit
               room event queue from the Call Session Manager.
    """
    if settings.use_mocks:
        from mocks.mock_call_session import MockCallSession

        logger.info("Signal main: USE_MOCKS=true — using MockCallSession(scenario='reconnect')")
        session = MockCallSession(scenario="reconnect", ring_duration_s=5.0)
        return session.event_stream()

    # ── Live path placeholder ─────────────────────────────────────────────────
    # TODO(Pair A integration): Connect to the real LiveKit Agents event queue.
    #
    # Example:
    #   from modules.transport.call_session_manager import CallSessionManager
    #   manager = CallSessionManager()
    #   return manager.event_stream()
    #
    raise NotImplementedError(
        "Live LiveKit event source is not yet connected. "
        "Set USE_MOCKS=true to run with the mock session, or implement the "
        "Pair A integration in modules/signal/main.py."
    )


# ── Main ─────────────────────────────────────────────────────────────────────


async def _main() -> None:
    logger.info("=" * 60)
    logger.info("Continuum — Signal Module (Pair B)")
    logger.info("USE_MOCKS=%s  STT_PROVIDER=%s", settings.use_mocks, settings.stt_provider)
    logger.info("=" * 60)

    agent = SignalAgent(
        on_transcript=_on_transcript,
        on_reconnect=_on_reconnect,
        on_call_ended=_on_call_ended,
    )

    event_stream = await _get_event_stream()
    await agent.run(event_stream)

    logger.info("Signal main: done.")


if __name__ == "__main__":
    asyncio.run(_main())
