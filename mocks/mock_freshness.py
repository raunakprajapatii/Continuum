"""
mocks/mock_freshness.py
------------------------
Pair D (Voice & Facts) mock freshness data source — used by the
Fact-Freshness Checker during development.

This is a tiny FastAPI service that exposes the "live" data endpoints the
freshness checker queries.  It now hosts the full **Meridian enterprise
pricing feed** (see ``mocks/enterprise/``): every product price is a freshness
fact, and a presentation console at ``http://localhost:8001/`` lets you
simulate overnight market moves to demonstrate Scenario C (stale fact caught
and flagged in the recap).

Run as a standalone process:
    python -m mocks.mock_freshness

Then query:
    GET  http://localhost:8001/                      → enterprise console
    GET  http://localhost:8001/api/enterprise        → company + product catalog
    POST http://localhost:8001/api/enterprise/market-tick
    GET  http://localhost:8001/facts/{key}           → freshness contract
    POST http://localhost:8001/facts/{key}  {"value": "420"}

Also importable for programmatic use in tests:
    from mocks.mock_freshness import get_fact_value, set_fact_value
"""

from __future__ import annotations

import json
from typing import Any

# The enterprise service owns all fact state (product price keys + legacy keys).
# ``_FACT_STORE`` is re-exported for the original evaluation fixtures that
# snapshot the legacy generic-fact store.
from mocks.enterprise.service import (
    _LEGACY_STORE as _FACT_STORE,
    get_fact_value,
    set_fact_value,
)

__all__ = ["get_fact_value", "set_fact_value", "_FACT_STORE", "app"]


# ── FastAPI service ────────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from mocks.enterprise.router import router as _enterprise_router

    app: Any = FastAPI(
        title="Continuum Enterprise Freshness API",
        description=(
            "Meridian Commodities & Exports live price feed — the enterprise "
            "data source the Fact-Freshness Checker re-verifies facts against. "
            "Modify prices at runtime to demonstrate Scenario C (stale fact catch)."
        ),
        version="1.0.0",
    )
    app.include_router(_enterprise_router)

    @app.get("/health", response_class=JSONResponse)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "enterprise-freshness-api"}

except ImportError:
    from datetime import datetime, timezone

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        """
        Minimal ASGI fallback for test environments without FastAPI.

        This preserves the mock freshness contract used by httpx.ASGITransport:
        GET /facts/{key}, POST /facts/{key}, and GET /health.
        """
        if scope["type"] != "http":
            raise RuntimeError("mock_freshness fallback only supports HTTP scopes")

        method = scope["method"]
        path = scope["path"]

        status = 404
        payload: dict[str, Any] = {"detail": f"Unknown route: {method} {path}"}

        if method == "GET" and path == "/health":
            status = 200
            payload = {"status": "ok", "service": "enterprise-freshness-api"}
        elif path.startswith("/facts/"):
            key = path.removeprefix("/facts/")
            if method == "GET":
                value = get_fact_value(key)
                if value is None:
                    status = 404
                    payload = {"detail": f"Unknown fact key: {key!r}"}
                else:
                    status = 200
                    payload = {
                        "key": key,
                        "value": value,
                        "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
                        "latency_ms": 12,
                    }
            elif method == "POST":
                body = b""
                more_body = True
                while more_body:
                    event = await receive()
                    body += event.get("body", b"")
                    more_body = event.get("more_body", False)

                try:
                    value = json.loads(body.decode("utf-8"))["value"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    status = 422
                    payload = {"detail": "Body must be JSON with a string value field"}
                else:
                    set_fact_value(key, str(value))
                    status = 200
                    payload = {
                        "key": key,
                        "value": get_fact_value(key),
                        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                    }

        body_bytes = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mocks.mock_freshness:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )