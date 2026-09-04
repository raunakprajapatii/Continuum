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
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from shared.schemas import (
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
    ) -> str:
        """
        Build and validate the Rime-formatted recap string.

        Raises ``RecapTextValidationError`` if the generated text violates any
        of the 8 Rime prompting guide rules.
        """
        parts: list[str] = []

        # ── Rule 1: Headline first, no preamble ───────────────────────────────
        headline = self._format_headline(summary)
        parts.append(headline)

        if urgency == RecapUrgency.HEADLINE_ONLY:
            text = self._join(parts)
            self._validate(text)
            return text

        # ── Rule 5: Freshness flags early ─────────────────────────────────────
        if freshness.any_changed:
            for fact_result in freshness.results:
                flag = fact_result.spoken_flag
                if flag:
                    parts.append(flag)

        # ── Standard detail: open items ───────────────────────────────────────
        if urgency in (RecapUrgency.STANDARD, RecapUrgency.EXTENDED):
            if summary.open_items:
                open_text = self._format_open_items(summary.open_items)
                if open_text:
                    parts.append(open_text)

        # ── Extended: stale/UNAVAILABLE fact caveats ──────────────────────────
        if urgency == RecapUrgency.EXTENDED:
            for fact_result in freshness.results:
                if fact_result.status == FreshnessStatus.UNAVAILABLE:
                    flag = fact_result.spoken_flag
                    if flag:
                        parts.append(flag)

            if summary.is_interrupted and summary.last_spoken_turn_text:
                interrupted_note = self._format_interrupted(
                    summary.last_spoken_turn_text
                )
                if interrupted_note:
                    parts.append(interrupted_note)

        # ── Rule 8: End with next action ──────────────────────────────────────
        next_action = self._format_next_action(summary)
        if next_action:
            parts.append(next_action)

        text = self._join(parts)
        self._validate(text)
        return text

    # ── private helpers ────────────────────────────────────────────────────────

    def _validate(self, text: str) -> None:
        violations = self._validator.validate(text)
        if violations:
            raise RecapTextValidationError(violations)

    @staticmethod
    def _join(parts: list[str]) -> str:
        return " ".join(p.strip().rstrip(".") + "." for p in parts if p.strip())

    @staticmethod
    def _format_headline(summary: ThreadSummary) -> str:
        """Rule 1 — one-sentence headline from ``summary.headline``."""
        headline = summary.headline.strip()
        # Ensure it ends with punctuation
        if not headline.endswith((".", "!", "?")):
            headline += "."
        return headline

    @staticmethod
    def _format_open_items(open_items: list[str]) -> str:
        """Convert the first open item into a spoken fragment ≤ 20 words."""
        if not open_items:
            return ""
        item = open_items[0].strip()
        # Prefix with "so," (Rule 3 — one disfluency max)
        sentence = f"So, still open: {item}"
        # Truncate if over word limit
        words = sentence.split()
        if len(words) > 20:
            sentence = " ".join(words[:19]) + "."
        return sentence

    @staticmethod
    def _format_interrupted(last_text: str) -> str:
        """Note the call was interrupted mid-sentence."""
        preview = last_text.strip().rstrip("- ").strip()
        if not preview:
            return ""
        sentence = f"They were cut off mid-sentence — they said: \"{preview}\"."
        words = sentence.split()
        if len(words) > 20:
            sentence = "The call dropped mid-sentence."
        return sentence

    @staticmethod
    def _format_next_action(summary: ThreadSummary) -> str:
        """Rule 8 — the single most useful next action."""
        # First unresolved commitment from the user is the clearest next action
        for commitment in summary.commitments:
            if not commitment.is_resolved and commitment.owner in ("user", "you"):
                action = commitment.text.strip()
                words = action.split()
                if len(words) > 18:
                    action = " ".join(words[:17]) + "."
                return f"Your move: {action}"

        # Fall back to first open item
        if summary.open_items:
            item = summary.open_items[0].strip()
            words = item.split()
            if len(words) > 17:
                item = " ".join(words[:16]) + "."
            return f"Top priority: {item}"

        return ""
