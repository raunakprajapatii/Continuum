"""
mocks/enterprise/router.py
--------------------------
FastAPI router for the Meridian enterprise pricing API.

Mounted into the mock freshness service (``mocks/mock_freshness.py``) so one
process on port 8001 serves both the legacy ``/facts/{key}`` contract (used by
the Fact-Freshness Checker and the evaluation fixtures) and the full enterprise
console + API used to *demonstrate* the freshness feature:

    GET  /                           → the presentation console (console.html)
    GET  /api/enterprise             → company info + live product catalog
    GET  /api/enterprise/products    → product list (live prices)
    GET  /api/enterprise/products/{sku}
    POST /api/enterprise/products/{sku}/price   {"price": "$955"}
    POST /api/enterprise/market-tick            → simulate an overnight move
    POST /api/enterprise/reset                  → restore baseline prices
    GET  /facts/{key}  ·  POST /facts/{key}     → freshness-checker contract
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import service

# console.html lives next to this module.
_CONSOLE_HTML = Path(__file__).parent / "console.html"

router = APIRouter()


class PriceUpdate(BaseModel):
    price: str


class FactUpdate(BaseModel):
    value: str


# ── Console ────────────────────────────────────────────────────────────────────


@router.get("/", response_class=FileResponse, include_in_schema=False)
async def console() -> FileResponse:
    """Serve the enterprise pricing console (the demo presentation surface)."""
    return FileResponse(_CONSOLE_HTML, media_type="text/html")


# ── Enterprise API ─────────────────────────────────────────────────────────────


@router.get("/api/enterprise", response_class=JSONResponse)
async def enterprise_overview() -> dict[str, Any]:
    """Company info + full live product catalog."""
    return service.company_payload()


@router.get("/api/enterprise/products", response_class=JSONResponse)
async def list_products() -> dict[str, Any]:
    return {"products": service.list_products()}


@router.get("/api/enterprise/products/{sku}", response_class=JSONResponse)
async def get_product(sku: str) -> dict[str, Any]:
    product = service.get_product(sku)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Unknown SKU: {sku!r}")
    return product


@router.post("/api/enterprise/products/{sku}/price", response_class=JSONResponse)
async def update_price(sku: str, body: PriceUpdate) -> dict[str, Any]:
    """Set a product's live price — simulate a rate revision mid-demo."""
    product = service.set_product_price(sku, body.price)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Unknown SKU: {sku!r}")
    return {"ok": True, "product": product}


@router.post("/api/enterprise/market-tick", response_class=JSONResponse)
async def market_tick() -> dict[str, Any]:
    """
    Advance the market: a couple of products move overnight.

    Run this between call one and the callback to make the freshness check
    find a CHANGED fact.
    """
    moved = service.market_tick()
    return {"ok": True, "moved": moved, "count": len(moved)}


@router.post("/api/enterprise/reset", response_class=JSONResponse)
async def reset_enterprise() -> dict[str, Any]:
    """Restore all baseline prices (fresh take)."""
    products = service.reset_enterprise()
    return {"ok": True, "products": products}


@router.get("/api/enterprise/history", response_class=JSONResponse)
async def history() -> dict[str, Any]:
    """Recent price movements for the console live feed."""
    return {"history": service.get_history()}


# ── Legacy freshness-checker contract ─────────────────────────────────────────


@router.get("/facts/{key}", response_class=JSONResponse)
async def read_fact(key: str) -> dict[str, Any]:
    """Return the current live value for a fact key (freshness checker)."""
    from datetime import datetime, timezone

    value = service.get_fact_value(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Unknown fact key: {key!r}")
    return {
        "key": key,
        "value": value,
        "retrieved_at": datetime.now(tz=timezone.utc).isoformat(),
        "latency_ms": 12,  # simulated fast response
    }


@router.post("/facts/{key}", response_class=JSONResponse)
async def update_fact(key: str, body: FactUpdate) -> dict[str, Any]:
    """Update a live fact value (evaluation harness / console)."""
    from datetime import datetime, timezone

    service.set_fact_value(key, body.value)
    return {
        "key": key,
        "value": service.get_fact_value(key),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }