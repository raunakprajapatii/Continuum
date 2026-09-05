"""
mocks/enterprise/service.py
----------------------------
Facade over the Meridian enterprise database (``mocks/enterprise/db.py``).

All product state — prices, stock, price history — lives in SQLite, so the
freshness checker genuinely reads from the enterprise database.  This module
adds the freshness fact-key contract on top:

  * ``price_<sku>`` keys (e.g. ``price_bas112``) resolve to the product's
    current price in the database.
  * Legacy generic keys (``price_usd`` / ``ticket_status``) resolve from the
    in-memory legacy store kept for the original evaluation fixtures.

Importable programmatically:
    from mocks.enterprise.service import (
        get_fact_value, set_fact_value, list_products, get_product,
        set_product_price, market_tick, reset_enterprise, get_history,
    )
"""

from __future__ import annotations

from . import catalog, db

#: Legacy generic facts (original evaluation fixtures) — not enterprise products.
_LEGACY_STORE: dict[str, str] = {
    "price_usd": "$420",       # was $400 in the mock thread → triggers CHANGED
    "ticket_status": "closed",  # hypothetical second fact for context-fencing test
}


# ── Product operations (delegated to the database) ────────────────────────────


def list_products() -> list[dict]:
    """Current product rows (with live prices) from the database."""
    return db.list_products()


def get_product(sku: str) -> dict | None:
    """Current product row by SKU from the database, or None."""
    return db.get_product(sku)


def set_product_price(sku: str, price: str) -> dict | None:
    """Set a product's live price in the database (records history)."""
    return db.set_product_price(sku, price)


def market_tick() -> list[dict]:
    """Apply the next deterministic overnight market move (persisted)."""
    return db.market_tick()


def reset_enterprise() -> list[dict]:
    """Restore baseline prices in the database and clear the history."""
    return db.reset_enterprise()


def get_history() -> list[dict]:
    """Recent price movements (newest first) from the database."""
    return db.get_history()


def company_payload() -> dict:
    """Company info + catalog snapshot for ``GET /api/enterprise``."""
    return {
        **catalog.COMPANY,
        "database": f"sqlite://{db.path()}",
        "products": list_products(),
        "updated_at": db.now_iso(),
    }


# ── Fact-value operations (freshness-checker contract) ────────────────────────


def get_fact_value(key: str) -> str | None:
    """
    Resolve a freshness fact key to its current value.

    Product price keys (``price_bas112``) resolve through the enterprise
    database; generic keys (``price_usd``, ``ticket_status``) resolve through
    the legacy store.  Unknown keys return None (→ UNAVAILABLE).
    """
    sku = catalog.sku_for_fact_key(key)
    if sku is not None:
        product = db.get_product(sku)
        if product is not None:
            return product["current_price"]
    return _LEGACY_STORE.get(key)


def set_fact_value(key: str, value: str) -> None:
    """
    Update a live fact value.

    Product price keys update the enterprise database (and record history);
    generic keys update the legacy store.  Used by tests and the demo console.
    """
    sku = catalog.sku_for_fact_key(key)
    if sku is not None:
        db.set_product_price(sku, value)
    else:
        _LEGACY_STORE[key] = value