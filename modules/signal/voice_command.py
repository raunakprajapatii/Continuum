"""
modules/signal/voice_command.py
---------------------------------
Ring-Window Voice Command & Barge-In Detector.

Listens for user speech during the RINGING window when an AI recap is playing in
the user's private whisper channel. Detects verbal commands in English,
Hinglish, or Hindi (Latin script or Devanagari), such as:
  - "I know, just pick up the call" / "Answer"  -> ANSWER_CALL (stops recap & connects call)
  - "call utha lo" / "mujhe pta hai call utha lo" -> ANSWER_CALL
  - "Skip" / "I remember" / "mujhe pata hai"     -> DISMISS_RECAP (stops recap, leaves ringing)
  - "Hold on" / "Wait a sec" / "ruk ja"           -> DISMISS_RECAP (stop-only, no auto-answer)

The matcher is deliberately NOT anchored to a single canonical sentence: it
searches the whole utterance for a decisive verb phrase (e.g. "pick up",
"utha lo", "उठा लो"), so any preamble, filler, or word order with the same
meaning is recognised — "just pick up the call", "call utha lo", "haan,
utha lo", "मुझे पता है, कॉल उठा लो". Answer intent is checked before dismiss so
a preamble like "mujhe pata hai" (I know) only dismisses when no pickup verb
follows.
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

    # Patterns indicating intent to answer/pick up the call. Each pattern is a
    # decisive verb phrase searched anywhere in the utterance, so preambles and
    # word order are free: "call utha lo", "mujhe pta hai call utha lo",
    # "pick up the phone", "go ahead and answer" all hit the same core verb.
    _ANSWER_PATTERNS = [
        # ── English ────────────────────────────────────────────────────────
        r"\bpick\s+(?:it\s+)?up\b",  # pick up / pick it up / just pick up
        r"\bpick\s+up\s+(?:the\s+|my\s+)?(?:call|phone)\b",  # pick up the call
        r"\bpick\s+(?:the\s+|my\s+)?(?:call|phone)\s+up\b",  # pick the phone up
        r"\banswer\s+(?:the\s+|my\s+)?(?:call|phone)\b",  # answer the call/phone
        r"\banswer\s+it\b",
        # Bare "answer" as an imperative. Guards keep nouns out ("the answer",
        # "kya answer") and Hindi tenses out ("answer karunga" = I'll reply).
        r"(?<!the\s)(?<!an\s)(?<!a\s)(?<!kya\s)(?<!what\s)\banswer\b"
        r"(?!\s+kar\w*\b)(?!\s+(?:nahi|nhi|nai)\b)",
        r"\b(?:take|accept|connect)(?:\s+(?:the\s+)?(?:call|phone))?\b",
        # ── Hinglish / Hindi (Latin script) ────────────────────────────────
        r"\butha\s+(?:lo|le|lena)\b",  # call utha lo / utha le / utha lena
        r"\buthao\b",  # uthao / call uthao
        r"\b(?:call|phone|col)\s+le\s+(?:lo|lena)\b",  # call le lo (take the call)
        r"\b(?:call\s+|phone\s+)?answer\s+kar\s*(?:o|do|de|lo)\b",  # (call) answer karo / kar do / kar lo
        r"\b(?:call\s+|phone\s+)?receive\s+kar\s*(?:o|do|lo)\b",  # (call) receive karo / kar lo
        r"\b(?:call|phone|col)\s+ka\s+jawab\s+(?:de\s+)?do\b",  # call ka jawab de do
        # ── Hindi (Devanagari) ─────────────────────────────────────────────
        # NOTE: Devanagari vowel signs (ो े ा …) are combining marks — NOT word
        # characters — so `\b` after a syllable like लो/करो never matches. End
        # patterns with a lookahead that rejects a following Devanagari rune
        # instead of `\b`.
        r"\bउठा\s*(?:लो|ले)(?![\u0900-\u097f])|\bउठाओ(?![\u0900-\u097f])",  # कॉल उठा लो / उठाओ
        r"\b(?:कॉल|फ़ोन|फोन)\s+ले\s*(?:लो|लेना)(?![\u0900-\u097f])",  # कॉल ले लो
        r"\b(?:कॉल|फ़ोन|फोन)\s+का\s+जवाब\s+(?:दे\s*)?दो(?![\u0900-\u097f])",  # कॉल का जवाब दो
        r"\b(?:कॉल|फ़ोन|फोन)\s+रिसीव\s+करो(?![\u0900-\u097f])",  # कॉल रिसीव करो
    ]

    # Patterns indicating intent to skip the recap only (phone keeps ringing).
    _DISMISS_PATTERNS = [
        # ── English ────────────────────────────────────────────────────────
        r"\b(?:skip|dismiss)(?:\s+(?:the\s+)?recap)?\b",
        r"\b(?:i\s+know|i\s+remember|got\s+it)\b",
        r"\b(?:stop|quiet|shut\s+up)(?:\s+talking)?\b",
        r"\bnevermind\b",
        # Generic interrupt: pause/stop the recap but do NOT auto-answer.
        r"\bhold\s+on\b",
        r"\b(?:wait|one\s+sec(?:ond)?|hang\s+on)(?:\b|,)\s*",
        # ── Hinglish / Hindi (Latin script) ────────────────────────────────
        r"\bskip\s+kar\s*(?:o|do|de|lo)\b",  # skip karo / skip kar do
        r"\bmujhe\s+(?:pata|pta|maloom)\s+h(?:ai|e)\b",  # mujhe pata hai (I know)
        r"\bmujhe\s+yaad\s+h(?:ai|e)\b",  # mujhe yaad hai (I remember)
        r"\bsamajh\s+(?:gaya|gayi|aa\s+gaya|aa\s+gayi)\b",  # samajh gaya (got it)
        r"\bbas\s+(?:kar\s*(?:o|do|de|lo)|ho\s+gaya|ho\s+gayi|bahut\s+h(?:ai|e))\b",  # bas karo
        r"\bruk\s+(?:ja|jao)\b",  # ruk ja / ruk jao (hold on)
        r"\b(?:ek|one)\s+second\b",  # ek second (wait a sec)
        r"\bchup\s+(?:karo|kar|ho\s+jao|raho)\b",  # chup karo (shut up)
        r"\bband\s+kar\s*(?:o|do|de|lo)\b",  # band karo / band kar do
        # ── Hindi (Devanagari) ─────────────────────────────────────────────
        # See the ANSWER block note: end with a Devanagari-rejecting lookahead,
        # never `\b` (vowel signs are combining marks, not word characters).
        r"\bस्किप\s+करो(?![\u0900-\u097f])",
        r"\bमुझे\s+पता\s+हैं?(?![\u0900-\u097f])",  # मुझे पता है (I know)
        r"\bमुझे\s+याद\s+हैं?(?![\u0900-\u097f])",  # मुझे याद है (I remember)
        r"\bसमझ\s+(?:गया|गई|आ\s+गया|आ\s+गई)(?![\u0900-\u097f])",  # समझ गया (got it)
        r"\bबस\s+(?:करो|कर\s+दो|हो\s+गया|हो\s+गई)(?![\u0900-\u097f])",  # बस करो
        r"\bरुक\s+(?:जा|जाओ)(?![\u0900-\u097f])",  # रुक जाओ (hold on)
        r"\bचुप\s+(?:करो|हो\s+जाओ|रहो)(?![\u0900-\u097f])",  # चुप करो
        r"\bबंद\s+(?:करो|कर\s+दो)(?![\u0900-\u097f])",  # बंद करो (stop it)
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
