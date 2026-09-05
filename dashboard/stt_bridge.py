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

Hinglish language policy
------------------------
The demo mic transcribes spoken Hinglish (Hindi + English code-switching).
Deepgram's multilingual mode (``language=multi`` on Nova-3) is documented by
Deepgram staff as frequently misdetecting Hindi as Spanish, so this bridge
uses the dedicated Nova-3 Hindi model (``language=hi``) instead: it handles
Hindi-English code-switching accurately and never drifts into Spanish.

One caveat: ``language=hi`` returns Hindi in Devanagari script (Latin-script
Hindi ``hi-Latn`` only exists on legacy models). Every transcript is therefore
romanized to Latin-script Hinglish by ``dashboard.hinglish`` before it reaches
the browser — English tokens Deepgram already emits in Latin pass through
unchanged, so "hello भाई कैसे हो" arrives as "hello bhai kaise ho".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from dashboard.hinglish import romanize_hinglish
from shared.config import settings

logger = logging.getLogger(__name__)

DEEPGRAM_WS = "wss://api.deepgram.com/v1/listen"

#: Model used for the dashboard's live transcription.  Override via DEEPGRAM_MODEL.
#: nova-3 is the only current Deepgram model with good Hindi-English
#: code-switching (nova-2's multi mode is Spanish + English only).
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3-general")


class SttUnavailableError(RuntimeError):
    """Raised when the live STT provider cannot be used (mocks / no key)."""


def stt_available() -> bool:
    """True when a real Deepgram key is configured and mocks are disabled."""
    if settings.use_mocks:
        return False
    return bool(settings.deepgram_api_key)


def _upstream_uri(language: Optional[str] = None) -> str:
    language = language or settings.rime_default_language or "en"
    # Deepgram recommends a tighter endpointing value (100 ms) when Hindi is
    # involved — both the multilingual mode and the dedicated ``hi`` model do
    # Hindi/English code-switching, so turns need to segment quickly.
    endpointing = "100" if language.strip().lower() in ("hi", "multi") else "250"
    params = {
        "model": DEEPGRAM_MODEL,
        "encoding": "linear16",
        "sample_rate": "16000",
        "channels": "1",
        "interim_results": "true",
        "endpointing": endpointing,
        "punctuate": "true",
        "smart_format": "true",
        "language": language,
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

    ``language`` is forwarded to Deepgram. For Hinglish voice input the demo
    sends "hi" (the Nova-3 Hindi model, which handles Hindi/English
    code-switching accurately — Nova-3 ``multi`` is prone to misdetecting
    Hindi as Spanish). Every transcript is romanized to Latin-script Hinglish
    before it is sent to the browser; defaults to
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
                    "text": romanize_hinglish(item["text"]),
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
