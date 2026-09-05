"""
modules/voice/freshness_checker.py
------------------------------------
Pair D — Fact-Freshness Checker

Consumes the ``facts_to_verify`` list in a ``RecapRequest`` and produces a
``FreshnessResult`` by querying the enterprise data source (``mocks/``
Meridian pricing feed, port 8001) in both mock and live mode:

  * The FastAPI service at ``settings.mock_freshness_api_url`` serves both the
    product price facts (``price_<sku>``) and the legacy generic facts
    (``price_usd``, ``ticket_status``).
  * It is the stand-in "live" API — run it as
    ``python -m mocks.mock_freshness``.

Each fact is checked independently with a per-request timeout.  Network errors
and timeouts yield ``FreshnessStatus.UNAVAILABLE`` — the checker never raises;
it always returns a complete ``FreshnessResult`` so the pipeline can continue.

Usage::

    from modules.voice.freshness_checker import FreshnessChecker
    from mocks.mock_brain import make_recap_request

    checker = FreshnessChecker()
    result  = await checker.check(make_recap_request())
    print(result.any_changed)       # True in Scenario C
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from shared.config import settings
from shared.schemas import (
    FactCheckResult,
    FreshnessResult,
    FreshnessStatus,
    RecapRequest,
    TimeSensitiveFact,
)

logger = logging.getLogger(__name__)

# How long to wait for a single fact lookup before giving UNAVAILABLE.
_TIMEOUT_SECONDS: float = 3.0


class FreshnessChecker:
    """
    Re-verifies ``TimeSensitiveFact`` values before the recap is spoken.

    Instantiate once and reuse — the underlying ``httpx.AsyncClient`` is
    created lazily and shared across calls.
    """

    def __init__(
        self,
        timeout: float = _TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = client

    # ── Public API ─────────────────────────────────────────────────────────────

    async def check(self, recap_request: RecapRequest) -> FreshnessResult:
        """
        Check all ``facts_to_verify`` in *recap_request* and return a
        ``FreshnessResult``.

        Always returns — never raises.  Individual lookup failures are captured
        as ``FreshnessStatus.UNAVAILABLE`` entries in the result.
        """
        client = await self._get_client()

        tasks = [
            self._check_one(client, fact)
            for fact in recap_request.facts_to_verify
        ]
        results: list[FactCheckResult] = await asyncio.gather(*tasks)

        any_changed = any(r.status == FreshnessStatus.CHANGED for r in results)

        freshness_result = FreshnessResult(
            request_id=recap_request.request_id,
            thread_id=recap_request.thread_id,
            results=results,
            any_changed=any_changed,
            completed_at=datetime.now(tz=timezone.utc),
        )

        if any_changed:
            changed = [r for r in results if r.status == FreshnessStatus.CHANGED]
            logger.info(
                "freshness_checker: %d fact(s) changed for request_id=%s — %s",
                len(changed),
                recap_request.request_id,
                [r.key for r in changed],
            )
        else:
            logger.debug(
                "freshness_checker: all facts unchanged for request_id=%s",
                recap_request.request_id,
            )

        return freshness_result

    async def aclose(self) -> None:
        """Close the underlying HTTP client.  Call when shutting down."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Internals ──────────────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _check_one(
        self,
        client: httpx.AsyncClient,
        fact: TimeSensitiveFact,
    ) -> FactCheckResult:
        """
        Check a single fact.  Returns a ``FactCheckResult`` regardless of
        network outcome.
        """
        start_ms = int(time.monotonic() * 1000)

        try:
            live_value, latency_ms = await self._fetch_live_value(client, fact.key)
        except Exception as exc:
            latency_ms = int(time.monotonic() * 1000) - start_ms
            logger.warning(
                "freshness_checker: lookup failed for key=%r: %s", fact.key, exc
            )
            return FactCheckResult(
                key=fact.key,
                label=fact.label,
                cached_value=fact.value,
                live_value=None,
                status=FreshnessStatus.UNAVAILABLE,
                checked_at=datetime.now(tz=timezone.utc),
                latency_ms=latency_ms,
            )

        status = (
            FreshnessStatus.CHANGED
            if live_value != fact.value
            else FreshnessStatus.UNCHANGED
        )

        return FactCheckResult(
            key=fact.key,
            label=fact.label,
            cached_value=fact.value,
            live_value=live_value,
            status=status,
            checked_at=datetime.now(tz=timezone.utc),
            latency_ms=latency_ms,
        )

    async def _fetch_live_value(
        self,
        client: httpx.AsyncClient,
        key: str,
    ) -> tuple[str, int]:
        """
        Return ``(live_value, latency_ms)``.

        Routing — both modes query the enterprise data source at
        ``settings.mock_freshness_api_url`` (port 8001).  In this demo the
        Meridian enterprise pricing feed (``mocks/enterprise/``) IS the live
        stand-in for a real vendor API: product price keys (``price_<sku>``)
        resolve to catalog prices, and legacy keys (``price_usd``,
        ``ticket_status``) resolve from the generic store.  To point at a real
        external API later, swap the base URL / key mapping here.

        Raises ``httpx.HTTPError`` or ``httpx.TimeoutException`` on failure —
        callers must catch.
        """
        base_url = settings.mock_freshness_api_url
        url = f"{base_url}/facts/{key}"
        t0 = time.monotonic()
        response = await client.get(url)
        latency_ms = int((time.monotonic() - t0) * 1000)
        response.raise_for_status()

        data = response.json()
        live_value: str = data["value"]
        return live_value, latency_ms
