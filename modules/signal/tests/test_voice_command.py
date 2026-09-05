"""
modules/signal/tests/test_voice_command.py
--------------------------------------------
Unit tests for VoiceCommandDetector in modules/signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from modules.signal.voice_command import (
    VoiceCommandDetector,
    VoiceCommandIntent,
    VoiceCommandResult,
)
from shared.schemas import CallState, Speaker, TranscriptEvent


@pytest.fixture
def detector() -> VoiceCommandDetector:
    return VoiceCommandDetector()


def make_event(text: str, speaker: Speaker = Speaker.USER) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=str(uuid.uuid4()),
        session_id="sess-voice-cmd",
        speaker=speaker,
        text=text,
        start_ms=0,
        end_ms=1000,
        is_final=True,
        confidence=0.99,
        timestamp=datetime.now(tz=timezone.utc),
    )


class TestVoiceCommandDetector:
    """Test intent classification for user verbal commands during incoming call ring."""

    @pytest.mark.parametrize(
        "phrase",
        [
            # English — any preamble / word order with a pickup verb.
            "pick up",
            "just pick up",
            "i know, just pick up the call",
            "i know just pick up",
            "answer",
            "answer it",
            "answer the call",
            "answer the phone",
            "pick up the phone",
            "pick the phone up",
            "go ahead and answer it",
            "alright, pick up",
            "take the call",
            "connect",
            "accept the call",
            "yeah, pick up",
            "okay just answer",
            # Hinglish / Hindi (Latin script) — "call utha lo" and friends.
            "call utha lo",
            "call uthao",
            "phone utha lo",
            "utha lo",
            "utha le",
            "haan, utha lo",
            "mujhe pta hai call utha lo",
            "mujhe pata hai, call utha lo",
            "theek hai, call utha le lo",
            "call le lo",
            "phone le lena",
            "answer kar do",
            "call answer karo",
            "jaldi se receive kar lo",
            "call ka jawab de do",
            # Hindi (Devanagari).
            "कॉल उठा लो",
            "उठाओ",
            "मुझे पता है, कॉल उठा लो",
            "कॉल ले लो",
            "फ़ोन का जवाब दे दो",
            "कॉल रिसीव करो",
        ],
    )
    def test_detect_answer_call_phrases(self, detector: VoiceCommandDetector, phrase: str):
        res = detector.detect(phrase)
        assert res.intent == VoiceCommandIntent.ANSWER_CALL
        assert res.matched_phrase is not None
        assert res.confidence >= 0.9

    @pytest.mark.parametrize(
        "phrase",
        [
            # English
            "skip",
            "skip recap",
            "dismiss",
            "i know",
            "i remember",
            "stop talking",
            "got it",
            "nevermind",
            # Hinglish / Hindi (Latin script)
            "skip karo",
            "skip kar do",
            "mujhe pata hai",
            "mujhe pta hai",
            "mujhe maloom hai",
            "mujhe yaad hai",
            "samajh gaya",
            "samajh gayi",
            "samajh aa gaya",
            "bas karo",
            "bas kar do",
            "ruk ja",
            "ruk jao, ek second",
            "chup karo",
            "band kar do",
            # Hindi (Devanagari)
            "स्किप करो",
            "बस करो",
            "मुझे पता है",
            "मुझे याद है",
            "समझ गया",
            "रुक जाओ",
            "चुप करो",
            "बंद कर दो",
        ],
    )
    def test_detect_dismiss_recap_phrases(self, detector: VoiceCommandDetector, phrase: str):
        res = detector.detect(phrase)
        assert res.intent == VoiceCommandIntent.DISMISS_RECAP
        assert res.matched_phrase is not None
        assert res.confidence >= 0.9

    @pytest.mark.parametrize(
        "phrase",
        [
            "hello",
            "who is this?",
            "finance team",
            "the price was 400 dollars",
            "what did he say yesterday",
            "",
            "   ",
            # Ambient / non-command Hinglish & Hindi must NOT auto-answer.
            "kya hua",
            "price kitna hai",
            "call kar lo",  # "make the call" — not "pick up"
            "tum call kar lo, main baad mein aaunga",
            "main kal answer karunga",  # "I'll reply tomorrow" — not an answer now
            "kya answer hai",  # "what is the answer" — noun, not a command
            "mujhe answer nahi pata",  # "I don't know the answer"
            "sawaal ka jawab do",  # "answer the question" — no phone context
            "बस में भीड़ है",  # "the bus is crowded"
            "सवाल का जवाब दो",  # "answer the question" (Devanagari)
            "किताब पढ़ लो",  # "read the book"
        ],
    )
    def test_detect_ignore_ambient_speech(self, detector: VoiceCommandDetector, phrase: str):
        res = detector.detect(phrase)
        assert res.intent == VoiceCommandIntent.IGNORE

    def test_process_transcript_event_in_ringing_state(self, detector: VoiceCommandDetector):
        event = make_event("i know, just pick up the call", speaker=Speaker.USER)
        res = detector.process_transcript_event(event, CallState.RINGING)
        assert res is not None
        assert res.intent == VoiceCommandIntent.ANSWER_CALL

    def test_process_transcript_event_ignores_non_ringing(self, detector: VoiceCommandDetector):
        event = make_event("i know, just pick up the call", speaker=Speaker.USER)
        # In CONNECTED state, regular conversation should not trigger call pickup/dismiss logic
        res = detector.process_transcript_event(event, CallState.CONNECTED)
        assert res is None

    def test_process_transcript_event_ignores_caller_speech(self, detector: VoiceCommandDetector):
        # If caller says "pick up", it should NOT answer the user's phone
        event = make_event("pick up the phone", speaker=Speaker.CALLER)
        res = detector.process_transcript_event(event, CallState.RINGING)
        assert res is None

    @pytest.mark.parametrize(
        "phrase",
        [
            # "I know"-style preambles are only a dismissal on their own; the
            # moment a pickup verb follows they must classify as ANSWER_CALL
            # (answer intent is checked before dismiss).
            "mujhe pata hai call utha lo",
            "mujhe pta hai, phone le lo",
            "theek hai, answer kar do",
            "मुझे पता है, कॉल उठा लो",
            "i know, just pick up the call",
        ],
    )
    def test_answer_preamble_beats_dismiss(self, detector: VoiceCommandDetector, phrase: str):
        res = detector.detect(phrase)
        assert res.intent == VoiceCommandIntent.ANSWER_CALL

    @pytest.mark.parametrize(
        "phrase",
        [
            "skip karo, mujhe pata hai",
            "bas karo, main baad mein le lunga",
            "ruk ja, mujhe yaad aa gaya",
        ],
    )
    def test_dismiss_without_pickup_verb(self, detector: VoiceCommandDetector, phrase: str):
        res = detector.detect(phrase)
        assert res.intent == VoiceCommandIntent.DISMISS_RECAP
