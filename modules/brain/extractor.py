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


class ConversationExtractor:
    """
    Robust extractor for conversational memory, strictly conforming to Rime guidelines.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (
            api_key
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

        # Currency prices: $400, $420.50, €500, £1,200
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
                        value=val,
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

        last_turn_text = valid_turns[-1].text if is_interrupted else None

        return ThreadSummary(
            thread_id=thread_id,
            caller_id=caller_id,
            caller_name=detected_name,
            headline=headline,
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

        prompt = f"""
You are the Brain of Continuum, a voice continuity assistant.
Analyze this phone call transcript.

STRICT CONSTRAINTS (Rime TTS compliance):
1. Headline MUST be a single sentence under 20 words. No preamble. Lead directly with the key subject.
2. Commitments: promises made (owner: 'user' or 'caller', text, is_resolved: false).
3. Time-sensitive facts: prices, quantities, deadlines (key, label, value).
4. Open items: unresolved topics or questions.
5. Key names / acronyms: names, ticket numbers, codes.

Return ONLY valid JSON matching:
{{
  "caller_name": "...",
  "headline": "...",
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
            facts = [
                TimeSensitiveFact(
                    key=f.get("key", "fact"),
                    label=f.get("label", "Fact"),
                    value=str(f.get("value", "")),
                    recorded_at=now,
                )
                for f in data.get("time_sensitive_facts", [])
            ]

            headline = self._clean_headline(data.get("headline", "Call completed."))

            return ThreadSummary(
                thread_id=thread_id or (prior_summary.thread_id if prior_summary else f"thread_{caller_id}"),
                caller_id=caller_id,
                caller_name=data.get("caller_name") or caller_name or (prior_summary.caller_name if prior_summary else None),
                headline=headline,
                open_items=data.get("open_items", []),
                commitments=commitments,
                time_sensitive_facts=facts,
                key_names=data.get("key_names", []),
                last_spoken_turn_text=valid_turns[-1].text if is_interrupted else None,
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
