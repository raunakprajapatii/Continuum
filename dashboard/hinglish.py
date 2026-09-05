"""
dashboard/hinglish.py
---------------------
Devanagari -> Latin-script Hinglish romanizer for the live STT path.

Why this exists
---------------
Deepgram's Nova-3 Hindi model (``language=hi``) is the accurate choice for
Hindi-English code-switching — ``language=multi`` is documented by Deepgram
staff as frequently misdetecting Hindi as Spanish — but the ``hi`` model
returns Hindi in Devanagari script. Latin-script Hindi (``hi-Latn``) is only
available on legacy Deepgram models.

So the bridge transcribes with Nova-3 ``hi`` and romanizes every Devanagari
token into natural Latin-script Hinglish before the browser sees it. English
tokens Deepgram already emits in Latin pass through untouched, which gives
exactly the "hello bhai kaise ho" style transcript the demo needs: Hindi words
in English characters, English words as themselves.

Design
------
A two-layer converter:

1. A dictionary of the most frequent spoken-Hindi function words and demo
   vocabulary (pronouns, particles, common verbs, domain loanwords) so those
   come out with the spelling people actually type (``bhai``, ``kaise``,
   ``mujhe``, ``discount``), not a mechanical syllable expansion.
2. A deterministic fallback that maps every Devanagari syllable to Latin
   (consonants + vowel signs) and then applies Hindi schwa deletion so
   word-final and mid-word ``a`` vowels are dropped the way they are spoken
   (``karna`` not ``karana``).

Words that contain no Devanagari are returned unchanged, so mixed-script
transcripts ("hello भाई कैसे हो") stay mixed but fully Latin.
"""

from __future__ import annotations

import unicodedata

__all__ = ["romanize_hinglish", "has_devanagari"]

# ---------------------------------------------------------------------------
# Exact-word dictionary — spoken Hindi + demo vocabulary, spelled the way
# people write Hinglish. Keys are Devanagari, values Latin.
# ---------------------------------------------------------------------------

_WORDS = {
    # Pronouns & question words
    "मैं": "main", "मुझे": "mujhe", "मेरा": "mera", "मेरी": "meri", "मेरे": "mere",
    "हम": "hum", "हमारा": "hamara", "हमें": "humein",
    "तुम": "tum", "तुम्हें": "tumhe", "तुम्हारा": "tumhara", "तू": "tu",
    "आप": "aap", "आपको": "aapko", "आपका": "aapka", "आपकी": "aapki",
    "उसे": "use", "उसने": "usne", "उन्होंने": "unhone", "इसे": "ise",
    "क्या": "kya", "कौन": "kaun", "कौनसा": "kaunsa", "कब": "kab",
    "कहाँ": "kahan", "कहां": "kahan", "क्यों": "kyon", "कैसे": "kaise",
    "कैसा": "kaisa", "कैसी": "kaisi", "कितना": "kitna", "कितने": "kitne",
    "कितनी": "kitni", "कौन-सा": "kaunsa",
    "यह": "yeh", "ये": "ye", "वह": "woh", "वो": "wo", "वे": "ve",
    "जो": "jo", "जब": "jab", "तब": "tab", "कोई": "koi", "कुछ": "kuch",
    "सब": "sab", "सारा": "sara",
    # Particles, postpositions, conjunctions
    "और": "aur", "या": "ya", "पर": "par", "पे": "pe", "से": "se",
    "में": "mein", "को": "ko", "का": "ka", "की": "ki", "के": "ke",
    "ने": "ne", "भी": "bhi", "ही": "hi", "तो": "to", "हाँ": "haan",
    "ना": "na", "नहीं": "nahi", "नही": "nahi", "बिल्कुल": "bilkul",
    "ज़रूर": "zaroor", "शायद": "shayad", "वैसे": "vaise", "अब": "ab",
    "अभी": "abhi", "फिर": "phir", "बाद": "baad", "पहले": "pehle",
    "पहला": "pehla", "पहली": "pehli", "बस": "bas", "यहाँ": "yahan",
    "वहाँ": "wahan", "वापस": "wapas", "सिर्फ": "sirf", "यानी": "yani",
    # Be / common verbs
    "है": "hai", "हैं": "hain", "हूँ": "hoon", "था": "tha", "थी": "thi",
    "थे": "the", "थीं": "thin", "हो": "ho", "होगा": "hoga", "होगी": "hogi",
    "होगे": "hoge", "हुआ": "hua", "हुई": "hui", "हुए": "hue", "होना": "hona",
    "कर": "kar", "करो": "karo", "करता": "karta", "करती": "karti",
    "करते": "karte", "करना": "karna", "करूँगा": "karunga", "करूंगा": "karunga",
    "करेंगे": "karenge", "किया": "kiya", "किए": "kiye", "कीजिए": "kijiye",
    "काम": "kaam", "बात": "baat", "बातें": "baatein",
    "कल": "kal", "आज": "aaj",
    "सुन": "sun", "सुनो": "suno", "सुनिए": "suniye", "सुनना": "sunna",
    "बोल": "bol", "बोलो": "bolo", "बोला": "bola", "बोली": "boli",
    "बोलना": "bolna", "कहा": "kaha", "कहना": "kahna", "कहो": "kaho",
    "कहिए": "kahiye", "पूछा": "poocha", "पूछना": "poochna",
    "दो": "do", "देना": "dena", "दिया": "diya", "दी": "di", "दिए": "diye",
    "लो": "lo", "ले": "le", "लिया": "liya", "लेना": "lena", "लिए": "liye",
    "देख": "dekh", "देखो": "dekho", "देखा": "dekha", "देखना": "dekhna",
    "चल": "chal", "चलो": "chalo", "चलता": "chalta", "चलती": "chalti",
    "जाओ": "jao", "जाइए": "jaiye", "जाना": "jana", "जाता": "jata",
    "जाती": "jati", "गया": "gaya", "गई": "gayi", "गए": "gaye",
    "आओ": "aao", "आया": "aaya", "आई": "aai", "आना": "aana", "आते": "aate",
    "रह": "reh", "रहा": "raha", "रहे": "rahe", "रही": "rahi",
    "रुक": "ruk", "रुको": "ruko", "रुकिए": "rukiye",
    "समझ": "samajh", "समझा": "samjha", "समझो": "samjho", "समझिए": "samjhiye",
    "सकता": "sakta", "सकते": "sakte", "सकती": "sakti", "सकूँगा": "sakunga",
    "पता": "pata", "मालूम": "maloom", "याद": "yaad", "चाहिए": "chahiye",
    "लगता": "lagta", "लगेगा": "lagega", "मिला": "mila", "मिले": "mile",
    "मिलेगा": "milega", "सोच": "soch", "सोचो": "socho", "सोचना": "sochna",
    # Everyday nouns & adjectives
    "ठीक": "theek", "अच्छा": "achha", "अच्छी": "achhi", "बुरा": "bura",
    "बहुत": "bahut", "थोड़ा": "thoda", "थोड़ी": "thodi", "थोड़े": "thode",
    "जल्दी": "jaldi", "धीरे": "dhire", "भाई": "bhai", "बहन": "behen",
    "दोस्त": "dost", "लोग": "log", "पैसा": "paisa", "पैसे": "paise",
    "रुपये": "rupaye", "साल": "saal", "महीना": "mahina", "हफ्ता": "hafta",
    "दिन": "din", "रात": "raat", "सुबह": "subah", "शाम": "shaam",
    "आधा": "aadha", "नाम": "naam", "घर": "ghar", "काम": "kaam",
    "सवाल": "sawaal", "जवाब": "jawab", "सच": "sach", "गलत": "galat",
    "नमस्ते": "namaste", "नमस्कार": "namaskar", "धन्यवाद": "dhanyavaad",
    "शुक्रिया": "shukriya", "माफ़": "maaf", "माफ": "maaf",
    # Hinglish demo vocabulary — words usually spoken in English; if Deepgram
    # romanizes them into Devanagari these restore the English spelling.
    "हेलो": "hello", "हैलो": "hello",    "ओके": "okay", "हाय": "hi",
    "कॉल": "call", "फोन": "phone", "फ़ोन": "phone", "कल": "kal",
    "बढ़िया": "badhiya", "यूनिट": "unit", "डॉलर": "dollar",
    "चार": "char", "सौ": "sau", "हज़ार": "hazaar",
    "नंबर": "number", "प्राइस": "price", "प्राइसिंग": "pricing",
    "डिस्काउंट": "discount", "फाइनेंस": "finance", "मीटिंग": "meeting",
    "क्वार्टर": "quarter", "क्यूथ्री": "Q3", "रिपोर्ट": "report",
    "ईमेल": "email", "मैसेज": "message", "डेडलाइन": "deadline",
    "प्लान": "plan", "टिकट": "ticket", "वॉल्यूम": "volume",
    "ऑर्डर": "order", "पेमेंट": "payment", "इनवॉइस": "invoice",
    "बजट": "budget", "कंपनी": "company", "प्रोजेक्ट": "project",
    "टीम": "team", "क्लाइंट": "client", "मार्केट": "market",
    "सेल्स": "sales", "मार्जिन": "margin", "प्रॉफिट": "profit",
    "कन्फर्म": "confirm", "कंफर्म": "confirm", "अपडेट": "update",
    "रिव्यू": "review", "फाइल": "file", "डॉक्यूमेंट": "document",
    "ऑफिस": "office", "लैपटॉप": "laptop", "बुक": "book",
    "चेक": "check", "कैलेंडर": "calendar", "टाइम": "time",
}

# ---------------------------------------------------------------------------
# Syllable mapping for the fallback transliterator.
# ---------------------------------------------------------------------------

#: Consonants -> bare Latin letter (no inherent vowel). Nukta forms are two
#: codepoints (base + U+093C) and are matched in _CONSONANT_NUKTA first.
_CONSONANT = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
}

_CONSONANT_NUKTA = {
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "फ़": "f",
    "ड़": "r", "ढ़": "rh", "य़": "y",
}

#: Independent vowels.
_VOWEL = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "अं": "an", "अः": "ah",
}

#: Dependent vowel signs (matras). Includes the candra vowels ॉ/ॅ used in
#: English loanwords (डॉलर -> dollar, कॉलेज -> college).
_MATRA = {
    "ा": "aa", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}

_ANUSVARA = "ं"
_CHANDRABINDU = "ँ"
_VISARGA = "ः"
_HALANT = "्"
_NUKTA = "़"

#: Devanagari digits -> ASCII digits.
_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

_DEV_BLOCK = range(0x0900, 0x0980)


def has_devanagari(text: str) -> bool:
    """True when ``text`` contains at least one Devanagari letter or mark."""
    return any(unicodedata.category(ch) in ("Lo", "Mn", "Mc") and ord(ch) in _DEV_BLOCK for ch in text)


def _is_dev_word_char(ch: str) -> bool:
    """Devanagari letters/marks/digits that belong inside a romanized word."""
    if ch in _DIGITS:
        return True
    cat = unicodedata.category(ch)
    return cat in ("Lo", "Mn", "Mc") and ord(ch) in _DEV_BLOCK


def romanize_hinglish(text: str) -> str:
    """
    Romanize Devanagari Hindi into Latin-script Hinglish.

    Tokens without Devanagari (pure English, digits, punctuation) pass through
    unchanged, so mixed-script input like "hello भाई कैसे हो" becomes
    "hello bhai kaise ho". ``None``/empty input returns ``""``.
    """
    if not text:
        return ""
    out: list[str] = []
    buf: list[str] = []
    for ch in text:
        if _is_dev_word_char(ch):
            buf.append(ch)
        else:
            if buf:
                out.append(_romanize_word("".join(buf)))
                buf = []
            out.append(ch)
    if buf:
        out.append(_romanize_word("".join(buf)))
    return "".join(out)


def _romanize_word(word: str) -> str:
    """Romanize a single Devanagari word (possibly with embedded digits)."""
    exact = _WORDS.get(word)
    if exact is not None:
        return exact
    return _transliterate(word)


def _transliterate(word: str) -> str:
    """
    Deterministic Devanagari -> Latin fallback with Hindi schwa deletion.

    Returns a list of syllables: ``(letters, kind)`` where kind is one of
    ``"vowel"`` (explicit vowel), ``"halant"`` (no vowel), or ``"schwa"``
    (inherent ``a`` that may be dropped).
    """
    syllables: list[tuple[str, str]] = []
    i = 0
    n = len(word)
    while i < n:
        ch = word[i]
        # Consonant, optionally followed by a nukta (ड़ / फ़ / ज़ …). Nukta is
        # always a separate combining mark (base + U+093C), so peek for it.
        if ch in _CONSONANT_NUKTA or ch in _CONSONANT:
            if i + 1 < n and word[i + 1] == _NUKTA and ch + _NUKTA in _CONSONANT_NUKTA:
                letters = _CONSONANT_NUKTA[ch + _NUKTA]
                i += 2  # base + nukta
            else:
                letters = _CONSONANT[ch]
                i += 1
            # What follows the consonant?
            if i < n and word[i] == _HALANT:
                syllables.append((letters, "halant"))
                i += 1
            elif i < n and word[i] in _MATRA:
                syllables.append((letters + _MATRA[word[i]], "vowel"))
                i += 1
                # trailing anusvara after the matra (e.g. हैं -> hain)
                if i < n and word[i] in (_ANUSVARA, _CHANDRABINDU):
                    syllables[-1] = (syllables[-1][0] + _nasal(word, i), "vowel")
                    i += 1
            elif i < n and word[i] in (_ANUSVARA, _CHANDRABINDU):
                syllables.append((letters + _nasal(word, i), "vowel"))
                i += 1
            elif i < n and word[i] == _VISARGA:
                syllables.append((letters + "h", "vowel"))
                i += 1
            else:
                syllables.append((letters, "schwa"))
        # Independent vowel (optionally अं / अः)
        elif ch in _VOWEL:
            syllables.append((_VOWEL[ch], "vowel"))
            i += 1
        elif ch == _ANUSVARA or ch == _CHANDRABINDU:
            # Standalone nasal — carry the previous syllable's vowel
            if syllables:
                letters, kind = syllables[-1]
                syllables[-1] = (letters + _nasal(word, i), kind if kind == "vowel" else "schwa")
            i += 1
        elif ch in _DIGITS:
            syllables.append((_DIGITS[ch], "halant"))
            i += 1
        elif ch == _NUKTA:
            # Orphan nukta (no base letter seen) — drop it silently.
            i += 1
        else:
            # Shouldn't happen (non-word chars are split out upstream).
            syllables.append((ch, "halant"))
            i += 1

    # -- Schwa deletion (approximation of spoken Hindi) ---------------------
    # 1. Word-final inherent 'a' is silent.
    if syllables and syllables[-1][1] == "schwa":
        syllables[-1] = (syllables[-1][0], "halant")
    # 2. An inherent 'a' is silent when the next syllable carries an explicit
    #    vowel or closes a cluster with a halant — but never delete it from
    #    the word's first syllable (keeps onsets pronounceable).
    for idx in range(len(syllables) - 1):
        if idx == 0:
            continue
        letters, kind = syllables[idx]
        if kind != "schwa":
            continue
        nxt = syllables[idx + 1][1]
        if nxt in ("vowel", "halant"):
            syllables[idx] = (letters, "halant")

    # -- Word-final आ/aa shortens to 'a' in everyday Hinglish spelling -------
    if syllables:
        letters, kind = syllables[-1]
        if kind == "vowel" and letters.endswith("aa"):
            syllables[-1] = (letters[:-1], kind)

    return "".join(letters for letters, _ in syllables)


def _nasal(word: str, pos: int) -> str:
    """Romanize an anusvara/chandrabindu: m before labials, n otherwise."""
    nxt = word[pos + 1] if pos + 1 < len(word) else ""
    if nxt in ("प", "फ", "ब", "भ", "म", "प्", "फ्", "ब्", "भ्", "म्"):
        return "m"
    return "n"
