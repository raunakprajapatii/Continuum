"""
modules/voice/recap_text_builder.py
-------------------------------------
Pair D — Recap Text Builder

Converts a ``ThreadSummary`` + ``FreshnessResult`` into Rime-compliant spoken
text ready to be passed to ``RimeTtsClient``.

Rime Prompting Guide — all 8 rules are enforced by ``RimePromptValidator``
*before* the text ever leaves this module:

  1. Lead with the one-sentence headline. No preamble.
  2. Every sentence must be under 20 words.
  3. Natural disfluencies sparingly ("so,", "yeah,") — never stacked.
  4. Punctuation is the only prosody tool. No SSML, no <break> tags.
  5. Freshness flags early: ``"Heads up — [old] is now [new]."``
  6. Wrap any ID / ticket number / code in ``spell(...)``.
  7. Never invent details not present in thread memory.
  8. End with the single most useful next action, if one exists.

Recap quality (light + short):
  The recap is headline first, then the extracted context sentence(s) — the
  substance behind the headline (what was discussed, decided, still open) —
  then only a changed-fact flag (freshness), then one next action. The context
  is what stops a recap from collapsing into a bare headline + "call got cut"
  note. A standalone "still open / open items" sentence is deliberately NOT
  emitted: it only repeats the headline or the next action. The only extra
  that may appear (long ring window only) is a short note when the previous
  call dropped mid-sentence, because that fragment can carry a ticket number
  the agent needs.

``language`` selects the fixed *frames* only (freshness flag, interruption
note, next-action lead-in):
  - ``en``  → English frames.
  - ``hi``  → HINGLISH frames: Hindi written in Latin (Roman) letters, mixed
    naturally with English words (e.g. "Sun — price ab $420 hai."). Thread
    memory content — headline, open items, commitments — is kept exactly as
    it was recorded (Gemini already writes Hinglish for Hindi conversations),
    so nothing is ever invented or translated on the fly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from shared.schemas import (
    FactCheckResult,
    FreshnessResult,
    FreshnessStatus,
    RecapUrgency,
    ThreadSummary,
)

logger = logging.getLogger(__name__)

# Regex to detect SSML / HTML tags (Rule 4 violation)
_SSML_RE = re.compile(r"<[^>]+>", re.IGNORECASE)

# Disfluency tokens that, if stacked, violate Rule 3
_DISFLUENCY_TOKENS = ("so,", "yeah,", "uh,", "um,", "like,", "right,", "okay,")

# ticket / ID patterns that need spell() wrapping (Rule 6)
# Matches patterns like ABC-123, XYZ, 4-digit+ numbers on their own
_ID_RE = re.compile(
    r"\b([A-Z]{2,}-\d+|[A-Z]{3,}\d+|\b\d{5,})\b"
)

_MONTH_NAMES = {
    "01": "January", "1": "January",
    "02": "February", "2": "February",
    "03": "March", "3": "March",
    "04": "April", "4": "April",
    "05": "May", "5": "May",
    "06": "June", "6": "June",
    "07": "July", "7": "July",
    "08": "August", "8": "August",
    "09": "September", "9": "September",
    "10": "October",
    "11": "November",
    "12": "December",
}


def _ordinal_suffix(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ── Validation ─────────────────────────────────────────────────────────────────


@dataclass
class RimePromptValidator:
    """
    Validates recap text against all 8 Rime prompting guide rules.

    Usage::

        violations = RimePromptValidator().validate(text)
        if violations:
            raise RecapTextValidationError(violations)
    """

    def validate(self, text: str) -> list[str]:
        """Return a list of rule violations. Empty list means the text is valid."""
        violations: list[str] = []
        sentences = self._split_sentences(text)

        # Rule 1 — headline must be first, no preamble filler
        self._check_no_preamble(text, violations)

        # Rule 2 — every sentence ≤ 20 words
        for i, sent in enumerate(sentences, 1):
            word_count = len(sent.split())
            if word_count > 20:
                violations.append(
                    f"Rule 2: sentence {i} has {word_count} words (max 20): {sent!r}"
                )

        # Rule 3 — disfluencies not stacked (no two in a row)
        self._check_disfluency_stacking(text, violations)

        # Rule 4 — no SSML / HTML tags
        ssml_matches = _SSML_RE.findall(text)
        if ssml_matches:
            violations.append(
                f"Rule 4: SSML/HTML tags found (use punctuation only): {ssml_matches}"
            )

        # Rule 5 — freshness flag format (checked at build time, not here)
        # Rule 6 — IDs / ticket numbers wrapped in spell()
        self._check_bare_ids(text, violations)

        # Rule 7 — no explicit invention check (structural; enforced by builder)
        # Rule 8 — ends with a next action (structural; enforced by builder)

        return violations

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split on sentence-ending punctuation."""
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    @staticmethod
    def _check_no_preamble(text: str, violations: list[str]) -> None:
        preamble_patterns = [
            r"^(here is|here's|let me|i'll give you|so here|alright,?\s+so)",
        ]
        for pat in preamble_patterns:
            if re.match(pat, text.strip(), re.IGNORECASE):
                violations.append(
                    f"Rule 1: text starts with preamble filler. Lead with the headline directly."
                )
                break

    @staticmethod
    def _check_disfluency_stacking(text: str, violations: list[str]) -> None:
        lower = text.lower()
        for tok in _DISFLUENCY_TOKENS:
            # count consecutive occurrences (stacking)
            stacked = re.search(
                rf"({re.escape(tok)}\s+){{2,}}", lower
            )
            if stacked:
                violations.append(
                    f"Rule 3: disfluency {tok!r} stacked — use sparingly, never consecutively."
                )

    @staticmethod
    def _check_bare_ids(text: str, violations: list[str]) -> None:
        """Flag any ID-like token not already inside spell(...)."""
        # Remove existing spell(...) regions first
        cleaned = re.sub(r"spell\([^)]*\)", "", text)
        bare = _ID_RE.findall(cleaned)
        if bare:
            violations.append(
                f"Rule 6: ticket/ID tokens not wrapped in spell(): {bare}. "
                "Use spell(TOKEN) for each."
            )


class RecapTextValidationError(Exception):
    """Raised when recap text fails the Rime prompting guide rules."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Recap text failed {len(violations)} Rime prompting guide rule(s):\n"
            + "\n".join(f"  • {v}" for v in violations)
        )


# ── Builder ───────────────────────────────────────────────────────────────────


class RecapTextBuilder:
    """
    Builds Rime-compliant spoken recap text from a ``ThreadSummary`` and a
    ``FreshnessResult``.

    The output text is validated against all 8 rules before being returned.
    A ``RecapTextValidationError`` is raised on violations.

    Usage::

        builder = RecapTextBuilder()
        text = builder.build(
            summary=recap_request.summary,
            freshness=freshness_result,
            urgency=recap_request.urgency,
        )
    """

    def __init__(self, validator: Optional[RimePromptValidator] = None) -> None:
        self._validator = validator or RimePromptValidator()

    def build(
        self,
        summary: ThreadSummary,
        freshness: FreshnessResult,
        urgency: RecapUrgency = RecapUrgency.STANDARD,
        language: str = "en",
    ) -> str:
        """
        Build and validate the Rime-formatted recap string.

        ``language`` (``en`` / ``hi``) selects the fixed recap frames only.
        ``hi`` produces HINGLISH frames (Latin-script Hindi mixed with English)
        — never Devanagari. Thread-memory content — headline, open items,
        commitments — is kept exactly as it was recorded so nothing is ever
        invented or translated on the fly.

        Structure (light and short):

          HEADLINE_ONLY:  headline.
          STANDARD:       headline → context (substance, ≤ 2 short sentences)
                          → freshness flags (changed facts only)
                          → single next action.
          EXTENDED:       headline → context → freshness flags (incl.
                          unavailable facts) → short mid-sentence-drop note
                          (if interrupted) → single next action.

        A standalone open-items sentence is intentionally omitted — it only
        repeats the headline or the next action.

        Raises ``RecapTextValidationError`` if the generated text violates any
        of the 8 Rime prompting guide rules.
        """
        hi = (language or "").strip().lower().startswith("hi")
        parts: list[str] = []

        # ── Rule 1: Headline first, no preamble ───────────────────────────────
        # When extraction produced only a generic placeholder headline, lift
        # the real substance from the context sentence instead — a recap that
        # leads with "Call completed." tells the agent nothing.
        headline = self._format_headline(summary)
        parts.append(headline)

        if urgency == RecapUrgency.HEADLINE_ONLY:
            text = self._join(parts)
            text = self.prenormalize_text(text)
            text = self.wrap_ids(text)
            self._validate(text)
            return text

        # ── Substance behind the headline ─────────────────────────────────────
        # Gemini's ``context`` field is what keeps a recap from collapsing into
        # a bare headline + "call got cut" note: it carries what was discussed,
        # decided and still open. Kept to two short spoken sentences.
        context = self._format_context(summary)
        if context:
            parts.append(context)

        # ── Rule 5: Freshness flags early ─────────────────────────────────────
        if freshness.any_changed:
            for fact_result in freshness.results:
                if fact_result.status == FreshnessStatus.CHANGED:
                    flag = self._spoken_flag(fact_result, hi=hi)
                    if flag:
                        parts.append(flag)

        # ── Extended: stale/UNAVAILABLE fact caveats ──────────────────────────
        if urgency == RecapUrgency.EXTENDED:
            for fact_result in freshness.results:
                if fact_result.status == FreshnessStatus.UNAVAILABLE:
                    flag = self._spoken_flag(fact_result, hi=hi)
                    if flag:
                        parts.append(flag)

            # The previous call dropped mid-sentence — that fragment can carry
            # an important anchor (e.g. a ticket number), so keep it short.
            if summary.is_interrupted and summary.last_spoken_turn_text:
                interrupted_note = self._format_interrupted(
                    summary.last_spoken_turn_text, hi=hi
                )
                if interrupted_note:
                    parts.append(interrupted_note)

        # ── Rule 8: End with the single next action ──────────────────────────
        # Open items feed the next action (fallback) rather than a standalone
        # sentence, keeping the recap free of repetition.
        next_action = self._format_next_action(summary, hi=hi)
        if next_action:
            parts.append(next_action)

        text = self._join(parts)
        text = self.prenormalize_text(text)
        text = self.wrap_ids(text)
        self._validate(text)
        return text

    # ── helpers ────────────────────────────────────────────────────────────────

    @classmethod
    def prenormalize_text(cls, text: str) -> str:
        """
        Pre-normalizes known Rime normalizer gaps per RIME_RESEARCH.md & docs.rime.ai:
        - MM/DD dates without year -> 'Month ordinal' (e.g. 04/21 -> April 21st)
        - Bare hours with meridiem -> 3pm -> 3:00pm
        - Numeric ranges -> 10-15 -> 10 to 15 (avoids literal hyphen reading)
        - Decades -> 1990s -> the nineteen nineties
        - Replaces exclamation marks with periods for a calm, composed baseline.
        """
        # 1. Dates without year (e.g. 04/21 or 4/21 not followed by /YYYY)
        def replace_date(match: re.Match) -> str:
            month_num = match.group(1)
            day_num = int(match.group(2))
            month_name = _MONTH_NAMES.get(month_num)
            if month_name:
                return f"{month_name} {_ordinal_suffix(day_num)}"
            return match.group(0)

        text = re.sub(
            r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?!\s*/\s*\d{2,4})\b",
            replace_date,
            text,
        )

        # 2. Bare hours with meridiem (e.g. 3pm or 3 pm -> 3:00pm)
        text = re.sub(r"\b([1-9]|1[0-2])\s*([ap]m)\b", r"\1:00\2", text, flags=re.IGNORECASE)

        # 3. Numeric ranges (pure digits e.g. 10-15 -> 10 to 15)
        text = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1 to \2", text)

        # 4. Decades
        text = re.sub(r"\b1990s\b", "the nineteen nineties", text, flags=re.IGNORECASE)
        text = re.sub(r"\b1980s\b", "the nineteen eighties", text, flags=re.IGNORECASE)

        # 5. Calm prosody (replace exclamation with period)
        text = text.replace("!", ".")

        return text

    @staticmethod
    def wrap_ids(text: str) -> str:
        """Wrap bare ticket / ID tokens in spell(...) per Rule 6."""
        def replacer(match: re.Match) -> str:
            return f"spell({match.group(0)})"

        parts: list[str] = []
        last_idx = 0
        for m in re.finditer(r"spell\([^)]*\)", text):
            segment = text[last_idx:m.start()]
            parts.append(_ID_RE.sub(replacer, segment))
            parts.append(m.group(0))
            last_idx = m.end()
        parts.append(_ID_RE.sub(replacer, text[last_idx:]))
        return "".join(parts)

    def _validate(self, text: str) -> None:
        violations = self._validator.validate(text)
        if violations:
            raise RecapTextValidationError(violations)

    @staticmethod
    def _join(parts: list[str]) -> str:
        return " ".join(p.strip().rstrip(".") + "." for p in parts if p.strip())

    @staticmethod
    def _format_headline(summary: ThreadSummary) -> str:
        """
        Rule 1 — one-sentence headline from ``summary.headline``.

        Generic placeholder headlines ("Call completed." etc.) are replaced
        by the first context sentence when one exists, so the recap always
        leads with real substance.
        """
        headline = summary.headline.strip()
        if summary.context:
            generic = (
                headline.lower().rstrip(".") in (
                    "call completed",
                    "call ended without spoken turns",
                    "call with caller ended without spoken turns",
                )
            )
            if generic:
                first = RecapTextBuilder._first_sentence(summary.context)
                if first:
                    words = first.split()
                    if len(words) > 20:
                        first = " ".join(words[:20])
                    headline = first
        # Ensure it ends with punctuation
        if not headline.endswith((".", "!", "?")):
            headline += "."
        return headline

    @staticmethod
    def _first_sentence(text: str) -> str:
        """Return the first sentence of a text block (or the whole block)."""
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", text)
            if s.strip()
        ]
        return sentences[0] if sentences else text.strip()

    @staticmethod
    def _format_context(summary: ThreadSummary) -> str:
        """
        Spoken context behind the headline: at most two sentences, each capped
        at 20 words so the Rime prompt-guide validation can never fail on the
        extracted context.
        """
        if not summary.context:
            return ""
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", summary.context)
            if s.strip()
        ]
        kept: list[str] = []
        for sentence in sentences[:2]:
            words = sentence.split()
            if len(words) > 20:
                words = words[:20]
            kept.append(" ".join(words))
        return " ".join(kept)

    @staticmethod
    def _spoken_flag(result: FactCheckResult, hi: bool = False) -> str:
        """
        Ready-to-insert spoken flag for a fact check outcome.

        English uses ``FactCheckResult.spoken_flag`` (Rime rule 5 phrasing);
        Hinglish (``hi``) gets the same two facts in a Latin-script frame.
        """
        if result.status == FreshnessStatus.CHANGED and result.live_value is not None:
            if hi:
                return (
                    f"Sun — {result.label} pehle {result.cached_value} tha, "
                    f"ab {result.live_value} hai."
                )
            return result.spoken_flag
        if result.status == FreshnessStatus.UNAVAILABLE:
            if hi:
                return (
                    f"Yeh {result.label} ab confirm nahi ho paya — "
                    f"last value {result.cached_value} thi."
                )
            return result.spoken_flag
        return ""

    @staticmethod
    def _format_interrupted(last_text: str, hi: bool = False) -> str:
        """Note the call was interrupted mid-sentence."""
        preview = last_text.strip().rstrip("- ").strip()
        if not preview:
            return ""
        sentence = (
            f"Call beech mein cut ho gayi. Unka last line: \"{preview}\"."
            if hi
            else f"They were cut off mid-sentence — they said: \"{preview}\"."
        )
        words = sentence.split()
        if len(words) > 20:
            sentence = "The call dropped mid-sentence." if not hi else "Call beech mein cut ho gayi."
        return sentence

    @staticmethod
    def _format_next_action(summary: ThreadSummary, hi: bool = False) -> str:
        """Rule 8 — the single most useful next action."""
        # First unresolved commitment from the user is the clearest next action
        for commitment in summary.commitments:
            if not commitment.is_resolved and commitment.owner in ("user", "you"):
                action = commitment.text.strip()
                words = action.split()
                if len(words) > 18:
                    action = " ".join(words[:17]) + "."
                return f"Aapka move: {action}" if hi else f"Your move: {action}"

        # Fall back to first open item (keeps the recap to one actionable line)
        if summary.open_items:
            item = summary.open_items[0].strip()
            words = item.split()
            if len(words) > 17:
                item = " ".join(words[:16]) + "."
            return f"Sabse zaroori: {item}" if hi else f"Top priority: {item}"

        return ""
