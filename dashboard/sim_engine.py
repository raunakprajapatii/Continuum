"""
dashboard/sim_engine.py
-----------------------
Control-surface orchestration for the interactive web demo simulation.

This module wires the real Continuum modules (Thread Memory Store, Brain
extractor, Voice & Facts pipeline) behind small async functions that the
FastAPI routes in ``dashboard/server.py`` call.  It deliberately reuses the
production modules from ``modules/`` — it is not a mock.

Responsibilities:
  - Own lazily-created singletons (ThreadMemoryStore, BrainService,
    FreshnessChecker, RecapTextBuilder, RimeTtsClient) with injectable
    overrides so tests can point at an in-memory store / fake pipeline.
  - End-call extraction  : transcript turns -> structured ThreadSummary
  - Reconnect recap      : stored summary -> RecapRequest -> freshness check
                           -> Rime-formatted spoken text (with per-step ms)
  - Demo thread reset    : clear the single demo thread between takes

The spoken recap text returned here is later sent to the Rime HTTP API by
``dashboard/server.py`` (``POST /api/rime/tts``) — audio is never proxied or
mixed by this module.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from modules.brain.recap import build_recap_request
from modules.brain.service import BrainService
from modules.brain.store import ThreadMemoryStore
from modules.voice.freshness_checker import FreshnessChecker
from modules.voice.recap_text_builder import RecapTextBuilder
from modules.voice.rime_tts_client import RimeTtsClient
from shared.config import settings
from shared.schemas import (
    CallState,
    CallStateEvent,
    Speaker,
    ThreadSummary,
    TranscriptEvent,
)

logger = logging.getLogger(__name__)


# ── Injectable singletons (swap in tests) ──────────────────────────────────────

#: Thread Memory Store used by the demo.  Replaced with an in-memory store in tests.
_demo_store: Optional[ThreadMemoryStore] = None

#: BrainService bound to ``_demo_store``.
_demo_brain: Optional[BrainService] = None

#: FreshnessChecker used by the reconnect-recap flow.
_demo_freshness: Optional[FreshnessChecker] = None

#: Recap text builder (Rime prompting-guide validator).
_demo_builder: Optional[RecapTextBuilder] = None

#: Rime TTS request builder.
_demo_tts_client: Optional[RimeTtsClient] = None


def configure(
    store: Optional[ThreadMemoryStore] = None,
    brain: Optional[BrainService] = None,
    freshness: Optional[FreshnessChecker] = None,
    builder: Optional[RecapTextBuilder] = None,
    tts_client: Optional[RimeTtsClient] = None,
) -> None:
    """
    Inject custom implementations (used by tests).  Passing ``None`` leaves
    the current singleton untouched.
    """
    global _demo_store, _demo_brain, _demo_freshness, _demo_builder, _demo_tts_client
    if store is not None:
        _demo_store = store
    if brain is not None:
        _demo_brain = brain
    if freshness is not None:
        _demo_freshness = freshness
    if builder is not None:
        _demo_builder = builder
    if tts_client is not None:
        _demo_tts_client = tts_client


def get_store() -> ThreadMemoryStore:
    global _demo_store
    if _demo_store is None:
        _demo_store = ThreadMemoryStore()  # settings.database_url (SQLite by default)
    return _demo_store


def get_brain() -> BrainService:
    global _demo_brain
    if _demo_brain is None:
        _demo_brain = BrainService(store=get_store())
    return _demo_brain


def get_freshness() -> FreshnessChecker:
    global _demo_freshness
    if _demo_freshness is None:
        _demo_freshness = FreshnessChecker()
    return _demo_freshness


def get_builder() -> RecapTextBuilder:
    global _demo_builder
    if _demo_builder is None:
        _demo_builder = RecapTextBuilder()
    return _demo_builder


def get_tts_client() -> RimeTtsClient:
    global _demo_tts_client
    if _demo_tts_client is None:
        _demo_tts_client = RimeTtsClient()
    return _demo_tts_client


# ── Internal helpers ───────────────────────────────────────────────────────────

def _speaker_enum(value: str) -> Speaker:
    try:
        return Speaker(value.upper())
    except ValueError:
        raise ValueError(f"speaker must be USER or CALLER, got {value!r}") from None


def _make_transcript_event(
    session_id: str,
    speaker: Speaker,
    text: str,
    index_ms: int = 0,
) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        speaker=speaker,
        text=text,
        is_final=True,
        confidence=0.98,
        start_ms=index_ms,
        end_ms=index_ms + max(400, int(len(text) * 45)),
        timestamp=datetime.now(tz=timezone.utc),
    )


# ── Public operations used by routes ──────────────────────────────────────────


async def ensure_ready() -> None:
    """Initialise the underlying SQLite store (idempotent)."""
    await get_brain().init()


async def ingest_turn(session_id: str, speaker: str, text: str) -> None:
    """
    Record one final transcript turn for the demo call.

    Only non-empty final text is persisted (Brain ignores interim noise).
    """
    cleaned = text.strip()
    if not cleaned:
        return
    event = _make_transcript_event(session_id, _speaker_enum(speaker), cleaned)
    await get_brain().on_transcript_event(event)


async def end_demo_call(
    session_id: str,
    caller_id: str,
    interrupted: bool = True,
    caller_name: Optional[str] = None,
) -> ThreadSummary:
    """
    Extract structured memory from the buffered turns and persist it.

    Raises ``ValueError`` when no final turns were recorded for the session —
    the demo needs real conversation turns before the recap can exist.
    """
    brain = get_brain()
    await brain.init()

    state = CallState.DISCONNECTED if interrupted else CallState.COMPLETED
    event = CallStateEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        thread_id=None,
        state=state,
        previous_state=CallState.CONNECTED,
        caller_id=caller_id,
        is_reconnect=False,
        timestamp=datetime.now(tz=timezone.utc),
    )
    summary = await brain.on_call_ended(event)
    if summary is None:
        raise ValueError(
            f"No final turns were recorded for session {session_id!r}. "
            "Run the conversation stage first."
        )
    if caller_name:
        # Store the known caller display name (e.g. 'Z') on the persisted summary.
        # Heuristic extraction may not have recognised the name from speech, so
        # surface it in the headline as well when it was missing.
        headline = summary.headline
        if caller_name and headline.startswith("Caller "):
            headline = headline.replace("Caller", caller_name, 1)
        updated = summary.model_copy(
            update={"caller_name": caller_name, "headline": headline}
        )
        await brain.store.save_summary(updated)
        summary = updated
    return summary


async def get_thread(caller_id: str) -> Optional[ThreadSummary]:
    """Return the latest stored ThreadSummary for a caller (or None)."""
    brain = get_brain()
    await brain.init()
    return await brain.store.get_summary_by_caller(caller_id)


async def reset_thread(caller_id: str, session_ids: list[str]) -> None:
    """
    Reset the single demo thread to a clean baseline between takes:
      - drop the stored summary for the caller
      - clear any buffered session turns for the demo session ids
    """
    store = get_store()
    await store.init_db()
    for session_id in session_ids:
        try:
            await store.clear_session_turns(session_id)
        except Exception as exc:  # pragma: no cover - defensive cleanup
            logger.warning("Could not clear session %s turns: %s", session_id, exc)
    summary = await store.get_summary_by_caller(caller_id)
    if summary is not None:
        await store.delete_summary(summary.thread_id)


async def build_reconnect_recap(
    caller_id: str,
    session_id: str,
    ring_window_s: float = 25.0,
    language: str = "en",
) -> dict[str, Any]:
    """
    Produce a ready-to-speak recap for a returning caller.

    Mirrors the production data flow  Brain -> Voice & Facts:
        stored ThreadSummary
          -> RecapRequest (with facts to re-verify)
          -> FreshnessChecker.check()          (step 1, timed)
          -> RecapTextBuilder.build()          (step 2, timed — Rime lint enforced)
          -> RimeTtsClient.make_request()      (step 3, timed)

    ``language`` localises the fixed recap phrasing (en / hi) — thread-memory
    content is kept exactly as it was recorded.

    Returns a JSON-safe payload containing the final spoken text plus the
    freshness results and per-step timings for the on-screen event log.
    """
    brain = get_brain()
    await brain.init()

    summary = await brain.store.get_summary_by_caller(caller_id)
    if summary is None:
        raise LookupError(
            f"No stored thread for caller {caller_id!r}. Complete call one first."
        )

    recap_request = build_recap_request(
        summary=summary,
        session_id=session_id,
        estimated_ring_window_seconds=ring_window_s,
    )

    # Step 1 — freshness
    t0 = time.monotonic()
    freshness = await get_freshness().check(recap_request)
    step1_ms = int((time.monotonic() - t0) * 1000)

    # Step 2 — Rime-formatted spoken text (validated against the prompting guide)
    t0 = time.monotonic()
    text = get_builder().build(
        summary=recap_request.summary,
        freshness=freshness,
        urgency=recap_request.urgency,
        language=language,
    )
    step2_ms = int((time.monotonic() - t0) * 1000)

    # Step 3 — TTS request (model/speaker/speed selected for this content)
    t0 = time.monotonic()
    tts_request = get_tts_client().make_request(
        recap_request=recap_request,
        spoken_text=text,
        language=language,
    )
    step3_ms = int((time.monotonic() - t0) * 1000)

    total_ms = step1_ms + step2_ms + step3_ms
    logger.info(
        "sim recap built request_id=%s total=%dms (freshness=%dms text=%dms tts=%dms)",
        recap_request.request_id,
        total_ms,
        step1_ms,
        step2_ms,
        step3_ms,
    )

    return {
        "request_id": recap_request.request_id,
        "thread_id": summary.thread_id,
        "session_id": session_id,
        "urgency": recap_request.urgency.value,
        "headline": summary.headline,
        "text": tts_request.text,
        "model": tts_request.model.value,
        "speaker": tts_request.speaker,
        "language": tts_request.language,
        "time_scale_factor": tts_request.time_scale_factor,
        "freshness": freshness.model_dump(mode="json"),
        "metrics": {
            "freshness_ms": step1_ms,
            "text_ms": step2_ms,
            "tts_ms": step3_ms,
            "total_ms": total_ms,
        },
    }
