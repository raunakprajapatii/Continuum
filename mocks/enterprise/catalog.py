"""
mocks/enterprise/catalog.py
----------------------------
The Continuum enterprise data source — a simulated B2B commodities trading
company whose product prices are the "live" facts the Fact-Freshness Checker
re-verifies before a recap is spoken.

This module is pure data + lookup helpers (no I/O, no FastAPI).  The runtime
state lives in ``service.py``; the HTTP surface lives in ``router.py``; the
human-facing console is ``console.html``; and the role-play brief is
``ENTERPRISE_BRIEF.md``.

Fact-key contract
-----------------
Every product exposes a *price fact* keyed ``price_<sku_lower>`` (e.g.
``price_bas112`` for Basmati Rice 1121).  The ConversationExtractor keys any
product price mentioned in the call with the matching ``price_<sku>`` key, and
the enterprise service resolves those keys in ``GET /facts/{key}`` — so a
price spoken in call one and changed overnight is flagged by the freshness
check in the callback recap.

The legacy generic keys (``price_usd``, ``ticket_status``) are kept for the
original evaluation fixtures and are served from the same service.
"""

from __future__ import annotations

# ── Company ────────────────────────────────────────────────────────────────────

COMPANY: dict = {
    "name": "Meridian Commodities & Exports",
    "short_name": "Meridian",
    "tagline": "Global B2B trading — agri, metals & textiles",
    "currency": "USD",
    "market_note": "FOB Mumbai · prices refreshed from the exchange feed",
    "buyer_contact": "Zara Mitchell · Procurement, Horizon Foods Intl.",
    "sales_rep": "You — Regional Sales Manager",
    "timezone": "IST",
    "exchange": "Meridian Live Price Feed (simulated)",
}


# ── Products ───────────────────────────────────────────────────────────────────
# baseline prices are what the catalog opens with; current_price is what the
# live feed serves right now (market_tick() and price edits mutate it).

PRODUCTS: list[dict] = [
    {
        "sku": "BAS112",
        "name": "Basmati Rice 1121",
        "aliases": ["basmati rice", "basmati", "rice 1121", "1121 basmati", "basmati rice 1121"],
        "category": "Agri",
        "unit": "tonne",
        "base_price": "$940",
        "current_price": "$940",
        "stock": 240,
        "min_qty": 25,
        "status": "IN_STOCK",
        "price_note": "FOB Mumbai · export grade",
    },
    {
        "sku": "WHT450",
        "name": "Wheat (MP Sharbati)",
        "aliases": ["wheat", "sharbati", "wheat sharbati", "mp sharbati"],
        "category": "Agri",
        "unit": "tonne",
        "base_price": "$320",
        "current_price": "$320",
        "stock": 1800,
        "min_qty": 50,
        "status": "IN_STOCK",
        "price_note": "FOB Kandla · food-grade",
    },
    {
        "sku": "CRN220",
        "name": "Yellow Maize",
        "aliases": ["maize", "yellow maize", "corn"],
        "category": "Agri",
        "unit": "tonne",
        "base_price": "$215",
        "current_price": "$215",
        "stock": 960,
        "min_qty": 40,
        "status": "IN_STOCK",
        "price_note": "FOB Kakinada · feed grade",
    },
    {
        "sku": "SLN005",
        "name": "Soya Bean Meal",
        "aliases": ["soya", "soybean meal", "soya bean meal", "soyameal"],
        "category": "Agri",
        "unit": "tonne",
        "base_price": "$410",
        "current_price": "$410",
        "stock": 520,
        "min_qty": 25,
        "status": "IN_STOCK",
        "price_note": "FOB Vizag · 48% protein",
    },
    {
        "sku": "STLHRC",
        "name": "Hot Rolled Steel Coil",
        "aliases": ["hot rolled steel", "hot rolled coil", "hr coil", "hr steel", "steel coil"],
        "category": "Metals",
        "unit": "tonne",
        "base_price": "$585",
        "current_price": "$585",
        "stock": 410,
        "min_qty": 20,
        "status": "IN_STOCK",
        "price_note": "CFR Nhava Sheva · IS 2062",
    },
    {
        "sku": "STLCRC",
        "name": "Cold Rolled Steel Coil",
        "aliases": ["cold rolled steel", "cold rolled coil", "cr coil", "cr steel"],
        "category": "Metals",
        "unit": "tonne",
        "base_price": "$642",
        "current_price": "$642",
        "stock": 310,
        "min_qty": 20,
        "status": "IN_STOCK",
        "price_note": "CFR Nhava Sheva · IS 513",
    },
    {
        "sku": "CPR300",
        "name": "Copper Cathode",
        "aliases": ["copper", "copper cathode"],
        "category": "Metals",
        "unit": "tonne",
        "base_price": "$8,940",
        "current_price": "$8,940",
        "stock": 85,
        "min_qty": 5,
        "status": "LOW_STOCK",
        "price_note": "LME-linked · CIF Mundra",
    },
    {
        "sku": "COT101",
        "name": "Raw Cotton (Shankar-6)",
        "aliases": ["cotton", "raw cotton", "shankar 6", "shankar-6"],
        "category": "Textiles",
        "unit": "bale",
        "base_price": "$1,275",
        "current_price": "$1,275",
        "stock": 1400,
        "min_qty": 100,
        "status": "IN_STOCK",
        "price_note": "FOB Mundra · 29mm staple",
    },
    {
        "sku": "JUT330",
        "name": "Jute Fiber (TD-6)",
        "aliases": ["jute", "jute fiber", "jute fibre"],
        "category": "Textiles",
        "unit": "bale",
        "base_price": "$412",
        "current_price": "$412",
        "stock": 610,
        "min_qty": 50,
        "status": "IN_STOCK",
        "price_note": "FOB Kolkata · TD-6 grade",
    },
    {
        "sku": "SPR012",
        "name": "Refined Sugar (ICUMSA 45)",
        "aliases": ["sugar", "refined sugar", "icuamsa 45", "icuamsa", "sugar icumsa 45"],
        "category": "Agri",
        "unit": "tonne",
        "base_price": "$525",
        "current_price": "$525",
        "stock": 780,
        "min_qty": 30,
        "status": "IN_STOCK",
        "price_note": "FOB Nhava Sheva · ICUMSA 45",
    },
]

# ── Lookup indexes (built once) ────────────────────────────────────────────────

_SKU_TO_PRODUCT: dict[str, dict] = {p["sku"]: p for p in PRODUCTS}

# alias (lowercased) -> product; longest aliases first so "basmati rice 1121"
# wins over "basmati rice" when both appear in the text.
_ALIAS_INDEX: list[tuple[str, dict]] = sorted(
    (
        (alias.lower(), p)
        for p in PRODUCTS
        for alias in p["aliases"]
    ),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

# price tokens as spoken: "$940" | "$1,275" | "940 dollars" | "8,940 US dollars"
_PRICE_RE = (
    r"(?:[$€£]\s*\d+(?:,\d{3})*(?:\.\d{1,2})?"
    r"|\b\d+(?:,\d{3})*(?:\.\d{1,2})?\s+(?:us\s+)?dollars?\b)"
)

# Keep only the distinct product names per SKU for the Gemini prompt block.
_COMPACT_LINES: list[str] = []
for _p in PRODUCTS:
    _aliases = ", ".join(_p["aliases"][:3])
    _COMPACT_LINES.append(
        f"- {_p['name']} (aliases: {_aliases}) → price_{_p['sku'].lower()} "
        f"(last quoted {_p['current_price']} per {_p['unit']})"
    )

#: Compact catalog text injected into the Gemini extraction prompt so the LLM
#: keys product prices with the exact enterprise fact keys.
COMPACT_CATALOG: str = "\n".join(_COMPACT_LINES)

#: Aliases used for heuristic matching in the extractor.
ALL_ALIASES: list[tuple[str, str]] = [
    (alias.lower(), p["sku"]) for p in PRODUCTS for alias in p["aliases"]
]


def get_product(sku: str) -> dict | None:
    """Return a product by SKU (case-insensitive) or None."""
    return _SKU_TO_PRODUCT.get(sku.upper())


def fact_key_for_product(sku: str) -> str:
    """Return the freshness fact key for a product SKU: ``price_<sku_lower>``."""
    return f"price_{sku.lower()}"


def sku_for_fact_key(key: str) -> str | None:
    """
    Return the SKU whose price fact key matches ``key`` (``price_bas112`` ->
    ``BAS112``), or None.  Used by the enterprise service to resolve
    ``GET /facts/{key}`` for any product price.
    """
    lower = (key or "").lower()
    if not lower.startswith("price_"):
        return None
    sku = lower.removeprefix("price_").upper()
    return sku if sku in _SKU_TO_PRODUCT else None


def find_price_mentions(text: str, max_products: int = 4) -> list[dict]:
    """
    Heuristic extraction of product prices from a conversation transcript.

    For every product alias that appears in *text*, find the nearest
    ``$``-prefixed price token and return::

        [{"sku": "BAS112", "name": "Basmati Rice 1121",
          "unit": "tonne", "price": "$950"}, ...]

    Products whose name appears without a nearby price are skipped.  At most
    ``max_products`` distinct products are returned (first matches win).
    """
    import re

    if not text:
        return []

    price_matches = [
        (m.start(), m.group(0).strip())
        for m in re.finditer(_PRICE_RE, text)
    ]
    if not price_matches:
        return []

    seen: set[str] = set()
    results: list[dict] = []

    for alias, sku in ALL_ALIASES:
        if sku in seen or len(results) >= max_products:
            continue
        for m in re.finditer(re.escape(alias), text, re.IGNORECASE):
            pos = m.start()
            # Nearest price token; on a tie prefer the price that comes AFTER
            # the product name ("wheat is $320" → $320, not the earlier $950).
            candidates = []
            for ppos, price in price_matches:
                dist = abs(ppos - pos)
                if dist <= 60:
                    candidates.append((dist, ppos < pos, price))
            if not candidates:
                continue
            nearest = min(candidates, key=lambda c: (c[0], c[1]))[2]
            product = _SKU_TO_PRODUCT[sku]
            results.append(
                {
                    "sku": product["sku"],
                    "name": product["name"],
                    "unit": product["unit"],
                    "price": nearest,
                }
            )
            seen.add(sku)
            break

    return results


def products_payload(include_price: bool = True) -> list[dict]:
    """Serialisable product list for the API / console (no internal keys)."""
    out = []
    for p in PRODUCTS:
        item = {
            "sku": p["sku"],
            "name": p["name"],
            "category": p["category"],
            "unit": p["unit"],
            "stock": p["stock"],
            "min_qty": p["min_qty"],
            "status": p["status"],
            "price_note": p["price_note"],
        }
        if include_price:
            item["current_price"] = p["current_price"]
            item["base_price"] = p["base_price"]
        out.append(item)
    return out