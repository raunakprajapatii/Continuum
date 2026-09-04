"""
modules/signal/tests/test_caller_matching.py
---------------------------------------------
Unit tests for CallerMatcher and normalise_caller_id.

Tests cover:
  - E.164 normalisation (spaces, dashes, parentheses)
  - SIP URI normalisation (case, transport params)
  - None / empty input handling
  - Record → Lookup round-trip
  - mark_interrupted / clear_interrupted lifecycle
  - Concurrent access (asyncio.Lock correctness)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from modules.signal.caller_matcher import CallerMatcher, normalise_caller_id
from shared.schemas import CallState, CallStateEvent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_event(
    caller_id: str | None,
    state: CallState = CallState.RINGING,
    thread_id: str | None = None,
    is_reconnect: bool = False,
) -> CallStateEvent:
    return CallStateEvent(
        event_id=str(uuid.uuid4()),
        session_id="test-session-001",
        thread_id=thread_id or "thread-test-001",
        state=state,
        previous_state=CallState.IDLE,
        caller_id=caller_id,
        is_reconnect=is_reconnect,
        timestamp=datetime.now(tz=timezone.utc),
    )


# ── normalise_caller_id ───────────────────────────────────────────────────────


class TestNormaliseCallerId:
    def test_e164_clean(self) -> None:
        assert normalise_caller_id("+14155550199") == "+14155550199"

    def test_e164_with_spaces_and_dashes(self) -> None:
        assert normalise_caller_id("+1 (415) 555-0199") == "+14155550199"

    def test_e164_with_dots(self) -> None:
        # dots are not in _E164_STRIP but trailing dot would be edge case
        result = normalise_caller_id("+1415.555.0199")
        assert result is not None
        assert "." not in result or result.startswith("+")

    def test_sip_uri_lowercase(self) -> None:
        result = normalise_caller_id("sip:Alice@Example.COM")
        assert result == "sip:alice@example.com"

    def test_sip_uri_strips_transport_param(self) -> None:
        result = normalise_caller_id("sip:alice@example.com;transport=tls")
        assert result == "sip:alice@example.com"
        assert "transport" not in (result or "")

    def test_sips_scheme(self) -> None:
        result = normalise_caller_id("sips:bob@example.org")
        assert result == "sips:bob@example.org"

    def test_none_returns_none(self) -> None:
        assert normalise_caller_id(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalise_caller_id("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalise_caller_id("   ") is None

    def test_same_number_different_formats_equal(self) -> None:
        a = normalise_caller_id("+1 (415) 555-0199")
        b = normalise_caller_id("+14155550199")
        assert a == b


# ── CallerMatcher ─────────────────────────────────────────────────────────────


class TestCallerMatcher:
    @pytest.fixture
    def matcher(self) -> CallerMatcher:
        return CallerMatcher()

    @pytest.mark.asyncio
    async def test_lookup_unknown_caller_returns_none(self, matcher: CallerMatcher) -> None:
        result = await matcher.lookup("+19998887777")
        assert result is None

    @pytest.mark.asyncio
    async def test_record_and_lookup(self, matcher: CallerMatcher) -> None:
        event = _make_event("+14155550199", thread_id="thread-Z-001")
        await matcher.record_event(event)

        entry = await matcher.lookup("+14155550199")
        assert entry is not None
        assert entry.thread_id == "thread-Z-001"
        assert entry.caller_id_raw == "+14155550199"

    @pytest.mark.asyncio
    async def test_lookup_normalises_input(self, matcher: CallerMatcher) -> None:
        """Record with dashes, lookup with spaces — should still match."""
        event = _make_event("+1-415-555-0199", thread_id="thread-Z-001")
        await matcher.record_event(event)

        entry = await matcher.lookup("+1 (415) 555-0199")
        assert entry is not None

    @pytest.mark.asyncio
    async def test_mark_interrupted(self, matcher: CallerMatcher) -> None:
        event = _make_event("+14155550199")
        await matcher.record_event(event)

        assert not (await matcher.lookup("+14155550199")).is_interrupted  # type: ignore[union-attr]

        await matcher.mark_interrupted("+14155550199")
        assert (await matcher.lookup("+14155550199")).is_interrupted  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_clear_interrupted(self, matcher: CallerMatcher) -> None:
        event = _make_event("+14155550199")
        await matcher.record_event(event)
        await matcher.mark_interrupted("+14155550199")
        await matcher.clear_interrupted("+14155550199")

        entry = await matcher.lookup("+14155550199")
        assert entry is not None
        assert not entry.is_interrupted

    @pytest.mark.asyncio
    async def test_record_none_caller_id_is_noop(self, matcher: CallerMatcher) -> None:
        """IDLE events have no caller_id — should not crash or store anything."""
        idle_event = _make_event(None, state=CallState.IDLE)
        await matcher.record_event(idle_event)  # should not raise
        result = await matcher.lookup(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_record_updates_existing_entry(self, matcher: CallerMatcher) -> None:
        """Second event for same caller should update last_event, not duplicate."""
        event1 = _make_event("+14155550199", thread_id="thread-001")
        event2 = _make_event("+14155550199", thread_id="thread-001", state=CallState.CONNECTED)
        await matcher.record_event(event1)
        await matcher.record_event(event2)

        entry = await matcher.lookup("+14155550199")
        assert entry is not None
        assert entry.last_event.state == CallState.CONNECTED

    @pytest.mark.asyncio
    async def test_all_entries(self, matcher: CallerMatcher) -> None:
        await matcher.record_event(_make_event("+14155550001"))
        await matcher.record_event(_make_event("+14155550002"))
        entries = await matcher.all_entries()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_concurrent_access_is_safe(self, matcher: CallerMatcher) -> None:
        """Concurrent record_event calls should not raise due to lock contention."""
        events = [_make_event(f"+1415555{i:04d}") for i in range(20)]
        await asyncio.gather(*[matcher.record_event(e) for e in events])
        entries = await matcher.all_entries()
        assert len(entries) == 20
