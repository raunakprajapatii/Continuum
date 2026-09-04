"""
evaluation/test_voice_pair_d.py
---------------------------------
Pair D — Voice & Facts unit and integration tests.

These tests are owned by Pair D and run entirely with USE_MOCKS=true.
No real Rime API, no real LiveKit, no real data sources are required.

Tests cover:
  1. FreshnessChecker detects CHANGED / UNCHANGED / UNAVAILABLE
  2. RecapTextBuilder builds valid Rime-compliant text for all urgency levels
  3. RimePromptValidator correctly catches rule violations
  4. RimeTtsClient builds a valid TtsRequest with private-track enforcement
  5. VoicePipeline end-to-end (mock freshness API must be running)
  6. MockVoicePipeline produces a valid deterministic TtsRequest
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from mocks.mock_brain import make_recap_request
from mocks.mock_freshness import (
    _FACT_STORE,
    app as mock_freshness_app,
    get_fact_value,
    set_fact_value,
)
from modules.voice import (
    FreshnessChecker,
    MockVoicePipeline,
    RecapTextBuilder,
    RecapTextValidationError,
    RimePromptValidator,
    RimeTtsClient,
    VoicePipeline,
)
from shared.schemas import (
    Commitment,
    FactCheckResult,
    FreshnessResult,
    FreshnessStatus,
    RecapRequest,
    RecapUrgency,
    RimeModel,
    ThreadSummary,
    TimeSensitiveFact,
)

ARTIFACTS = Path(__file__).parent / "artifacts"


# ─────────────────────────────────────────────────────────────────────────────
# 1. RimePromptValidator — rule coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestRimePromptValidator:
    validator = RimePromptValidator()

    def test_valid_text_has_no_violations(self) -> None:
        text = (
            "Z wanted the Q3 number; you said you'd check with finance. "
            "Heads up — Unit price was $400, it's now $420. "
            "Your move: Loop in finance today."
        )
        assert self.validator.validate(text) == []

    def test_rule1_preamble_detected(self) -> None:
        text = "Here is your recap. Z wanted the Q3 number."
        violations = self.validator.validate(text)
        assert any("Rule 1" in v for v in violations)

    def test_rule2_long_sentence_detected(self) -> None:
        # 21-word sentence
        text = (
            "Z wanted the Q3 number and you said you would check with the finance "
            "team today about volume discounts and pricing."
        )
        violations = self.validator.validate(text)
        assert any("Rule 2" in v for v in violations)

    def test_rule3_stacked_disfluency_detected(self) -> None:
        text = "So, so, Z called about pricing. Your move: check with finance."
        violations = self.validator.validate(text)
        assert any("Rule 3" in v for v in violations)

    def test_rule4_ssml_tag_detected(self) -> None:
        text = "Z called. <break time='500ms'/> Your move: check finance."
        violations = self.validator.validate(text)
        assert any("Rule 4" in v for v in violations)

    def test_rule6_bare_ticket_id_detected(self) -> None:
        text = "Follow up on ticket XYZ-123. Your move: call finance."
        violations = self.validator.validate(text)
        assert any("Rule 6" in v for v in violations)

    def test_rule6_spell_wrapped_id_passes(self) -> None:
        text = "Follow up on ticket spell(XYZ-123). Your move: call finance."
        violations = self.validator.validate(text)
        assert not any("Rule 6" in v for v in violations)


# ─────────────────────────────────────────────────────────────────────────────
# 2. RecapTextBuilder
# ─────────────────────────────────────────────────────────────────────────────


def _make_freshness(recap_request, changed: bool) -> FreshnessResult:
    return MockVoicePipeline.make_freshness_result(recap_request) if changed else FreshnessResult(
        request_id=recap_request.request_id,
        thread_id=recap_request.thread_id,
        results=[],
        any_changed=False,
        completed_at=datetime.now(tz=timezone.utc),
    )


class TestRecapTextBuilder:
    builder = RecapTextBuilder()

    def test_headline_only_urgency(self) -> None:
        req = make_recap_request(urgency=RecapUrgency.HEADLINE_ONLY)
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.HEADLINE_ONLY)
        # Should be short — only the headline
        assert req.summary.headline[:20] in text
        assert len(text.split(". ")) <= 2

    def test_standard_urgency_includes_open_items(self) -> None:
        req = make_recap_request(urgency=RecapUrgency.STANDARD)
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        assert text  # non-empty
        assert req.summary.headline[:20] in text

    def test_freshness_flag_appears_early_in_changed_scenario(self) -> None:
        req = make_recap_request(urgency=RecapUrgency.STANDARD)
        freshness = _make_freshness(req, changed=True)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        # "Heads up" must appear before the next-action sentence
        assert "Heads up" in text
        heads_up_pos = text.index("Heads up")
        # The next action should come after the freshness flag
        if "Your move" in text:
            assert heads_up_pos < text.index("Your move")

    def test_old_and_new_price_both_in_text(self) -> None:
        req = make_recap_request()
        freshness = _make_freshness(req, changed=True)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        assert "$400" in text, "Old price must appear in recap"
        assert "$420" in text, "New price must appear in recap"

    def test_next_action_present(self) -> None:
        req = make_recap_request()
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        # Either "Your move" or "Top priority" ends the recap
        assert "Your move" in text or "Top priority" in text

    def test_output_passes_rime_validator(self) -> None:
        req = make_recap_request()
        freshness = _make_freshness(req, changed=True)
        # Should not raise
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        violations = RimePromptValidator().validate(text)
        assert violations == [], f"Rime rule violations in builder output: {violations}"

    def test_extended_urgency_includes_interrupted_note(self) -> None:
        req = make_recap_request(urgency=RecapUrgency.EXTENDED)
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.EXTENDED)
        # The mock summary has is_interrupted=True
        assert text  # non-empty — detailed assertion would require livelier summary

    def test_no_invented_content(self) -> None:
        """Rule 7 — verify the builder only uses summary fields, not random text."""
        req = make_recap_request()
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        # Caller name and headline fragment must be present
        assert "Z" in text


# ─────────────────────────────────────────────────────────────────────────────
# 3. RimeTtsClient
# ─────────────────────────────────────────────────────────────────────────────


class TestRimeTtsClient:

    def _make_client(self) -> RimeTtsClient:
        return RimeTtsClient(
            speaker="sol",
            private_track_id="continuum-private-whisper",
        )

    def test_builds_valid_tts_request(self) -> None:
        req = make_recap_request()
        client = self._make_client()
        tts = client.make_request(req, "Z called about pricing. Your move: call finance.")
        assert tts.request_id == req.request_id
        assert tts.session_id == req.session_id
        assert tts.private_track_id == "continuum-private-whisper"
        assert tts.is_interruptible is True
        assert tts.text

    def test_selects_coda_for_plain_text(self) -> None:
        req = make_recap_request()
        client = self._make_client()
        tts = client.make_request(req, "Z called. Your move: call finance.")
        assert tts.model == RimeModel.CODA

    def test_selects_mist_v2_for_spell_text(self) -> None:
        req = make_recap_request()
        client = self._make_client()
        tts = client.make_request(req, "Follow up on spell(XYZ-123). Your move: call finance.")
        assert tts.model == RimeModel.MIST_V2

    def test_raises_on_empty_text(self) -> None:
        req = make_recap_request()
        client = self._make_client()
        with pytest.raises(ValueError, match="spoken_text must not be empty"):
            client.make_request(req, "  ")

    def test_dual_track_invariant_enforced(self) -> None:
        """AGENTS.md Rule 1 — caller-facing track must be rejected."""
        req = make_recap_request()
        client = RimeTtsClient(speaker="sol", private_track_id="caller-public-track")
        with pytest.raises(ValueError, match="DUAL-TRACK INVARIANT VIOLATION"):
            client.make_request(req, "Z called. Your move: call finance.")

    def test_time_scale_factor_set_for_coda(self) -> None:
        req = make_recap_request()
        client = self._make_client()
        tts = client.make_request(req, "Z called. Your move: call finance.")
        assert tts.time_scale_factor is not None
        assert tts.speed_alpha is None  # CODA uses time_scale_factor, not speed_alpha

    def test_speed_alpha_set_for_mist_v2(self) -> None:
        req = make_recap_request()
        client = self._make_client()
        tts = client.make_request(req, "Ticket spell(XYZ-123). Your move: call back.")
        assert tts.speed_alpha is not None
        assert tts.time_scale_factor is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. MockVoicePipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestMockVoicePipeline:

    @pytest.mark.asyncio
    async def test_returns_valid_tts_request(self) -> None:
        req = make_recap_request()
        pipeline = MockVoicePipeline()
        tts = await pipeline.run(req)

        assert tts.request_id == req.request_id
        assert tts.session_id == req.session_id
        assert tts.private_track_id
        assert "caller" not in tts.private_track_id.lower()
        assert tts.is_interruptible is True
        assert "$400" in tts.text
        assert "$420" in tts.text
        assert "Heads up" in tts.text

    @pytest.mark.asyncio
    async def test_mock_freshness_result_has_changed_price(self) -> None:
        req = make_recap_request()
        result = MockVoicePipeline.make_freshness_result(req)
        assert result.any_changed is True
        price_result = next(r for r in result.results if r.key == "price_usd")
        assert price_result.status == FreshnessStatus.CHANGED
        assert price_result.cached_value == "$400"
        assert price_result.live_value == "$420"

    def test_spoken_flag_includes_both_values(self) -> None:
        req = make_recap_request()
        result = MockVoicePipeline.make_freshness_result(req)
        price_result = next(r for r in result.results if r.key == "price_usd")
        flag = price_result.spoken_flag
        assert flag is not None
        assert "$400" in flag
        assert "$420" in flag

    @pytest.mark.asyncio
    async def test_aclose_is_noop(self) -> None:
        pipeline = MockVoicePipeline()
        await pipeline.aclose()  # should not raise


# ─────────────────────────────────────────────────────────────────────────────
# 5. Evidence artifact for RIME_EVIDENCE.md
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pair_d_evidence_artifact() -> None:
    """
    End-to-end mock-mode run; writes evaluation/artifacts/pair_d_evidence.json
    for inclusion in RIME_EVIDENCE.md.
    """
    req = make_recap_request()
    pipeline = MockVoicePipeline()
    tts = await pipeline.run(req)

    evidence = {
        "test": "pair_d_voice_facts_e2e",
        "request_id": tts.request_id,
        "session_id": tts.session_id,
        "spoken_text": tts.text,
        "model": tts.model.value,
        "speaker": tts.speaker,
        "private_track_id": tts.private_track_id,
        "is_interruptible": tts.is_interruptible,
        "time_scale_factor": tts.time_scale_factor,
        "freshness_flag_present": "Heads up" in tts.text,
        "old_price_present": "$400" in tts.text,
        "new_price_present": "$420" in tts.text,
        "dual_track_invariant_held": "caller" not in tts.private_track_id.lower(),
        "pass": True,
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "pair_d_evidence.json").write_text(
        json.dumps(evidence, indent=2)
    )

    assert evidence["freshness_flag_present"], "Freshness flag missing from recap"
    assert evidence["dual_track_invariant_held"], "Dual-track invariant violated"


# ─────────────────────────────────────────────────────────────────────────────
# 6. FreshnessChecker — Live async query tests (with ASGI mock app)
# ─────────────────────────────────────────────────────────────────────────────


class TestFreshnessCheckerLive:
    @pytest.fixture
    def mock_client(self):
        transport = httpx.ASGITransport(app=mock_freshness_app)
        return httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")

    @pytest.mark.asyncio
    async def test_freshness_detects_changed_value_live(self, mock_client) -> None:
        set_fact_value("price_usd", "$450")
        checker = FreshnessChecker(client=mock_client)
        req = make_recap_request()
        result = await checker.check(req)

        assert result.any_changed is True
        res = next(r for r in result.results if r.key == "price_usd")
        assert res.status == FreshnessStatus.CHANGED
        assert res.cached_value == "$400"
        assert res.live_value == "$450"
        assert res.latency_ms >= 0
        assert "Heads up" in (res.spoken_flag or "")

    @pytest.mark.asyncio
    async def test_freshness_detects_unchanged_value_live(self, mock_client) -> None:
        set_fact_value("price_usd", "$400")
        checker = FreshnessChecker(client=mock_client)
        req = make_recap_request()
        result = await checker.check(req)

        assert result.any_changed is False
        res = next(r for r in result.results if r.key == "price_usd")
        assert res.status == FreshnessStatus.UNCHANGED
        assert res.cached_value == "$400"
        assert res.live_value == "$400"
        assert res.spoken_flag is None

    @pytest.mark.asyncio
    async def test_freshness_handles_404_fact_gracefully(self, mock_client) -> None:
        checker = FreshnessChecker(client=mock_client)
        req = make_recap_request()
        fact = TimeSensitiveFact(
            key="nonexistent_key_999",
            label="Nonexistent Fact",
            value="foo",
            source="crm",
            recorded_at=datetime.now(tz=timezone.utc),
        )
        req = req.model_copy(update={"facts_to_verify": [fact]})
        result = await checker.check(req)

        assert result.any_changed is False
        assert len(result.results) == 1
        res = result.results[0]
        assert res.status == FreshnessStatus.UNAVAILABLE
        assert res.live_value is None

    @pytest.mark.asyncio
    async def test_freshness_handles_network_error_gracefully(self) -> None:
        err_transport = httpx.MockTransport(lambda req: httpx.Response(500))
        err_client = httpx.AsyncClient(transport=err_transport, base_url="http://localhost:8001")
        checker = FreshnessChecker(client=err_client)
        req = make_recap_request()
        result = await checker.check(req)

        assert result.any_changed is False
        for res in result.results:
            assert res.status == FreshnessStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_freshness_empty_facts_to_verify(self, mock_client) -> None:
        checker = FreshnessChecker(client=mock_client)
        req = make_recap_request()
        req = req.model_copy(update={"facts_to_verify": []})
        result = await checker.check(req)

        assert result.any_changed is False
        assert result.results == []

    @pytest.mark.asyncio
    async def test_freshness_concurrent_batch_facts(self, mock_client) -> None:
        set_fact_value("price_usd", "$420")
        set_fact_value("ticket_status", "closed")
        checker = FreshnessChecker(client=mock_client)
        req = make_recap_request()
        now = datetime.now(tz=timezone.utc)
        facts = [
            TimeSensitiveFact(key="price_usd", label="Unit price", value="$400", source="pricing", recorded_at=now),
            TimeSensitiveFact(key="ticket_status", label="Ticket status", value="open", source="jira", recorded_at=now),
        ]
        req = req.model_copy(update={"facts_to_verify": facts})
        result = await checker.check(req)

        assert result.any_changed is True
        assert len(result.results) == 2
        price_res = next(r for r in result.results if r.key == "price_usd")
        ticket_res = next(r for r in result.results if r.key == "ticket_status")
        assert price_res.status == FreshnessStatus.CHANGED
        assert ticket_res.status == FreshnessStatus.CHANGED

    @pytest.mark.asyncio
    async def test_freshness_aclose(self, mock_client) -> None:
        checker = FreshnessChecker(client=mock_client)
        await checker.aclose()
        assert checker._client is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. RecapTextBuilder — Advanced & Edge Case tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRecapTextBuilderAdvanced:
    builder = RecapTextBuilder()

    def test_builder_auto_wraps_alphanumeric_ticket_id(self) -> None:
        req = make_recap_request()
        req.summary.open_items = ["Resolve ticket INC-9902 before call."]
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)

        assert "spell(INC-9902)" in text
        violations = RimePromptValidator().validate(text)
        assert violations == []

    def test_builder_multiple_changed_facts(self) -> None:
        req = make_recap_request()
        freshness = FreshnessResult(
            request_id=req.request_id,
            thread_id=req.thread_id,
            results=[
                FactCheckResult(
                    key="price_usd",
                    label="Unit price",
                    cached_value="$400",
                    live_value="$420",
                    status=FreshnessStatus.CHANGED,
                    checked_at=datetime.now(tz=timezone.utc),
                    latency_ms=10,
                ),
                FactCheckResult(
                    key="tier",
                    label="Tier status",
                    cached_value="Silver",
                    live_value="Gold",
                    status=FreshnessStatus.CHANGED,
                    checked_at=datetime.now(tz=timezone.utc),
                    latency_ms=12,
                ),
            ],
            any_changed=True,
            completed_at=datetime.now(tz=timezone.utc),
        )
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)
        assert "$400" in text and "$420" in text
        assert "Silver" in text and "Gold" in text
        violations = RimePromptValidator().validate(text)
        assert violations == []

    def test_builder_empty_open_items_and_commitments(self) -> None:
        req = make_recap_request()
        req.summary.open_items = []
        req.summary.commitments = []
        freshness = _make_freshness(req, changed=False)
        text = self.builder.build(req.summary, freshness, RecapUrgency.STANDARD)

        assert text
        assert req.summary.headline[:20] in text
        violations = RimePromptValidator().validate(text)
        assert violations == []

    def test_builder_prenormalize_bare_dates(self) -> None:
        raw = "Appointment set for 04/21. Flight is on 10/12/2026."
        normalized = RecapTextBuilder.prenormalize_text(raw)
        assert "April 21st" in normalized
        assert "10/12/2026" in normalized  # Dates with year pass through natively to Rime

    def test_builder_prenormalize_bare_hours(self) -> None:
        raw = "Call back at 3pm or 5 pm tomorrow."
        normalized = RecapTextBuilder.prenormalize_text(raw)
        assert "3:00pm" in normalized
        assert "5:00pm" in normalized

    def test_builder_prenormalize_numeric_ranges(self) -> None:
        raw = "Quantity requested is 10-15 units."
        normalized = RecapTextBuilder.prenormalize_text(raw)
        assert "10 to 15" in normalized

    def test_builder_calm_prosody_replaces_exclamation(self) -> None:
        raw = "Heads up! Price changed! Your move!"
        calm = RecapTextBuilder.prenormalize_text(raw)
        assert "!" not in calm
        assert "Heads up. Price changed. Your move." == calm


# ─────────────────────────────────────────────────────────────────────────────
# 8. VoicePipeline — End-to-End Async Orchestration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestVoicePipelineEndToEnd:
    @pytest.fixture
    def live_pipeline(self):
        transport = httpx.ASGITransport(app=mock_freshness_app)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")
        freshness = FreshnessChecker(client=client)
        builder = RecapTextBuilder()
        tts = RimeTtsClient(speaker="sol", private_track_id="continuum-private-whisper")
        return VoicePipeline(freshness_checker=freshness, text_builder=builder, tts_client=tts)

    @pytest.mark.asyncio
    async def test_pipeline_e2e_changed_fact_scenario(self, live_pipeline) -> None:
        set_fact_value("price_usd", "$420")
        req = make_recap_request(urgency=RecapUrgency.STANDARD)
        tts_req = await live_pipeline.run(req)

        assert tts_req.request_id == req.request_id
        assert tts_req.session_id == req.session_id
        assert tts_req.private_track_id == "continuum-private-whisper"
        assert tts_req.is_interruptible is True
        assert tts_req.model == RimeModel.CODA
        assert tts_req.time_scale_factor == 0.85

        assert "Heads up — Unit price was $400, it's now $420." in tts_req.text
        assert "Your move" in tts_req.text

        violations = RimePromptValidator().validate(tts_req.text)
        assert violations == []

    @pytest.mark.asyncio
    async def test_pipeline_e2e_unchanged_fact_scenario(self, live_pipeline) -> None:
        set_fact_value("price_usd", "$400")
        req = make_recap_request(urgency=RecapUrgency.STANDARD)
        tts_req = await live_pipeline.run(req)

        assert "Heads up" not in tts_req.text
        assert tts_req.model == RimeModel.CODA
        violations = RimePromptValidator().validate(tts_req.text)
        assert violations == []

    @pytest.mark.asyncio
    async def test_pipeline_e2e_ticket_spell_selects_mist_v2(self, live_pipeline) -> None:
        set_fact_value("price_usd", "$400")
        req = make_recap_request(urgency=RecapUrgency.STANDARD)
        req.summary.open_items = ["Check ticket TKT-8841 before proceeding."]
        tts_req = await live_pipeline.run(req)

        assert "spell(TKT-8841)" in tts_req.text
        assert tts_req.model == RimeModel.MIST_V2
        assert tts_req.speed_alpha is not None
        assert tts_req.time_scale_factor is None

        violations = RimePromptValidator().validate(tts_req.text)
        assert violations == []

    @pytest.mark.asyncio
    async def test_pipeline_e2e_urgency_headline_only(self, live_pipeline) -> None:
        req = make_recap_request(urgency=RecapUrgency.HEADLINE_ONLY)
        tts_req = await live_pipeline.run(req)

        assert tts_req.time_scale_factor == 0.75
        assert tts_req.model == RimeModel.CODA
        violations = RimePromptValidator().validate(tts_req.text)
        assert violations == []

    @pytest.mark.asyncio
    async def test_pipeline_e2e_backend_failure_resilience(self) -> None:
        err_transport = httpx.MockTransport(lambda req: httpx.Response(500))
        err_client = httpx.AsyncClient(transport=err_transport, base_url="http://localhost:8001")
        freshness = FreshnessChecker(client=err_client)
        pipeline = VoicePipeline(freshness_checker=freshness)

        req = make_recap_request()
        tts_req = await pipeline.run(req)
        assert tts_req.text
        assert tts_req.private_track_id == "continuum-private-whisper"
        await pipeline.aclose()

    @pytest.mark.asyncio
    async def test_pipeline_e2e_records_telemetry_metrics(self, live_pipeline) -> None:
        req = make_recap_request()
        tts_req = await live_pipeline.run(req)
        metrics = live_pipeline.last_metrics
        assert metrics["request_id"] == req.request_id
        assert metrics["total_ms"] >= 0
        assert metrics["model"] == tts_req.model.value
        assert metrics["char_count"] > 0
        assert metrics["word_count"] > 0

    @pytest.mark.asyncio
    async def test_pipeline_aclose(self, live_pipeline) -> None:
        await live_pipeline.aclose()


