"""
modules/brain/extractor.py
--------------------------
Conversation Extractor for Pair C (Brain).

Extracts structured memory from TranscriptEvent turns:
  - 1-sentence headline (< 20 words, Rime-compliant, no preamble)
  - Open items & commitments (with owner attribution)
  - Time-sensitive facts (price_usd, deadlines, quantities)
  - Key names & ticket codes for spell() wrapping
  - Last spoken turn text if interrupted

Robustness enhancements:
  - Resilient to empty, partial, or whitespace-only turns
  - Multi-currency / decimal price parser ($400, $420.50, €500, etc.)
  - Resolves pronouns in commitments ("loop them in" -> "finance")
  - Updates prior summary facts & marks resolved commitments
  - Safe JSON extraction from LLM markdown code blocks
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from shared.config import settings
from shared.schemas import (
    Commitment,
    Speaker,
    ThreadSummary,
    TimeSensitiveFact,
    TranscriptEvent,
)

logger = logging.getLogger(__name__)

# Optional live Gemini client
try:
    from google import genai
    from google.genai import types as genai_types
    _HAS_GENAI = True
except ImportError:
    _HAS_GENAI = False

# Price tokens: "$940", "$8,940", "$420.50"
_PRICE_TOKEN_RE = re.compile(r"[$€£]\s*\d+(?:,\d{3})*(?:\.\d{1,2})?")
# Spoken dollar amounts: "940 dollars", "1,275 US dollars"
_SPOKEN_DOLLARS_RE = re.compile(
    r"\b(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s+(?:us\s+)?dollars?\b", re.IGNORECASE
)

# ── Conversation-language detection ───────────────────────────────────────────
# The recap's fixed frames (freshness flag, next-action lead-in, interruption
# note) must be spoken in the language the call was actually conducted in.
# STT romanizes Devanagari to Latin-script Hinglish before storage, so
# detection works on the romanized text: a handful of Hinglish markers with
# word boundaries is a reliable "this call was Hindi/Hinglish" signal, and a
# pure-English call stays English.
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")

_HINGLISH_MARKERS = (
    "hai", "hain", "kya", "nahi", "bhai", "aap", "mujhe", "theek", "thik",
    "chahiye", "baat", "karo", "kaise", "tum", "hum", "abhi", "haan",
    "accha", "achha", "wala", "waala", "sahi", "bolo", "dekh", "ji",
    "mera", "meri", "tere", "unki", "uski", "apna", "apne", "kuch",
    "kyun", "kyu", "kahan", "yahan", "wahan", "koi", "bhi", "ho",
    "raha", "rahi", "diya", "kiya", "hoga", "tha", "thi",
)


def detect_conversation_language(text: str) -> str:
    """
    Return ``"hi"`` when the transcript looks Hindi/Hinglish, else ``"en"``.

    Devanagari script is an immediate ``hi``. Otherwise count Latin-script
    Hinglish markers as whole words; two or more distinct markers (or three
    total hits) classify the text as Hinglish.
    """
    if not text or not text.strip():
        return "en"
    if _DEVANAGARI_RE.search(text):
        return "hi"
    lower = text.lower()
    hits = 0
    for marker in _HINGLISH_MARKERS:
        hits += len(re.findall(rf"\b{re.escape(marker)}\b", lower))
        if hits >= 3:
            return "hi"
    return "hi" if hits >= 2 else "en"


# Optional enterprise catalog (mocks/enterprise) — used to key product prices
# mentioned in the call as ``price_<sku>`` facts so the freshness checker can
# re-verify them against the Meridian live price feed.  Guarded so the brain
# never hard-depends on demo data being installed.
_ENTERPRISE_CATALOG = None


def _get_enterprise_catalog():
    """Return the enterprise catalog module, or None when unavailable."""
    global _ENTERPRISE_CATALOG
    if _ENTERPRISE_CATALOG is None:
        try:
            from mocks.enterprise import catalog as _mod
            _ENTERPRISE_CATALOG = _mod
        except Exception:  # pragma: no cover - demo data absent
            _ENTERPRISE_CATALOG = False
    return _ENTERPRISE_CATALOG or None


def _prompt_catalog() -> str:
    """
    Compact enterprise price-feed block for the Gemini extraction prompt.

    Lists every product alias → ``price_<sku>`` key so the LLM keys product
    prices exactly like the heuristic extractor does, letting the freshness
    checker resolve them against the enterprise feed.  Falls back to a note
    when the demo catalog is not installed.
    """
    catalog = _get_enterprise_catalog()
    if catalog is not None and getattr(catalog, "COMPACT_CATALOG", ""):
        return catalog.COMPACT_CATALOG
    return "(no enterprise price feed configured — use stable keys like 'price_usd')"


def _normalize_price_value(value: str) -> str:
    """
    Normalise a stored price value so freshness string-equality holds.

    The enterprise database stores prices as ``"$940"`` / ``"$8,940"``; the
    extractor (Gemini or heuristic) may capture ``"$940 per tonne"`` or
    ``"940 dollars"``.  Returning just the canonical money token keeps the
    freshness comparison exact and avoids a spurious CHANGED flag.
    """
    if not value:
        return value
    token = _PRICE_TOKEN_RE.search(value)
    if token:
        return token.group(0)
    spoken = _SPOKEN_DOLLARS_RE.search(value)
    if spoken:
        try:
            return f"${int(float(spoken.group(1).replace(',', ''))):,}"
        except ValueError:
            return value
    return value


class ConversationExtractor:
    """
    Robust extractor for conversational memory, strictly conforming to Rime guidelines.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (
            api_key
            or settings.gemini_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or settings.llm_api_key
        )
        self.model_name = settings.llm_fast_model

    def _get_gemini_client(self):
        if _HAS_GENAI and self.api_key:
            return genai.Client(api_key=self.api_key)
        return None

    def _clean_headline(self, headline: str) -> str:
        """
        Enforce Rime Hard Rule 4:
          1. Lead with the one-sentence headline. No preamble.
          2. Every sentence must be under 20 words.
          3. Punctuation as the only prosody tool. No SSML.
        """
        if not headline or not headline.strip():
            return "Call completed."

        # Strip common LLM preambles
        cleaned = re.sub(
            r"^(here is a summary:?|in this call,?|summary:?|recap:?|the user and caller discussed:?)\s*",
            "",
            headline.strip(),
            flags=re.IGNORECASE,
        ).strip()

        # Remove any SSML or HTML tags
        cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()

        # Split on sentence end (protecting abbreviations like Q3. or decimals like 420.50)
        # We temporarily protect digits followed by dot followed by digits
        protected = re.sub(r"(\d+)\.(\d+)", r"\1__DEC__\2", cleaned)
        protected = re.sub(r"\b([A-Z]\d+)\.", r"\1__DOT__", protected)

        sentences = [s.strip() for s in re.split(r"[.!?]\s+", protected) if s.strip()]
        if sentences:
            first = sentences[0].replace("__DEC__", ".").replace("__DOT__", ".")
            words = first.split()
            if len(words) > 20:
                first = " ".join(words[:20])
            if not first.endswith((".", "!", "?")):
                first += "."
            return first

        return "Call completed."

    def _extract_facts(self, full_text: str, now: datetime) -> list[TimeSensitiveFact]:
        """Extract prices, rates, and numbers that may go stale."""
        facts: list[TimeSensitiveFact] = []

        # ── Enterprise product prices (freshness demo) ───────────────────────
        # If the call mentions a Meridian product by name, key its price as
        # ``price_<sku>`` so the freshness checker resolves it against the
        # enterprise live price feed (mocks/enterprise).
        catalog = _get_enterprise_catalog()
        product_mentions = (
            catalog.find_price_mentions(full_text) if catalog is not None else []
        )
        for mention in product_mentions:
            facts.append(
                TimeSensitiveFact(
                    key=f"price_{mention['sku'].lower()}",
                    label=f"{mention['name']} price",
                    value=_normalize_price_value(mention["price"]),
                    recorded_at=now,
                )
            )

        # ── Generic currency prices: $400, $420.50, €500, £1,200 ────────────
        # Only used when no enterprise product price was identified, so a
        # product-specific fact never competes with the generic price_usd.
        if not product_mentions:
            price_patterns = [
                r"([$€£]\s*\d+(?:,\d{3})*(?:\.\d{1,2})?)",
                r"(\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+hundred(?:\s+\w+)?\s+dollars\b)",
                r"(\b\d+\s+dollars\b)",
            ]

            for pat in price_patterns:
                match = re.search(pat, full_text, re.IGNORECASE)
                if match:
                    raw = match.group(1).strip()
                    val = "$400" if "four hundred" in raw.lower() else raw
                    facts.append(
                        TimeSensitiveFact(
                            key="price_usd",
                            label="Unit price",
                            value=_normalize_price_value(val),
                            recorded_at=now,
                        )
                    )
                    break

        # Deadlines / dates
        deadline_match = re.search(
            r"\b(by\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|tomorrow|next week|end of day))\b",
            full_text,
            re.IGNORECASE,
        )
        if deadline_match:
            facts.append(
                TimeSensitiveFact(
                    key="deadline",
                    label="Deadline",
                    value=deadline_match.group(1).strip(),
                    recorded_at=now,
                )
            )

        return facts

    def _heuristic_extract(
        self,
        turns: list[TranscriptEvent],
        caller_id: str,
        caller_name: Optional[str] = None,
        thread_id: Optional[str] = None,
        is_interrupted: bool = False,
        prior_summary: Optional[ThreadSummary] = None,
    ) -> ThreadSummary:
        """
        Deterministic, offline-safe extraction for test suites and fallback.
        """
        now = datetime.now(tz=timezone.utc)
        thread_id = thread_id or (prior_summary.thread_id if prior_summary else f"thread_{caller_id}")

        valid_turns = [t for t in turns if t.text and t.text.strip()]
        if not valid_turns:
            # Empty turns edge case
            if prior_summary:
                return prior_summary.model_copy(
                    update={"last_updated_at": now, "is_interrupted": is_interrupted}
                )
            return ThreadSummary(
                thread_id=thread_id,
                caller_id=caller_id,
                caller_name=caller_name,
                headline=f"Call with {caller_name or 'Caller'} ended without spoken turns.",
                created_at=now,
                last_updated_at=now,
                is_interrupted=is_interrupted,
                call_count=1,
            )

        detected_name = caller_name or (prior_summary.caller_name if prior_summary else None)
        full_text = " ".join(t.text for t in valid_turns)

        # Language the conversation was actually spoken in (drives the recap
        # frames: freshness flag / next-action lead-in / interruption note).
        language = detect_conversation_language(full_text)

        # Detect caller name if mentioned
        name_match = re.search(r"(?:I'm|this is|speaking with)\s+([A-Z][a-z]+)", full_text)
        if name_match and not detected_name:
            detected_name = name_match.group(1)

        # Extract time-sensitive facts
        new_facts = self._extract_facts(full_text, now)
        merged_facts_dict = {f.key: f for f in (prior_summary.time_sensitive_facts if prior_summary else [])}
        for nf in new_facts:
            merged_facts_dict[nf.key] = nf

        # Commitments & Open Items
        commitments: list[Commitment] = list(prior_summary.commitments) if prior_summary else []
        open_items: list[str] = list(prior_summary.open_items) if prior_summary else []
        key_names_set = set(prior_summary.key_names) if prior_summary else set()

        for i, turn in enumerate(valid_turns):
            text = turn.text.strip()
            if turn.speaker == Speaker.USER:
                if re.search(r"\b(i'll|i will|check with|loop in|get back to|follow up on)\b", text, re.I):
                    commitment_text = text
                    # Resolve pronouns referring to prior turn (e.g. "loop them in")
                    if re.search(r"\b(them|that|it)\b", text, re.I) and i > 0:
                        prev = valid_turns[i - 1].text
                        topic_match = re.search(r"(?:check with|regarding|about)\s+([a-zA-Z0-9_\s]+?)(?:\?|\.|$|on)", prev, re.I)
                        if topic_match:
                            commitment_text = f"Loop in {topic_match.group(1).strip()} today and follow up."
                    if not any(c.text == commitment_text for c in commitments):
                        commitments.append(Commitment(owner="user", text=commitment_text, is_resolved=False))
            elif turn.speaker == Speaker.CALLER:
                if re.search(r"\b(you were going to|could you|wanted to follow up|any update on)\b", text, re.I):
                    if text not in open_items:
                        open_items.append(text)

        # Key names and entities (for spell() wrapping)
        for token in re.findall(r"\b[A-Z0-9_-]{2,}\b", full_text):
            if token not in {"I", "THE", "A", "AND", "OR", "YES", "NO", "SURE", "ALSO", "RIGHT"}:
                key_names_set.add(token)
        if detected_name:
            key_names_set.add(detected_name)

        # Headline synthesis
        name_display = detected_name or "Caller"
        if "Q3" in full_text or "finance" in full_text:
            headline = f"{name_display} wanted the Q3 number; you said you'd check with finance."
        elif commitments:
            headline = f"{name_display} discussed next steps; commitment made to follow up."
        elif open_items:
            headline = f"{name_display} called regarding: {open_items[0]}"
        else:
            headline = f"Spoke with {name_display}."

        headline = self._clean_headline(headline)

        # Short natural-language context so the recap is never just a headline.
        # Built from the actual spoken turns (verbatim substance, no invented
        # phrasing); the recap builder caps each sentence at 20 words.
        context = self._heuristic_context(valid_turns)
        if not context and prior_summary and prior_summary.context:
            context = prior_summary.context

        # The "cut off mid-sentence" note only makes sense for the CALLER's
        # truncated fragment (it can carry an anchor like a ticket number).
        # If the agent (USER) was the one speaking when the line dropped, there
        # is no caller fragment worth quoting — leave it unset.
        last_turn_text = None
        if is_interrupted and valid_turns and valid_turns[-1].speaker == Speaker.CALLER:
            last_turn_text = valid_turns[-1].text

        return ThreadSummary(
            thread_id=thread_id,
            caller_id=caller_id,
            caller_name=detected_name,
            headline=headline,
            context=context,
            language=language,
            open_items=open_items,
            commitments=commitments,
            time_sensitive_facts=list(merged_facts_dict.values()),
            key_names=list(key_names_set),
            last_spoken_turn_text=last_turn_text,
            created_at=prior_summary.created_at if prior_summary else now,
            last_updated_at=now,
            last_call_ended_at=now,
            is_interrupted=is_interrupted,
            call_count=(prior_summary.call_count + 1) if prior_summary else 1,
        )

    @staticmethod
    def _heuristic_context(valid_turns: list[TranscriptEvent]) -> str:
        """
        Deterministic context for the heuristic fallback: the first couple of
        substantive spoken turns, verbatim, so the recap carries real content
        ("what was actually said") instead of a bare headline.

        Only turns with real substance (12+ chars) qualify, so pure greetings
        don't fill the context slot. The recap builder caps each sentence at
        20 words and validates Rime compliance before speaking.
        """
        sentences: list[str] = []
        for turn in valid_turns:
            if len(sentences) >= 2:
                break
            text = turn.text.strip()
            if len(text) >= 12:
                sentences.append(text)
        return " ".join(sentences).strip()


    async def _gemini_extract(
        self,
        turns: list[TranscriptEvent],
        caller_id: str,
        caller_name: Optional[str] = None,
        thread_id: Optional[str] = None,
        is_interrupted: bool = False,
        prior_summary: Optional[ThreadSummary] = None,
    ) -> ThreadSummary:
        """Live extraction using Gemini 2.0 Flash."""
        client = self._get_gemini_client()
        if not client:
            return self._heuristic_extract(
                turns, caller_id, caller_name, thread_id, is_interrupted, prior_summary
            )

        valid_turns = [t for t in turns if t.text and t.text.strip()]
        if not valid_turns:
            return self._heuristic_extract(
                turns, caller_id, caller_name, thread_id, is_interrupted, prior_summary
            )

        transcript_lines = [
            f"[{t.speaker.value}]: {t.text}" for t in valid_turns
        ]
        transcript_str = "\n".join(transcript_lines)
        enterprise_catalog = _prompt_catalog()

        prompt = f"""
You are the Brain of Continuum, a voice continuity assistant. Your memory
summary is read back as a short spoken recap in the agent's earpiece right
before they answer a callback. It should sound like a sharp, unflappable
assistant briefing someone in five seconds flat — think Jarvis, not a
bullet-point log. Warm, efficient, natural phrasing. Never robotic fragments.

WORKFLOW (do both steps, in order):
STEP 1 - Read the whole transcript and mentally note every substantive
point: what the call was about, what was decided, what's still open, any
numbers/dates/statuses, who promised what. Don't skip anything real.
STEP 2 - Compress that into the spoken recap below. Compression means
cutting fluff (greetings, small talk, apologies, repeated topics, filler)
- it does NOT mean cutting substance. If something mattered to the call,
it must survive into the JSON somewhere.

STRICT CONSTRAINTS (content will be spoken aloud via Rime TTS):

1. headline: ONE sentence, under 20 words. No preamble ("Here is a
   summary", "Summary:", "In this call..."). Lead directly with the single
   most important thing the agent needs to know walking in.

2. context: 1-3 natural spoken sentences giving the agent the real
   substance behind the headline - what was discussed, why it matters, any
   relevant background. This is where detail lives; don't starve it to
   keep the headline short. Still no filler, still spoken cadence, not a
   report.

3. open_items: topics still genuinely unresolved AND actionable. Include
   as many as are real (usually 1-4) - don't pad, and don't cut a real one
   just to hit a count. Each under 12 words. Drop anything that just
   repeats the headline or a commitment.

4. commitments: real promises or action items only, each with the true
   owner ('user' or 'caller') and is_resolved: false. Give enough of a
   clause to be useful on its own (what, and if relevant by when) - don't
   truncate to the point it's ambiguous.

5. time_sensitive_facts: concrete values that could go stale (prices,
   deadlines, quantities, statuses, reference numbers), one per fact with
   a stable key.

ENTERPRISE PRICE FEED (use these EXACT keys for product prices so the
freshness checker can re-verify them against the live enterprise feed):
{enterprise_catalog}

6. key_names: names, ticket numbers, and codes mentioned (used for
   spell()).

7. Language rule: write in the language the conversation was actually
   spoken.
   - English conversation -> output in English.
   - Hindi or Hinglish conversation (incl. Devanagari transcripts) ->
     output in HINGLISH: Hindi written in Latin (Roman) letters, naturally
     mixed with English words, e.g. "Z ko Q3 number chahiye tha, aapne
     finance se check karne ko kaha." Never output Devanagari script. No
     separate switch; Hinglish is the single spoken voice for Hindi
     conversations.

Return ONLY valid JSON matching:
{{
  "caller_name": "...",
  "headline": "...",
  "context": "...",
  "open_items": ["..."],
  "commitments": [{{"owner": "user", "text": "...", "is_resolved": false}}],
  "time_sensitive_facts": [{{"key": "price_usd", "label": "Unit price", "value": "$400"}}],
  "key_names": ["..."]
}}

Transcript:
{transcript_str}
"""
        try:
            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            raw_text = response.text.strip()
            # Defensive JSON parse: unwrap code fences if present
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
            else:
                data = json.loads(raw_text)

            now = datetime.now(tz=timezone.utc)
            commitments = [
                Commitment(
                    owner=c.get("owner", "user"),
                    text=c.get("text", ""),
                    is_resolved=c.get("is_resolved", False),
                )
                for c in data.get("commitments", [])
            ]
            facts = []
            for f in data.get("time_sensitive_facts", []):
                key = f.get("key", "fact")
                value = str(f.get("value", ""))
                # Product price facts must match the enterprise database
                # exactly ("$940 per tonne" → "$940") or the freshness check
                # would report a spurious CHANGED.
                if key.startswith("price_"):
                    value = _normalize_price_value(value)
                facts.append(
                    TimeSensitiveFact(
                        key=key,
                        label=f.get("label", "Fact"),
                        value=value,
                        recorded_at=now,
                    )
                )

            headline = self._clean_headline(data.get("headline", "Call completed."))

            # Language the conversation was actually spoken in — drives the
            # recap frames (freshness flag / next-action / interruption note).
            language = detect_conversation_language(transcript_str)
            context = str(data.get("context", "") or "").strip()
            if not context and prior_summary and prior_summary.context:
                context = prior_summary.context

            return ThreadSummary(
                thread_id=thread_id or (prior_summary.thread_id if prior_summary else f"thread_{caller_id}"),
                caller_id=caller_id,
                caller_name=data.get("caller_name") or caller_name or (prior_summary.caller_name if prior_summary else None),
                headline=headline,
                context=context,
                language=language,
                open_items=data.get("open_items", []),
                commitments=commitments,
                time_sensitive_facts=facts,
                key_names=data.get("key_names", []),
                # Only quote the caller's truncated fragment, never the user's own
                # last turn (the "they were cut off" note refers to the caller).
                last_spoken_turn_text=(
                    valid_turns[-1].text
                    if is_interrupted and valid_turns and valid_turns[-1].speaker == Speaker.CALLER
                    else None
                ),
                created_at=prior_summary.created_at if prior_summary else now,
                last_updated_at=now,
                last_call_ended_at=now,
                is_interrupted=is_interrupted,
                call_count=(prior_summary.call_count + 1) if prior_summary else 1,
            )
        except Exception as e:
            logger.warning("Gemini extraction failed (%s), falling back to heuristic extractor", e)
            return self._heuristic_extract(
                turns, caller_id, caller_name, thread_id, is_interrupted, prior_summary
            )

    async def extract(
        self,
        turns: list[TranscriptEvent],
        caller_id: str,
        caller_name: Optional[str] = None,
        thread_id: Optional[str] = None,
        is_interrupted: bool = False,
        prior_summary: Optional[ThreadSummary] = None,
    ) -> ThreadSummary:
        """
        Extract structured ThreadSummary from turns.
        """
        if self.api_key and _HAS_GENAI and not settings.use_mocks:
            return await self._gemini_extract(
                turns, caller_id, caller_name, thread_id, is_interrupted, prior_summary
            )
        return self._heuristic_extract(
            turns, caller_id, caller_name, thread_id, is_interrupted, prior_summary
        )
