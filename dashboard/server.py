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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "audio_policy": "private-track-only"}


@app.get("/api/events", response_model=list[DashboardEvent])
async def events() -> list[DashboardEvent]:
    return store.snapshot()


@app.post("/api/private-recap-audio")
async def private_recap_audio() -> Response:
    """Return Rime audio for the user-private dashboard monitor only."""
    if settings.use_mocks:
        raise HTTPException(status_code=503, detail="Rime audio is unavailable while USE_MOCKS=true.")
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
