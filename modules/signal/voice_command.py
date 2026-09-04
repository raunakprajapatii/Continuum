"""
modules/signal/voice_command.py
---------------------------------
Ring-Window Voice Command & Barge-In Detector.

Listens for user speech during the RINGING window when an AI recap is playing in
the user's private whisper channel. Detects verbal commands such as:
  - "I know, just pick up the call" / "Answer" -> ANSWER_CALL (stops recap & connects call)
  - "Skip" / "I remember" / "Got it"           -> DISMISS_RECAP (stops recap, leaves ringing)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from shared.schemas import CallState, Speaker, TranscriptEvent


class VoiceCommandIntent(str, Enum):
    """Classified intent of user verbal command during incoming call ring window."""

    ANSWER_CALL = "ANSWER_CALL"
    """Stop recap immediately and connect the call hands-free."""

    DISMISS_RECAP = "DISMISS_RECAP"
    """Stop recap playback, but leave the phone ringing until user manually answers."""

    IGNORE = "IGNORE"
    """Unrelated ambient speech or conversation."""


@dataclass(frozen=True)
class VoiceCommandResult:
    """Result of voice command classification."""

    intent: VoiceCommandIntent
    raw_text: str
    matched_phrase: Optional[str] = None
    confidence: float = 1.0


class VoiceCommandDetector:
    """
    Lightweight, deterministic voice command matcher for ring-window user barge-in.
    Designed for sub-millisecond classification without external LLM latency.
    """

    # Patterns indicating intent to answer/pick up the call
    _ANSWER_PATTERNS = [
        r"\b(?:just\s+)?(?:pick\s+up|answer|take)(?:\s+(?:the\s+)?call)?\b",
        r"\b(?:i\s+know|okay|yeah|yes),?\s+(?:just\s+)?(?:pick\s+up|answer|take)\b",
        r"\b(?:connect|accept)(?:\s+(?:the\s+)?call)?\b",
        r"\banswer\s+it\b",
        r"\bpick\s+it\s+up\b",
    ]

    # Patterns indicating intent to skip the recap only
    _DISMISS_PATTERNS = [
        r"\b(?:skip|dismiss)(?:\s+(?:the\s+)?recap)?\b",
        r"\b(?:i\s+know|i\s+remember|got\s+it)\b",
        r"\b(?:stop|quiet|shut\s+up)(?:\s+talking)?\b",
        r"\bnevermind\b",
    ]

    def __init__(self) -> None:
        self._compiled_answer = [re.compile(p, re.IGNORECASE) for p in self._ANSWER_PATTERNS]
        self._compiled_dismiss = [re.compile(p, re.IGNORECASE) for p in self._DISMISS_PATTERNS]

    def detect(self, text: str) -> VoiceCommandResult:
        """
        Classifies user speech into a VoiceCommandIntent.

        Args:
            text: Transcribed text from user private microphone.

        Returns:
            VoiceCommandResult with intent and matched phrase.
        """
        if not text or not text.strip():
            return VoiceCommandResult(intent=VoiceCommandIntent.IGNORE, raw_text=text, confidence=0.0)

        cleaned = text.strip()

        # Check ANSWER_CALL patterns first (e.g. "I know, just pick up" matches ANSWER)
        for pattern in self._compiled_answer:
            match = pattern.search(cleaned)
            if match:
                return VoiceCommandResult(
                    intent=VoiceCommandIntent.ANSWER_CALL,
                    raw_text=cleaned,
                    matched_phrase=match.group(0),
                    confidence=0.98,
                )

        # Check DISMISS_RECAP patterns
        for pattern in self._compiled_dismiss:
            match = pattern.search(cleaned)
            if match:
                return VoiceCommandResult(
                    intent=VoiceCommandIntent.DISMISS_RECAP,
                    raw_text=cleaned,
                    matched_phrase=match.group(0),
                    confidence=0.95,
                )

        return VoiceCommandResult(
            intent=VoiceCommandIntent.IGNORE,
            raw_text=cleaned,
            confidence=0.1,
        )

    def process_transcript_event(
        self,
        event: TranscriptEvent,
        call_state: CallState,
    ) -> Optional[VoiceCommandResult]:
        """
        Evaluates a TranscriptEvent in context of the current call state.
        Only USER speech during RINGING state triggers voice commands.

        Args:
            event: The transcript event chunk.
            call_state: Current state of the call FSM.

        Returns:
            VoiceCommandResult if an actionable command was detected, else None.
        """
        if call_state != CallState.RINGING:
            return None

        if event.speaker != Speaker.USER:
            return None

        result = self.detect(event.text)
        if result.intent != VoiceCommandIntent.IGNORE:
            return result

        return None
