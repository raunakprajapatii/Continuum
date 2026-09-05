"""
tests/test_enterprise_freshness.py
-----------------------------------
Tests for the Meridian enterprise freshness flow:

  * the heuristic extractor keys product prices as ``price_<sku>`` facts
  * the enterprise service resolves those keys to live catalog prices
  * market ticks change prices so the freshness check flags them
  * the FastAPI surface (console + /api/enterprise + /facts/{key}) works
  * the legacy generic facts (price_usd / ticket_status) keep working

Everything runs against real modules + the mock ASGI app — no external APIs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast

import httpx
import pytest

from mocks.enterprise import catalog, service
from mocks.enterprise.service import (
    get_fact_value,
    list_products,
    market_tick,
    reset_enterprise,
    set_product_price,
)
from mocks.mock_freshness import app as freshness_asgi_app
from modules.brain.extractor import ConversationExtractor
from shared.schemas import (
    FreshnessStatus,
    RecapRequest,
    RecapUrgency,
    Speaker,
    ThreadSummary,
    TimeSensitiveFact,
    TranscriptEvent,
)


@pytest.fixture(autouse=True)
def _clean_enterprise_state():
    """Restore baseline prices + legacy facts before every test (module state is global)."""
    reset_enterprise()
    service.set_fact_value("price_usd", "$420")
    service.set_fact_value("ticket_status", "closed")
    yield


@pytest.fixture
def extractor() -> ConversationExtractor:
    """Heuristic extractor (no Gemini key)."""
    return ConversationExtractor(api_key=None)


def _turn(text: str, speaker: Speaker = Speaker.CALLER) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=str(uuid.uuid4()),
        session_id="sess-ent-01",
        speaker=speaker,
        text=text,
        start_ms=0,
        end_ms=2000,
        is_final=True,
        confidence=0.98,
        timestamp=datetime.now(tz=timezone.utc),
    )


# ── Extractor: product prices → price_<sku> facts ─────────────────────────────


class TestEnterpriseExtraction:
    async def test_basmati_price_maps_to_sku_key(self, extractor: ConversationExtractor):
        summary = await extractor.extract(
            [_turn("Basmati rice is $940 per tonne, FOB Mumbai.")],
            caller_id="+14155550199",
        )
        keys = {f.key: f.value for f in summary.time_sensitive_facts}
        assert keys.get("price_bas112") == "$940"

    async def test_multiple_products_become_separate_facts(self, extractor: ConversationExtractor):
        summary = await extractor.extract(
            [_turn("Basmati rice is $950 and wheat is $320 per tonne.")],
            caller_id="+14155550199",
        )
        keys = {f.key: f.value for f in summary.time_sensitive_facts}
        assert keys.get("price_bas112") == "$950"
        assert keys.get("price_wht450") == "$320"

    async def test_spoken_dollar_price_pairs_with_product(self, extractor: ConversationExtractor):
        """'940 dollars' (no $ sign) still pairs with the product and normalises."""
        summary = await extractor.extract(
            [_turn("Basmati rice is 940 dollars per tonne, FOB Mumbai.")],
            caller_id="+14155550199",
        )
        keys = {f.key: f.value for f in summary.time_sensitive_facts}
        assert keys.get("price_bas112") == "$940"

    async def test_generic_price_still_uses_price_usd(self, extractor: ConversationExtractor):
        """No product name → legacy generic price_usd fact (existing behaviour)."""
        summary = await extractor.extract(
            [_turn("The unit price is $400.")],
            caller_id="+14155550199",
        )
        keys = {f.key for f in summary.time_sensitive_facts}
        assert "price_usd" in keys

    async def test_spoken_dollars_normalised_to_symbol(self, extractor: ConversationExtractor):
        """'940 dollars' is stored as '$940' so freshness equality holds."""
        summary = await extractor.extract(
            [_turn("The unit price is 940 dollars.")],
            caller_id="+14155550199",
        )
        keys = {f.key: f.value for f in summary.time_sensitive_facts}
        assert keys.get("price_usd") == "$940"

    def test_price_value_normalisation(self):
        """Gemini may return '$940 per tonne' — must normalise to '$940'."""
        from modules.brain.extractor import _normalize_price_value

        assert _normalize_price_value("$940") == "$940"
        assert _normalize_price_value("$940 per tonne") == "$940"
        assert _normalize_price_value("$8,940 LME-linked") == "$8,940"
        assert _normalize_price_value("940 dollars") == "$940"
        assert _normalize_price_value("1,275 US dollars") == "$1,275"
        assert _normalize_price_value("Tomorrow at 9:00 AM") == "Tomorrow at 9:00 AM"

    def test_catalog_aliases_index_complete(self):
        """Every product has at least one alias and a resolvable fact key."""
        assert len(catalog.PRODUCTS) >= 5
        for product in catalog.PRODUCTS:
            assert catalog.get_product(product["sku"]) is not None
            assert catalog.sku_for_fact_key(
                catalog.fact_key_for_product(product["sku"])
            ) == product["sku"]


# ── Enterprise service: live prices, ticks, fact keys ─────────────────────────


class TestEnterpriseService:
    def test_fact_key_resolves_to_live_price(self):
        assert get_fact_value("price_bas112") == "$940"

    def test_unknown_fact_key_returns_none(self):
        assert get_fact_value("price_nope99") is None

    def test_legacy_facts_still_served(self):
        assert get_fact_value("price_usd") == "$420"
        assert get_fact_value("ticket_status") == "closed"

    def test_set_product_price_records_and_normalises(self):
        updated = set_product_price("BAS112", "$955")
        assert updated is not None
        assert updated["current_price"] == "$955"
        assert get_fact_value("price_bas112") == "$955"
        assert service.get_history()[0]["sku"] == "BAS112"

    def test_set_product_price_accepts_bare_number(self):
        updated = set_product_price("WHT450", "328")
        assert updated["current_price"] == "$328"

    def test_unknown_sku_returns_none(self):
        assert set_product_price("NOPE99", "$999") is None

    def test_market_tick_moves_prices_deterministically(self):
        before = {p["sku"]: p["current_price"] for p in list_products()}
        moved = market_tick()
        assert moved, "market tick should move at least one product"
        for product in moved:
            assert before[product["sku"]] != product["current_price"]

    def test_reset_restores_baseline(self):
        set_product_price("BAS112", "$999")
        assert get_fact_value("price_bas112") == "$999"
        reset_enterprise()
        assert get_fact_value("price_bas112") == "$940"


# ── Freshness check end to end (ASGI) ─────────────────────────────────────────


class TestEnterpriseFreshnessCheck:
    @pytest.fixture
    def http_client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=cast(Any, freshness_asgi_app))
        return httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")

    async def test_enterprise_overview_returns_catalog(self, http_client: httpx.AsyncClient):
        response = await http_client.get("/api/enterprise")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Meridian Commodities & Exports"
        assert len(data["products"]) == len(catalog.PRODUCTS)

    async def test_console_page_served(self, http_client: httpx.AsyncClient):
        response = await http_client.get("/")
        assert response.status_code == 200
        assert "Meridian Commodities" in response.text

    async def test_facts_contract_for_product_key(self, http_client: httpx.AsyncClient):
        response = await http_client.get("/facts/price_bas112")
        assert response.status_code == 200
        assert response.json()["value"] == "$940"

    async def test_freshness_catches_overnight_tick(self, http_client: httpx.AsyncClient):
        """Thread says $940; market tick moves BAS112 to $955 → CHANGED."""
        from modules.voice.freshness_checker import FreshnessChecker

        summary = ThreadSummary(
            thread_id="thread-ent-01",
            caller_id="+14155550199",
            caller_name="Z",
            headline="Z wanted the Basmati quote.",
            time_sensitive_facts=[
                TimeSensitiveFact(
                    key="price_bas112",
                    label="Basmati Rice 1121 price",
                    value="$940",
                    recorded_at=datetime.now(tz=timezone.utc),
                )
            ],
            created_at=datetime.now(tz=timezone.utc),
            last_updated_at=datetime.now(tz=timezone.utc),
        )
        request = RecapRequest(
            request_id=str(uuid.uuid4()),
            session_id="sess-ent-cb",
            thread_id=summary.thread_id,
            summary=summary,
            facts_to_verify=list(summary.time_sensitive_facts),
            urgency=RecapUrgency.EXTENDED,
            estimated_ring_window_seconds=25.0,
            created_at=datetime.now(tz=timezone.utc),
        )

        # no tick yet → unchanged
        checker = FreshnessChecker(client=http_client)
        result = await checker.check(request)
        assert result.any_changed is False
        assert result.results[0].status == FreshnessStatus.UNCHANGED

        # overnight market move → CHANGED with both values
        market_tick()
        result = await checker.check(request)
        assert result.any_changed is True
        check = result.results[0]
        assert check.key == "price_bas112"
        assert check.cached_value == "$940"
        assert check.live_value != "$940"
        assert check.status == FreshnessStatus.CHANGED
        await checker.aclose()

    async def test_unknown_key_reports_unavailable(self, http_client: httpx.AsyncClient):
        from modules.voice.freshness_checker import FreshnessChecker

        fact = TimeSensitiveFact(
            key="price_mystery",
            label="Mystery price",
            value="$100",
            recorded_at=datetime.now(tz=timezone.utc),
        )
        request = RecapRequest(
            request_id=str(uuid.uuid4()),
            session_id="sess-ent-02",
            thread_id="thread-ent-02",
            summary=ThreadSummary(
                thread_id="thread-ent-02",
                caller_id="+14155550199",
                headline="Z called.",
                time_sensitive_facts=[fact],
                created_at=datetime.now(tz=timezone.utc),
                last_updated_at=datetime.now(tz=timezone.utc),
            ),
            facts_to_verify=[fact],
            urgency=RecapUrgency.STANDARD,
            estimated_ring_window_seconds=15.0,
            created_at=datetime.now(tz=timezone.utc),
        )
        checker = FreshnessChecker(client=http_client)
        result = await checker.check(request)
        assert result.results[0].status == FreshnessStatus.UNAVAILABLE
        await checker.aclose()