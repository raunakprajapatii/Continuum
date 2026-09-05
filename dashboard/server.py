"""Small FastAPI event surface used by the Continuum demo dashboard.

The UI can run standalone for rehearsals.  In an integrated demo, transport,
signal, brain, and voice modules POST their real event records here and the
dashboard receives them via Server-Sent Events.  No audio is ever proxied or
mixed by this service.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from dashboard import sim_engine, stt_bridge
from modules.signal.voice_command import VoiceCommandDetector
from shared.config import settings


class DashboardEvent(BaseModel):
    """A timestamped event emitted by an existing Continuum module."""

    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: str = Field(min_length=3, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    meta: dict[str, Any] = Field(default_factory=dict)


class EventStore:
    """In-memory append-only event feed suitable for the hackathon dashboard."""

    def __init__(self) -> None:
        self._events: deque[DashboardEvent] = deque(maxlen=500)
        self._subscribers: set[asyncio.Queue[DashboardEvent]] = set()

    def append(self, event: DashboardEvent) -> None:
        self._events.append(event)
        for subscriber in tuple(self._subscribers):
            subscriber.put_nowait(event)

    def snapshot(self) -> list[DashboardEvent]:
        return list(self._events)

    async def subscribe(self) -> AsyncIterator[DashboardEvent]:
        queue: asyncio.Queue[DashboardEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


store = EventStore()
app = FastAPI(title="Continuum Dashboard Events", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_DEMO_RECAP = (
    "Z wanted the Q3 number. You said you would check with finance. "
    "Heads up — the price is now $420. Pick up with the updated number."
)


# ── Rime synthesis helpers (used by the private-track audio endpoints) ────────


class RimeTtsBody(BaseModel):
    """Request body for generic Rime synthesis on the private track."""

    text: str = Field(..., min_length=1, max_length=3000)
    speaker: str | None = Field(
        default=None, description="Override the voice ID from the live Rime catalog."
    )
    model: str | None = Field(
        default=None, description="Override the model ID (coda / mist_v2 / mist_v3)."
    )
    time_scale_factor: float | None = Field(
        default=None,
        ge=0.5,
        le=2.0,
        description=(
            "Speed multiplier (<1.0 = faster). Defaults to "
            "settings.rime_time_scale_factor when omitted."
        ),
    )
    lang: str | None = Field(
        default=None,
        description=(
            "BCP-47 language for synthesis (en / hi). Defaults to "
            "settings.rime_default_language when omitted."
        ),
    )


class _RimeSynthesis:
    """Small result wrapper for a successful Rime HTTP call."""

    def __init__(self, content: bytes, media_type: str) -> None:
        self.content = content
        self.media_type = media_type


def _rime_language_code(value: str) -> str:
    """
    Map a BCP-47-ish language to the code Rime accepts in TTS requests.

    Rime's mist family requires 3-letter codes (``eng``); the shorter form
    (``en``) is rejected with "Language 'en' is not supported". coda accepts
    both, so normalising to ``eng`` is safe for every model.  Hindi is
    ``hin`` on every model, and the code maps the UI's ``hi``/``hi-IN``
    values accordingly.
    """
    normalized = (value or "").strip().lower().split("-")[0]
    if normalized == "en":
        return "eng"
    if normalized == "hi":
        return "hin"
    return normalized or "eng"


def _rime_enabled() -> bool:
    """
    True when a real Rime API key is configured.

    ``USE_MOCKS=true`` still allows Rime when a key is present — Rime remains
    the only TTS provider (AGENTS.md Rule 2); mocks only gate the other
    services.  With no key at all the recap raises a clear error instead of
    silently substituting another provider.
    """
    key = settings.rime_api_key or ""
    return bool(key) and not key.startswith("YOUR_")


async def _synthesize_rime(
    text: str,
    *,
    speaker: str | None = None,
    model: str | None = None,
    time_scale_factor: float | None = None,
    lang: str | None = None,
) -> _RimeSynthesis:
    """
    Call the Rime TTS API for ``text``.

    Raises HTTPException:
      503 — no RIME_API_KEY configured (mock rehearsal / misconfigured env)
      502 — Rime was unreachable or declined the request

    No other TTS provider is ever substituted (AGENTS.md Rule 2).  When a
    real key is present Rime is used even under USE_MOCKS=true — mocks gate
    STT/LLM/freshness, not the Rime voice.
    """
    if not _rime_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Rime audio is unavailable: no RIME_API_KEY configured "
                "(USE_MOCKS=true rehearsal mode). Set RIME_API_KEY in .env "
                "to enable the live Rime recap path."
            ),
        )
    payload = {
        "text": text,
        "modelId": (model or settings.rime_default_model).replace("_", ""),
        "speaker": speaker or settings.rime_default_speaker,
        "lang": _rime_language_code(lang or settings.rime_default_language),
        "samplingRate": 22050,
        "audioFormat": "wav",
        "timeScaleFactor": time_scale_factor or settings.rime_time_scale_factor,
    }
    headers = {
        "Authorization": f"Bearer {settings.rime_api_key}",
        "Accept": "audio/wav",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            upstream = await client.post(settings.rime_api_url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Rime could not be reached: {exc}"
        ) from exc
    if upstream.is_error:
        raise HTTPException(status_code=502, detail="Rime declined the TTS request.")
    content_type = upstream.headers.get("content-type", "audio/wav").split(";")[0]
    if not content_type.startswith("audio/"):
        raise HTTPException(
            status_code=502, detail="Rime returned an unexpected response type."
        )
    return _RimeSynthesis(content=upstream.content, media_type=content_type)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "audio_policy": "private-track-only"}


@app.get("/api/events", response_model=list[DashboardEvent])
async def events() -> list[DashboardEvent]:
    return store.snapshot()


@app.post("/api/private-recap-audio")
async def private_recap_audio() -> Response:
    """Return Rime audio for the user-private dashboard monitor only."""
    if not _rime_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Rime audio is unavailable: no RIME_API_KEY configured "
                "(USE_MOCKS=true rehearsal mode)."
            ),
        )
    payload = {
        "text": _DEMO_RECAP,
        "modelId": settings.rime_default_model.replace("_", ""),
        "speaker": settings.rime_default_speaker,
        "lang": "eng",
        "samplingRate": 22050,
        "audioFormat": "wav",
        "timeScaleFactor": settings.rime_time_scale_factor,
    }
    headers = {
        "Authorization": f"Bearer {settings.rime_api_key}",
        "Accept": "audio/wav",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.post(settings.rime_api_url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Rime could not be reached for the private recap demo.") from exc
    if upstream.is_error:
        raise HTTPException(status_code=502, detail="Rime declined the private recap demo request.")
    content_type = upstream.headers.get("content-type", "audio/wav").split(";")[0]
    if not content_type.startswith("audio/"):
        raise HTTPException(status_code=502, detail="Rime returned an unexpected response type.")
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"X-Continuum-Track": settings.private_track_id},
    )


@app.post("/api/rime/tts")
async def rime_tts(body: RimeTtsBody) -> Response:
    """
    Synthesize arbitrary spoken text with Rime for the user-private track.

    Used by the interactive demo simulation to speak the freshly generated
    recap.  The response carries ``X-Continuum-Track`` so the dashboard can
    verify the audio is bound to the private whisper track only.
    """
    synth = await _synthesize_rime(
        body.text,
        speaker=body.speaker,
        model=body.model,
        time_scale_factor=body.time_scale_factor,
        lang=body.lang,
    )
    return Response(
        content=synth.content,
        media_type=synth.media_type,
        headers={"X-Continuum-Track": settings.private_track_id},
    )


# ── Capabilities & demo simulation endpoints ───────────────────────────────────

_voice_command_detector = VoiceCommandDetector()


@app.get("/api/capabilities")
async def capabilities() -> dict:
    """
    Report which live providers are usable right now so the demo UI can guide
    the presenter (provider badge values come from here as well).
    """
    rime_enabled = _rime_enabled()
    # Report the voice/model the RimeTtsClient actually resolves to (the recap
    # pipeline swaps the placeholder "sol" for the Continuum optimal voice).
    from modules.voice.rime_tts_client import DEFAULT_CONTINUUM_SPEAKER

    effective_speaker = (
        DEFAULT_CONTINUUM_SPEAKER
        if settings.rime_default_speaker in ("sol", "default", "")
        else settings.rime_default_speaker
    )
    effective_model = settings.rime_default_model
    stt_available = stt_bridge.stt_available()

    # Report whether the recap writer can use Gemini (ConversationExtractor
    # falls back to a deterministic heuristic when no key is configured).
    from modules.brain.extractor import ConversationExtractor

    llm = {
        "enabled": bool(ConversationExtractor().api_key) and not settings.use_mocks,
        "provider": "gemini" if settings.gemini_api_key else "llm",
        "model": settings.llm_fast_model,
    }

    freshness = {
        "enabled": False,
        "price_usd": None,
        "endpoint": settings.mock_freshness_api_url,
    }
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(f"{settings.mock_freshness_api_url}/facts/price_usd")
        if response.is_success:
            freshness["enabled"] = True
            freshness["price_usd"] = (response.json() or {}).get("value")
    except httpx.HTTPError:
        pass  # offline -> demo UI shows a setup hint

    return {
        "use_mocks": settings.use_mocks,
        "rime": {
            "enabled": rime_enabled,
            "model": effective_model,
            "speaker": effective_speaker,
            "language": settings.rime_default_language,
            "endpoint": settings.rime_api_url,
            "time_scale_factor": settings.rime_time_scale_factor,
            "private_track_id": settings.private_track_id,
        },
        "stt": {
            "enabled": stt_available,
            "provider": settings.stt_provider,
            "detail": (
                ""
                if stt_available
                else (
                    "USE_MOCKS=true — set USE_MOCKS=false for live Deepgram STT."
                    if settings.use_mocks
                    else "DEEPGRAM_API_KEY missing in .env."
                )
            ),
        },
        "llm": llm,
        "freshness": freshness,
        # Readiness requires the two live spoken-output providers only. The
        # freshness data source is optional: without one, fact checks report
        # UNAVAILABLE and the recap simply omits staleness flags.
        "ready": rime_enabled and stt_available,
    }


class SimTurnBody(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=120)
    speaker: str = Field(..., description="USER or CALLER")
    text: str = Field(..., min_length=1, max_length=1000)


class SimCallEndedBody(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=120)
    caller_id: str = Field(..., min_length=1, max_length=120)
    caller_name: str | None = Field(default=None, max_length=80)
    interrupted: bool = Field(default=True)


class SimRecapBody(BaseModel):
    caller_id: str = Field(..., min_length=1, max_length=120)
    session_id: str = Field(..., min_length=1, max_length=120)
    ring_window_s: float = Field(default=25.0, ge=5.0, le=60.0)
    language: str = Field(
        default="en",
        min_length=2,
        max_length=12,
        description=(
            "Recap spoken-language frame (en / hi). Fixed recap phrasing is "
            "localised; thread memory content stays as recorded."
        ),
    )


class SimResetBody(BaseModel):
    caller_id: str = Field(..., min_length=1, max_length=120)
    session_ids: list[str] = Field(default_factory=list)


class BargeIntentBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


@app.post("/api/sim/turn", status_code=202)
async def sim_turn(body: SimTurnBody) -> dict:
    """Record one final transcript turn for the demo conversation."""
    if body.speaker.upper() not in ("USER", "CALLER"):
        raise HTTPException(status_code=422, detail="speaker must be USER or CALLER")
    await sim_engine.ensure_ready()
    await sim_engine.ingest_turn(body.session_id, body.speaker, body.text)
    return {"ok": True}


@app.post("/api/sim/call-ended")
async def sim_call_ended(body: SimCallEndedBody) -> dict:
    """Extract + persist the ThreadSummary for the ended demo call."""
    await sim_engine.ensure_ready()
    try:
        summary = await sim_engine.end_demo_call(
            session_id=body.session_id,
            caller_id=body.caller_id,
            interrupted=body.interrupted,
            caller_name=body.caller_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return summary.model_dump(mode="json")


@app.get("/api/sim/thread")
async def sim_thread(caller_id: str) -> dict:
    """Return the stored ThreadSummary for a caller (404 when none)."""
    caller_id = caller_id.strip()  # '+' in query strings may decode to a space
    await sim_engine.ensure_ready()
    summary = await sim_engine.get_thread(caller_id)
    if summary is None:
        raise HTTPException(
            status_code=404, detail=f"No stored thread for caller {caller_id!r}."
        )
    return summary.model_dump(mode="json")


@app.post("/api/sim/recap")
async def sim_recap(body: SimRecapBody) -> dict:
    """
    Build the spoken recap for a returning caller (Brain -> Voice & Facts).
    The caller can then fetch the audio via ``POST /api/rime/tts``.
    """
    await sim_engine.ensure_ready()
    try:
        return await sim_engine.build_reconnect_recap(
            caller_id=body.caller_id,
            session_id=body.session_id,
            ring_window_s=body.ring_window_s,
            language=body.language,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/sim/barge-intent")
async def sim_barge_intent(body: BargeIntentBody) -> dict:
    """Classify a barge-in utterance using the real VoiceCommandDetector."""
    result = _voice_command_detector.detect(body.text)
    return {
        "intent": result.intent.value,
        "matched_phrase": result.matched_phrase,
        "confidence": result.confidence,
        "raw_text": result.raw_text,
    }


@app.post("/api/sim/reset", status_code=200)
async def sim_reset(body: SimResetBody) -> dict:
    """Reset the demo thread to a clean baseline between takes."""
    await sim_engine.ensure_ready()
    await sim_engine.reset_thread(body.caller_id, body.session_ids)
    return {"ok": True}


# ── Live STT (browser mic -> Deepgram) ────────────────────────────────────────


@app.websocket("/api/stt/stream")
async def stt_stream(
    ws: WebSocket,
    session_id: str = "demo",
    speaker: str = "USER",
    language: str = "",
) -> None:
    """
    Browser mic bridge: raw PCM16 16 kHz audio up, transcript JSON down.

    ``speaker`` (USER or CALLER) labels every transcript event so both sides
    of a live two-way conversation can be recorded from the same browser mic.

    Messages down:
        {type: "ready"} | {type: "transcript", speaker, text, is_final} | {type: "error"}
    """
    await ws.accept()
    try:
        await stt_bridge.run_stt_relay(
            ws, session_id, speaker=speaker, language=language or None
        )
    except WebSocketDisconnect:
        pass  # presenter closed the tab / clicked away
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/api/events", status_code=202)
async def ingest_event(event: DashboardEvent) -> DashboardEvent:
    """Append a metadata-only event. Audio payloads are intentionally absent."""
    forbidden = {"audio", "audio_bytes", "caller_track_audio"}
    if forbidden.intersection(event.meta):
        raise HTTPException(status_code=400, detail="Dashboard accepts metadata only, never audio.")
    store.append(event)
    return event


@app.get("/api/events/stream")
async def stream_events() -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        for event in store.snapshot():
            yield f"data: {event.model_dump_json()}\n\n"
        async for event in store.subscribe():
            yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
