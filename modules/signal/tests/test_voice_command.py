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
            "pick up",
            "just pick up",
            "i know, just pick up the call",
            "i know just pick up",
            "answer",
            "answer it",
            "answer the call",
            "take the call",
            "connect",
            "accept the call",
            "yeah, pick up",
            "okay just answer",
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
            "skip",
            "skip recap",
            "dismiss",
            "i know",
            "i remember",
            "stop talking",
            "got it",
            "nevermind",
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
