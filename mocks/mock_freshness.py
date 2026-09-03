"""
mocks/mock_freshness.py
------------------------
Pair D (Voice & Facts) mock freshness data source — used by the
Fact-Freshness Checker during development.

This is a tiny FastAPI service that exposes a mock "live data" endpoint
for the price_usd fact. The value can be toggled at runtime so the
evaluation harness can deterministically demonstrate Scenario C
(stale fact caught and flagged in the recap).

Run as a standalone process:
    python -m mocks.mock_freshness

Then query:
    GET http://localhost:8001/facts/{key}
    POST http://localhost:8001/facts/{key}  {"value": "420"}

Also importable for programmatic use in tests:
    from mocks.mock_freshness import get_fact_value, set_fact_value
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

# ── In-memory store ────────────────────────────────────────────────────────────

# The "live" data the mock API serves. Keys match TimeSensitiveFact.key values.
# This is intentionally different from the $400 in the mock thread summary
# to demonstrate the freshness-catch acceptance test.
_FACT_STORE: dict[str, str] = {
    "price_usd": "$420",       # was $400 in the thread → triggers CHANGED
    "ticket_status": "closed", # hypothetical second fact for context-fencing test
}


def get_fact_value(key: str) -> str | None:
    """Return the current 'live' value for a fact key, or None if unknown."""
    return _FACT_STORE.get(key)


def set_fact_value(key: str, value: str) -> None:
    """
    Update the live value for a fact key.

    Use this in the evaluation harness to change a value between calls
    and verify the freshness check catches it.
    """
    _FACT_STORE[key] = value


# ── FastAPI service ────────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel as _BaseModel

    app = FastAPI(
        title="Continuum Mock Freshness API",
        description=(
            "Deterministic mock data source for the Fact-Freshness Checker. "
            "Modify fact values at runtime to demonstrate Scenario C (stale fact catch)."
        ),
        version="0.1.0",
    )

    class _FactUpdate(_BaseModel):
        value: str

    @app.get("/facts/{key}", response_class=JSONResponse)
    async def read_fact(key: str) -> dict[str, Any]:
        """Return the current live value for a fact key."""
        value = get_fact_value(key)
        if value is None:
            raise HTTPException(status_code=404, detail=f"Unknown fact key: {key!r}")
        return {
            "key": key,
            "value": value,
            "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
            "latency_ms": 12,  # simulated fast response
        }

    @app.post("/facts/{key}", response_class=JSONResponse)
    async def update_fact(key: str, body: _FactUpdate) -> dict[str, Any]:
        """
        Update the live value for a fact key.

        Used by the evaluation harness to inject a changed fact between calls.
        """
        set_fact_value(key, body.value)
        return {
            "key": key,
            "value": body.value,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "mock-freshness-api"}

except ImportError:
    # FastAPI not installed — that's fine for schema-only usage in tests
    app = None  # type: ignore[assignment]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mocks.mock_freshness:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
