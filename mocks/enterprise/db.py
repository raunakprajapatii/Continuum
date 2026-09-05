"""
mocks/enterprise/db.py
-----------------------
SQLite persistence for the Meridian enterprise catalog.

This is the "database containing info about the enterprise": product rows and
price history live in a real SQLite file (``enterprise.db`` by default, or
``ENTERPRISE_DB_PATH``), so live prices survive restarts and the freshness
checker genuinely reads from a database rather than throwaway memory.

Schema
------
    products(sku PK, name, category, unit, base_price, current_price,
             stock, min_qty, status, price_note, last_updated)
    price_history(id PK AUTOINCREMENT, sku, name, from_price, to_price,
                  via, at)

The table is seeded from ``catalog.PRODUCTS`` on first init.  ``catalog.py``
remains the pristine definition; the database is the runtime state.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import catalog

#: SQLite file path (repo-root relative by default). Override with
#: ENTERPRISE_DB_PATH, e.g. ":memory:" for tests.
_DB_PATH = os.getenv("ENTERPRISE_DB_PATH", "enterprise.db")

_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku            TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    unit           TEXT NOT NULL,
    base_price     TEXT NOT NULL,
    current_price  TEXT NOT NULL,
    stock          INTEGER NOT NULL,
    min_qty        INTEGER NOT NULL,
    status         TEXT NOT NULL,
    price_note     TEXT NOT NULL,
    last_updated   TEXT
);
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL,
    name        TEXT NOT NULL,
    from_price  TEXT NOT NULL,
    to_price    TEXT NOT NULL,
    via         TEXT NOT NULL,
    at          TEXT NOT NULL
);
"""

# Module-level connection (single-threaded demo usage; sqlite3 is fine).
_db: sqlite3.Connection | None = None


def now_iso() -> str:
    """Current UTC timestamp in the history-feed format."""
    return datetime.now(tz=timezone.utc).strftime(_TIMESTAMP_FMT)


def path() -> str:
    """The SQLite database file path (or ':memory:')."""
    return _DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return the module-level SQLite connection, initialised + seeded."""
    global _db
    if _db is None:
        _db = sqlite3.connect(_DB_PATH)
        _db.row_factory = sqlite3.Row
        _db.executescript(_SCHEMA)
        _seed_if_empty()
    return _db


def _seed_if_empty() -> None:
    """Seed the products table from catalog.PRODUCTS on first boot."""
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count > 0:
        return
    conn.executemany(
        """
        INSERT INTO products
            (sku, name, category, unit, base_price, current_price,
             stock, min_qty, status, price_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                p["sku"],
                p["name"],
                p["category"],
                p["unit"],
                p["base_price"],
                p["current_price"],
                p["stock"],
                p["min_qty"],
                p["status"],
                p["price_note"],
            )
            for p in catalog.PRODUCTS
        ],
    )
    conn.commit()


# ── Price helpers ──────────────────────────────────────────────────────────────


def parse_price(price: str) -> int | None:
    """'$1,275' / '1275' / '955 USD' → 1275 (integer dollars), or None."""
    raw = (price or "").strip()
    if raw.startswith(("$", "€", "£")):
        raw = raw[1:]
    raw = raw.split()[0] if raw else ""
    try:
        return int(raw.replace(",", ""))
    except ValueError:
        return None


def format_price(dollars: int) -> str:
    """1275 → '$1,275'."""
    return f"${dollars:,}"


def _record_history(sku: str, name: str, from_price: str, to_price: str, via: str) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO price_history (sku, name, from_price, to_price, via, at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (sku, name, from_price, to_price, via, now_iso()),
    )
    conn.commit()


# ── Product operations (runtime state lives here) ──────────────────────────────


def list_products() -> list[dict]:
    """All product rows with live prices, in catalog order."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM products ORDER BY rowid"
    ).fetchall()
    return [dict(row) for row in rows]


def get_product(sku: str) -> dict | None:
    """One product row by SKU (case-insensitive), or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM products WHERE UPPER(sku) = ?", (sku.upper(),)
    ).fetchone()
    return dict(row) if row else None


def set_product_price(sku: str, price: str) -> dict | None:
    """
    Set a product's live price, persist it, and record the change.

    Accepts ``"$955"``, ``"955"`` or ``"955 USD"`` — normalised to the
    ``$N,NNN`` display form.  Returns the updated row, or None for an unknown
    SKU / unparseable price.
    """
    dollars = parse_price(price)
    if dollars is None:
        return None
    product = get_product(sku)
    if product is None:
        return None
    new_price = format_price(dollars)
    if new_price == product["current_price"]:
        return product
    old_price = product["current_price"]
    conn = get_connection()
    conn.execute(
        "UPDATE products SET current_price = ?, last_updated = ? WHERE sku = ?",
        (new_price, now_iso(), product["sku"]),
    )
    conn.commit()
    _record_history(product["sku"], product["name"], old_price, new_price, "manual-edit")
    return get_product(sku)


#: Deterministic overnight market-move deltas (applied in rotation).
_MARKET_MOVES: list[dict] = [
    {"sku": "BAS112", "delta": +15},   # Basmati rice +$15
    {"sku": "WHT450", "delta": +8},    # Wheat +$8
    {"sku": "CPR300", "delta": +120},  # Copper cathode +$120 (LME-linked)
    {"sku": "COT101", "delta": -25},   # Cotton −$25
    {"sku": "STLHRC", "delta": +18},   # HR steel coil +$18
    {"sku": "SLN005", "delta": -12},   # Soya bean meal −$12
    {"sku": "SPR012", "delta": +10},   # Refined sugar +$10
    {"sku": "CRN220", "delta": -7},    # Yellow maize −$7
]
_MOVE_IDX = 0


def market_tick() -> list[dict]:
    """
    Apply the next deterministic "overnight market move" — two products move
    per tick, advancing a rotation so repeated ticks keep producing fresh
    changes.  Persists the moves and returns the changed product rows.
    """
    global _MOVE_IDX
    conn = get_connection()
    moved: list[dict] = []
    for _ in range(2):  # two products move per tick
        move = _MARKET_MOVES[_MOVE_IDX % len(_MARKET_MOVES)]
        _MOVE_IDX += 1
        product = get_product(move["sku"])
        if product is None:
            continue
        dollars = parse_price(product["current_price"])
        if dollars is None:
            continue
        new_price = format_price(max(1, dollars + move["delta"]))
        if new_price == product["current_price"]:
            continue
        conn.execute(
            "UPDATE products SET current_price = ?, last_updated = ? WHERE sku = ?",
            (new_price, now_iso(), product["sku"]),
        )
        _record_history(product["sku"], product["name"], product["current_price"], new_price, "market-tick")
        moved.append(get_product(product["sku"]))
    conn.commit()
    return moved


def reset_enterprise() -> list[dict]:
    """
    Restore every product to its catalog baseline price and clear the price
    history.  Re-seeds rows that may be missing from the schema's baseline.
    """
    conn = get_connection()
    for product in catalog.PRODUCTS:
        conn.execute(
            """
            INSERT INTO products
                (sku, name, category, unit, base_price, current_price,
                 stock, min_qty, status, price_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                unit = excluded.unit,
                base_price = excluded.base_price,
                current_price = excluded.base_price,
                stock = excluded.stock,
                min_qty = excluded.min_qty,
                status = excluded.status,
                price_note = excluded.price_note,
                last_updated = NULL
            """,
            (
                product["sku"],
                product["name"],
                product["category"],
                product["unit"],
                product["base_price"],
                product["base_price"],
                product["stock"],
                product["min_qty"],
                product["status"],
                product["price_note"],
            ),
        )
    conn.execute("DELETE FROM price_history")
    conn.commit()
    global _MOVE_IDX
    _MOVE_IDX = 0
    return list_products()


def get_history() -> list[dict]:
    """Recent price movements, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT sku, name, from_price, to_price, via, at "
        "FROM price_history ORDER BY id DESC LIMIT 50"
    ).fetchall()
    return [dict(row) for row in rows]


def close_connection() -> None:
    """Close the module-level connection (used by tests / shutdown)."""
    global _db
    if _db is not None:
        _db.close()
        _db = None