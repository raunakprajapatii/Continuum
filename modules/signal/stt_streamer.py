"""
modules/signal/stt_streamer.py
--------------------------------
Streaming STT module — Pair B (Signal).

Provides a unified ``StreamingSTT`` interface that:
  - On the live path (``USE_MOCKS=False``): drives Deepgram or AssemblyAI via
    the LiveKit Agents plugin API, performing real-time diarised transcription.
  - On the mock path (``USE_MOCKS=True``): replays the scripted conversation
    from ``mocks.mock_stt.MockSTT`` so the whole pipeline can run without
    any external services.

Emits: ``TranscriptEvent`` (one per final utterance chunk).
Consumer: Brain (Pair C) via a shared async queue or callback.

Speaker tagging
---------------
Deepgram's ``diarize=true`` option tags utterances by speaker index (0, 1, …).
We map index 0 → ``Speaker.USER`` (the person who has the Continuum app) and
index 1 → ``Speaker.CALLER`` (the remote party). This is correct for 2-party
phone calls where the STT is capturing both legs. For conference calls this
heuristic breaks down — callers beyond index 1 are tagged ``UNKNOWN``.

If the STT provider does not return a speaker index (confidence-gated or
partial chunk), we default to ``Speaker.UNKNOWN``.

Confidence gating
-----------------
Chunks with ``confidence < STT_CONFIDENCE_THRESHOLD`` are emitted with
``is_final=True`` but flagged ``Speaker.UNKNOWN`` so Brain knows to treat
them as low-reliability input.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Callable, Coroutine, Optional

from shared.config import settings
from shared.schemas import Speaker, TranscriptEvent

logger = logging.getLogger(__name__)

# Minimum confidence to assign a definitive speaker label.
# Below this threshold, the chunk is tagged UNKNOWN.
STT_CONFIDENCE_THRESHOLD: float = 0.70

# Type alias for the async callback Brain passes in
TranscriptCallback = Callable[[TranscriptEvent], Coroutine]


# ── Speaker index → Speaker enum ─────────────────────────────────────────────


def _diarize_speaker(speaker_index: Optional[int]) -> Speaker:
    """
    Map a 0-based diarization index to a ``Speaker`` enum value.

    Index 0 is always the user (near-end leg); index 1 is the caller (far-end).
    Any other index is UNKNOWN.
    """
    if speaker_index == 0:
        return Speaker.USER
    if speaker_index == 1:
        return Speaker.CALLER
    return Speaker.UNKNOWN


# ── Live STT wrapper (Deepgram / AssemblyAI) ─────────────────────────────────


class _LiveSTT:
    """
    Wraps the LiveKit Agents STT plugin for Deepgram or AssemblyAI.

    Not instantiated directly — use ``StreamingSTT`` which picks the right
    backend based on ``settings.stt_provider``.

    The LiveKit Agents STT plugin yields ``SpeechEvent`` objects (from the
    ``livekit.agents.stt`` namespace). We convert those to ``TranscriptEvent``.
    """

    def __init__(self, session_id: str, thread_id: Optional[str]) -> None:
        self._session_id = session_id
        self._thread_id = thread_id
        self._start_ms: int = 0
        self._elapsed_ms: int = 0

    def _build_stt_plugin(self):  # type: ignore[return]
        """
        Instantiate the correct LiveKit STT plugin based on ``settings.stt_provider``.

        Returns a ``livekit.agents.stt.STT`` instance (Deepgram or AssemblyAI).
        """
        if settings.stt_provider == "deepgram":
            try:
                from livekit.plugins.deepgram import STT  # type: ignore[import-untyped]

                logger.info("StreamingSTT: using Deepgram provider")
                return STT(
                    api_key=settings.deepgram_api_key,
                    language="en",
                    model="nova-2",
                    smart_format=True,
                    diarize=True,
                    interim_results=True,
                )
            except ImportError as exc:
                raise RuntimeError(
                    "livekit-plugins-deepgram is not installed. "
                    "Run: pip install livekit-plugins-deepgram"
                ) from exc

        elif settings.stt_provider == "assemblyai":
            try:
                from livekit.plugins.assemblyai import STT  # type: ignore[import-untyped]

                logger.info("StreamingSTT: using AssemblyAI provider")
                return STT(api_key=settings.assemblyai_api_key)
            except ImportError as exc:
                raise RuntimeError(
                    "livekit-plugins-assemblyai is not installed."
                ) from exc

        else:
            raise ValueError(
                f"Unknown stt_provider: {settings.stt_provider!r}. "
                f"Must be 'deepgram' or 'assemblyai'."
            )

    async def stream(self) -> AsyncIterator[TranscriptEvent]:  # type: ignore[return]
        """
        Yield ``TranscriptEvent`` objects from the live STT provider.

        This is an async generator that runs until the audio stream ends.
        The LiveKit plugin handles WebSocket reconnects internally.

        In production the caller feeds audio frames into the plugin's
        push_frame() interface; those frames originate from the LiveKit
        room participant's audio track.

        Note: This generator is intentionally left as a skeleton for the
        LiveKit Agents integration sprint (Pair A + B). The diarization
        and frame-feeding logic requires a live ``rtc.AudioStream`` from
        LiveKit, which is available only inside a running Agent context.
        """
        stt = self._build_stt_plugin()

        # The LiveKit Agents plugin exposes a context-manager-based stream.
        # Inside an Agent function the usage would be:
        #
        #   async with stt.stream() as stt_stream:
        #       async for event in stt_stream:
        #           yield self._convert(event)
        #
        # Until Pair A provides the audio track, we yield nothing (empty stream).
        # This prevents any crash in module-level import / process start tests.
        logger.warning(
            "LiveSTT.stream(): no LiveKit audio track attached. "
            "Pair A must call attach_audio_stream() before events flow."
        )
        return
        yield  # make this a generator without an actual loop

    def _convert(  # noqa: ANN001
        self,
        speech_event,
        speaker_index: Optional[int] = None,
    ) -> Optional[TranscriptEvent]:
        """
        Convert a LiveKit ``SpeechEvent`` to a ``TranscriptEvent``.

        Returns ``None`` for non-final events when the text is empty.
        """
        if not hasattr(speech_event, "alternatives") or not speech_event.alternatives:
            return None

        alt = speech_event.alternatives[0]
        text: str = alt.text.strip()
        if not text:
            return None

        confidence: Optional[float] = getattr(alt, "confidence", None)
        is_final: bool = getattr(speech_event, "is_final", True)

        # Apply confidence gating for speaker assignment
        speaker = _diarize_speaker(speaker_index)
        if confidence is not None and confidence < STT_CONFIDENCE_THRESHOLD:
            speaker = Speaker.UNKNOWN

        duration_ms = int(len(text) * 60)  # rough estimate
        event = TranscriptEvent(
            event_id=str(uuid.uuid4()),
            session_id=self._session_id,
            thread_id=self._thread_id,
            speaker=speaker,
            text=text,
            is_final=is_final,
            confidence=confidence,
            start_ms=self._elapsed_ms,
            end_ms=self._elapsed_ms + duration_ms if is_final else None,
            timestamp=datetime.now(tz=timezone.utc),
        )
        if is_final:
            self._elapsed_ms += duration_ms
        return event


# ── Mock STT wrapper ──────────────────────────────────────────────────────────


class _MockSTT:
    """
    Wraps ``mocks.mock_stt.MockSTT`` to match the same async-generator interface.

    Activated when ``settings.use_mocks=True``.
    """

    def __init__(
        self,
        session_id: str,
        thread_id: Optional[str],
        include_partial: bool = False,
    ) -> None:
        self._session_id = session_id
        self._thread_id = thread_id
        self._include_partial = include_partial

    async def stream(self) -> AsyncIterator[TranscriptEvent]:
        from mocks.mock_stt import MockSTT

        mock = MockSTT(include_partial=self._include_partial)
        logger.info("StreamingSTT: using MockSTT (USE_MOCKS=true)")

        async for event in mock.transcript_stream():
            # Override session/thread IDs to match the live session context
            yield TranscriptEvent(
                event_id=event.event_id,
                session_id=self._session_id,
                thread_id=self._thread_id,
                speaker=event.speaker,
                text=event.text,
                is_final=event.is_final,
                confidence=event.confidence,
                start_ms=event.start_ms,
                end_ms=event.end_ms,
                timestamp=event.timestamp,
            )


# ── Public interface ──────────────────────────────────────────────────────────


class StreamingSTT:
    """
    Unified Streaming STT entry point for Pair B.

    Automatically selects the live or mock implementation based on
    ``settings.use_mocks``. The Signal Agent only interacts with this class
    — never with ``_LiveSTT`` or ``_MockSTT`` directly.

    Usage::

        stt = StreamingSTT(
            session_id=event.session_id,
            thread_id=event.thread_id,
            on_transcript=brain_queue.put,
        )

        # Start streaming (non-blocking — runs until stop() is called)
        stt_task = asyncio.create_task(stt.run())

        # Later, when the call ends:
        await stt.stop()
        await stt_task

    Attributes:
        session_id:  The current call session ID.
        thread_id:   The matched thread ID, if a reconnect was detected.
        on_transcript: Async callback invoked for each final ``TranscriptEvent``.
    """

    def __init__(
        self,
        session_id: str,
        thread_id: Optional[str],
        on_transcript: TranscriptCallback,
        include_partial: bool = False,
    ) -> None:
        self.session_id = session_id
        self.thread_id = thread_id
        self._on_transcript = on_transcript
        self._include_partial = include_partial
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def _make_backend(self) -> "_LiveSTT | _MockSTT":
        if settings.use_mocks:
            return _MockSTT(
                session_id=self.session_id,
                thread_id=self.thread_id,
                include_partial=self._include_partial,
            )
        return _LiveSTT(
            session_id=self.session_id,
            thread_id=self.thread_id,
        )

    async def run(self) -> None:
        """
        Main streaming loop. Runs until ``stop()`` is called.

        For each final ``TranscriptEvent`` produced by the backend, invokes
        ``on_transcript`` as an async coroutine. Filters out non-final chunks
        unless ``include_partial`` was requested.
        """
        backend = self._make_backend()
        logger.info(
            "StreamingSTT.run(): starting — session=%s use_mocks=%s",
            self.session_id,
            settings.use_mocks,
        )

        try:
            async for event in backend.stream():
                if self._stop_event.is_set():
                    logger.info("StreamingSTT: stop requested mid-stream; halting.")
                    break

                # Only forward final events to Brain (unless partials requested)
                if not self._include_partial and not event.is_final:
                    continue

                try:
                    await self._on_transcript(event)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "StreamingSTT: on_transcript callback raised an error "
                        "(event_id=%s); continuing stream.",
                        event.event_id,
                    )
        except asyncio.CancelledError:
            logger.info("StreamingSTT.run(): cancelled (task was cancelled).")
            raise
        except Exception:
            logger.exception("StreamingSTT.run(): unhandled error in STT stream.")
            raise
        finally:
            logger.info("StreamingSTT.run(): stream ended — session=%s", self.session_id)

    async def stop(self) -> None:
        """
        Signal the streaming loop to stop after the current event.

        Idempotent — safe to call multiple times.
        """
        self._stop_event.set()
        logger.info("StreamingSTT.stop(): stop flag set — session=%s", self.session_id)
