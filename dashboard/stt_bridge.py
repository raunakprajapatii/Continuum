"""
dashboard/stt_bridge.py
-----------------------
WebSocket bridge from the demo dashboard to Deepgram streaming STT.

The browser sends raw PCM16 mono audio at 16 kHz over a WebSocket to
``dashboard/server.py`` (``/api/stt/stream``); this module relays those bytes
upstream to Deepgram's live transcription endpoint and streams transcript
messages back to the browser as JSON::

    {type: "ready", session_id: ...}
    {type: "transcript", speaker: "USER", text: "...", is_final: false, confidence: 0.9}
    {type: "error", code: "...", message: "..."}

The ``speaker`` query parameter (USER or CALLER) tags every transcript so the
same browser microphone can record both sides of a live two-way conversation:
User 1 records as USER, User 2 (Z in the demo) records as CALLER.

Deepgram key is read from settings and is never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from shared.config import settings

logger = logging.getLogger(__name__)

DEEPGRAM_WS = "wss://api.deepgram.com/v1/listen"

#: Model used for the dashboard's live transcription.  Override via DEEPGRAM_MODEL.
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2-general")


class SttUnavailableError(RuntimeError):
    """Raised when the live STT provider cannot be used (mocks / no key)."""


def stt_available() -> bool:
    """True when a real Deepgram key is configured and mocks are disabled."""
    if settings.use_mocks:
        return False
    return bool(settings.deepgram_api_key)


def _upstream_uri(language: Optional[str] = None) -> str:
    params = {
        "model": DEEPGRAM_MODEL,
        "encoding": "linear16",
        "sample_rate": "16000",
        "channels": "1",
        "interim_results": "true",
        "endpointing": "250",
        "punctuate": "true",
        "smart_format": "true",
        "language": language or settings.rime_default_language or "en",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{DEEPGRAM_WS}?{query}"


async def connect_upstream(language: Optional[str] = None) -> Any:
    """
    Open the upstream Deepgram WebSocket.

    Returns the websockets client connection.  Raises ``SttUnavailableError``
    with a human-readable message when connection or auth fails.
    """
    import websockets

    uri = _upstream_uri(language)
    headers = {"Authorization": f"Token {settings.deepgram_api_key}"}
    try:
        conn = await websockets.connect(
            uri,
            additional_headers=headers,
            ping_interval=20,
            max_size=2**22,
            open_timeout=10,
        )
    except TypeError:
        # Older websockets API used ``extra_headers``.
        conn = await websockets.connect(
            uri,
            extra_headers=headers,
            max_size=2**22,
            open_timeout=10,
        )
    return conn


def _dg_transcript(message: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extract a transcript message from a Deepgram result (None if empty)."""
    if message.get("type") != "Results":
        return None
    channel = message.get("channel") or {}
    alternatives = channel.get("alternatives") or []
    if not alternatives:
        return None
    best = alternatives[0]
    text = (best.get("transcript") or "").strip()
    if not text:
        return None
    confidence = best.get("confidence")
    return {
        "text": text,
        "is_final": bool(message.get("is_final", False)),
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
    }


VALID_SPEAKERS = ("USER", "CALLER")


def normalize_speaker(speaker: Optional[str]) -> str:
    """
    Validate + normalise the speaker label for a live mic session.

    User 1 records as USER, User 2 (the remote party, Z in the demo) records
    as CALLER — matching the Speaker enum used by the Brain extractor.

    Raises ``ValueError`` for anything else.
    """
    value = (speaker or "USER").strip().upper()
    if value not in VALID_SPEAKERS:
        raise ValueError(f"speaker must be one of {VALID_SPEAKERS}, got {speaker!r}")
    return value


async def run_stt_relay(
    browser_ws: Any,
    session_id: str,
    speaker: Optional[str] = "USER",
    language: Optional[str] = None,
) -> None:
    """
    Relay audio between the browser WebSocket and Deepgram until either side
    disconnects.  Sends ``ready`` first, then transcript events tagged with the
    ``speaker`` who is recording (USER or CALLER).

    ``language`` (BCP-47, e.g. "en" / "hi") is forwarded to Deepgram so a
    Hindi conversation is transcribed in Hindi; defaults to
    ``settings.rime_default_language``.
    """
    speaker = normalize_speaker(speaker)

    if not stt_available():
        reason = (
            "Mock mode is active (USE_MOCKS=true). Live Deepgram STT is only "
            "available with USE_MOCKS=false and a DEEPGRAM_API_KEY."
            if settings.use_mocks
            else "DEEPGRAM_API_KEY is not configured."
        )
        await browser_ws.send_json(
            {"type": "error", "code": "stt_unavailable", "message": reason}
        )
        return

    try:
        upstream = await connect_upstream(language=language)
    except Exception as exc:  # pragma: no cover - depends on live network
        logger.error("Deepgram upstream connect failed: %s", exc)
        await browser_ws.send_json(
            {
                "type": "error",
                "code": "stt_upstream_failed",
                "message": f"Could not reach Deepgram streaming STT: {exc}",
            }
        )
        return

    try:
        await browser_ws.send_json(
            {
                "type": "ready",
                "session_id": session_id,
                "speaker": speaker,
                "provider": "deepgram",
                "model": DEEPGRAM_MODEL,
                "ts": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
    except Exception:
        await upstream.close()
        return

    async def upstream_reader() -> None:
        """Forward Deepgram transcripts back to the browser."""
        async for raw in upstream:
            if isinstance(raw, bytes):
                continue  # Audio shouldn't come back down; ignore defensively.
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            item = _dg_transcript(message)
            if item is None:
                continue
            await browser_ws.send_json(
                {
                    "type": "transcript",
                    "speaker": speaker,
                    "text": item["text"],
                    "is_final": item["is_final"],
                    "confidence": item["confidence"],
                    "ts": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

    reader_task = asyncio.create_task(upstream_reader())
    try:
        # Relay browser audio bytes upstream until the tab closes.
        async for message in browser_ws.iter_bytes():
            if not message:
                continue
            try:
                await upstream.send(message)
            except Exception:
                break
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await upstream.close()
        except Exception:
            pass
