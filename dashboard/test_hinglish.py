"""
dashboard/test_hinglish.py
----------------------------
Tests for the Devanagari -> Latin-script Hinglish romanizer used by the
STT bridge (Deepgram Nova-3 ``hi`` returns Devanagari; the demo wants
"hello bhai kaise ho" style transcripts).
"""

from __future__ import annotations

import pytest

from dashboard.hinglish import has_devanagari, romanize_hinglish


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # The user-facing acceptance case: Hindi in English characters.
        ("\u0939\u0947\u0932\u094b \u092d\u093e\u0908 \u0915\u0948\u0938\u0947 \u0939\u094b", "hello bhai kaise ho"),
        # Mixed script already emitted by Deepgram: English stays Latin.
        ("hello \u092d\u093e\u0908 \u0915\u0948\u0938\u0947 \u0939\u094b", "hello bhai kaise ho"),
        # Function words and demo vocabulary come out naturally.
        ("\u092e\u0948\u0902 \u0915\u0932 \u0924\u0941\u092e\u094d\u0939\u0947\u0902 \u0915\u0949\u0932 \u0915\u0930\u0942\u0901\u0917\u093e", "main kal tumhe call karunga"),
        ("\u0920\u0940\u0915 \u0939\u0948, \u092e\u0941\u091d\u0947 \u092a\u0924\u093e \u0939\u0948", "theek hai, mujhe pata hai"),
        ("\u0928\u0939\u0940\u0902, \u0905\u092d\u0940 \u0928\u0939\u0940\u0902", "nahi, abhi nahi"),
        ("\u0915\u093f\u0924\u0928\u093e \u0921\u093f\u0938\u094d\u0915\u093e\u0909\u0902\u091f \u092e\u093f\u0932\u0947\u0917\u093e", "kitna discount milega"),
        ("Q3 \u0928\u0902\u092c\u0930 \u091a\u093e\u0939\u093f\u090f", "Q3 number chahiye"),
        ("\u092e\u0940\u091f\u093f\u0902\u0917 \u092e\u0947\u0902 \u092c\u093e\u0924 \u0915\u0930\u0947\u0902\u0917\u0947", "meeting mein baat karenge"),
        ("\u092c\u0938 \u0915\u0930\u094b, \u092e\u0941\u091d\u0947 \u092f\u093e\u0926 \u0939\u0948", "bas karo, mujhe yaad hai"),
        ("\u091f\u093f\u0915\u091f \u0928\u0902\u092c\u0930 XYZ \u0939\u0948", "ticket number XYZ hai"),
        # Schwa deletion (spoken Hindi, not syllable-by-syllable).
        ("\u0915\u093e\u092e", "kaam"),
        ("\u0928\u093e\u092e", "naam"),
        ("\u092c\u094b\u0932\u0928\u093e", "bolna"),
        ("\u0938\u0915\u0924\u093e", "sakta"),
        # Nukta consonants and candra vowels (loanwords).
        ("\u092b\u093c\u094b\u0928 \u0909\u0920\u093e \u0932\u094b", "phone utha lo"),
        ("\u0921\u0949\u0932\u0930", "dollar"),
        # Barge-in / command phrases round-trip into Latin phrases the
        # VoiceCommandDetector recognises.
        ("\u092e\u0941\u091d\u0947 \u092a\u0924\u093e \u0939\u0948, \u0915\u0949\u0932 \u0909\u0920\u093e \u0932\u094b", "mujhe pata hai, call utha lo"),
        ("\u0915\u0949\u0932 \u0909\u0920\u093e \u0932\u094b", "call utha lo"),
    ],
)
def test_romanize_hinglish(source: str, expected: str) -> None:
    assert romanize_hinglish(source) == expected


def test_romanize_hinglish_pure_english_passthrough() -> None:
    text = "The unit price was 400 dollars, and I'll check with finance."
    assert romanize_hinglish(text) == text


def test_romanize_hinglish_punctuation_and_empty() -> None:
    assert romanize_hinglish("") == ""
    assert romanize_hinglish("\u0920\u0940\u0915 \u0939\u0948!") == "theek hai!"
    assert (
        romanize_hinglish("\u092e\u0948\u0902, \u0924\u0941\u092e \u0914\u0930 \u0935\u094b")
        == "main, tum aur wo"
    )


def test_has_devanagari() -> None:
    assert has_devanagari("\u092d\u093e\u0908")
    assert has_devanagari("hello \u092d\u093e\u0908")
    assert not has_devanagari("hello bhai")
    assert not has_devanagari("")


def test_romanize_output_never_contains_devanagari() -> None:
    source = (
        "\u0939\u0947\u0932\u094b \u092d\u093e\u0908, \u0915\u0948\u0938\u0947 \u0939\u094b? "
        "\u092e\u0948\u0902 \u0915\u0932 \u092b\u093e\u0907\u0928\u0947\u0902\u0938 \u0938\u0947 "
        "\u0921\u093f\u0938\u094d\u0915\u093e\u0909\u0902\u091f \u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 "
        "\u092c\u093e\u0924 \u0915\u0930\u0942\u0901\u0917\u093e \u0914\u0930 Q3 \u0928\u0902\u092c\u0930 \u0915\u093e "
        "\u091f\u093f\u0915\u091f XYZ \u092d\u0947\u091c\u0942\u0901\u0917\u093e\u0964"
    )
    assert not has_devanagari(romanize_hinglish(source))
