# Meridian Commodities & Exports — Enterprise Brief

**Your role:** Regional Sales Manager at Meridian Commodities & Exports — a B2B
commodities trading house selling agri, metals and textiles to bulk buyers.

**The buyer on the phone:** *Zara Mitchell* ("Z"), Procurement Lead at Horizon
Foods International. She is your returning client — the call drops, she calls
back next morning, and **Continuum whispers the recap into your earpiece
before you answer**.

This file is your cheat-sheet: every product Meridian trades, its live price,
and ready-to-speak lines for the role-play — as the **sales rep**, as the
**boss**, or as **Z** on the other side. The prices below are exactly what the
enterprise feed serves on port 8001, so anything you quote in the call is
re-verified by the freshness checker at the callback.

---

## 🏢 Company at a glance

| Field | Value |
|-------|-------|
| Company | Meridian Commodities & Exports Pvt. Ltd. |
| Business | Global B2B trading — agri, metals & textiles |
| Currency / basis | USD · FOB Mumbai (see per-product note) |
| Live price feed | `http://localhost:8001` (enterprise API) |
| Database | SQLite · `enterprise.db` (override with `ENTERPRISE_DB_PATH`) |
| Console | `http://localhost:8001/` — watch & move prices live |
| Your title | Regional Sales Manager |
| Buyer | Zara Mitchell · Procurement, Horizon Foods Intl. |
| Current deal on the table | Basmati Rice 1121 — 25–50 t, volume pricing |

> **Demo tip:** open the console (`http://localhost:8001/`) side-by-side with
> the Continuum dashboard. After call one, click **"Simulate overnight market
> move"** — two products change price — then run the callback and hear the
> recap flag it.

---

## 📦 Product catalog (baseline prices served by the feed)

| SKU | Product | Category | Unit | Live price | Stock | Min qty | Status | Price note |
|-----|---------|----------|------|-----------|-------|---------|--------|------------|
| BAS112 | Basmati Rice 1121 | Agri | tonne | **$940** | 240 | 25 | IN_STOCK | FOB Mumbai · export grade |
| WHT450 | Wheat (MP Sharbati) | Agri | tonne | **$320** | 1,800 | 50 | IN_STOCK | FOB Kandla · food-grade |
| CRN220 | Yellow Maize | Agri | tonne | **$215** | 960 | 40 | IN_STOCK | FOB Kakinada · feed grade |
| SLN005 | Soya Bean Meal | Agri | tonne | **$410** | 520 | 25 | IN_STOCK | FOB Vizag · 48% protein |
| STLHRC | Hot Rolled Steel Coil | Metals | tonne | **$585** | 410 | 20 | IN_STOCK | CFR Nhava Sheva · IS 2062 |
| STLCRC | Cold Rolled Steel Coil | Metals | tonne | **$642** | 310 | 20 | IN_STOCK | CFR Nhava Sheva · IS 513 |
| CPR300 | Copper Cathode | Metals | tonne | **$8,940** | 85 | 5 | LOW_STOCK | LME-linked · CIF Mundra |
| COT101 | Raw Cotton (Shankar-6) | Textiles | bale | **$1,275** | 1,400 | 100 | IN_STOCK | FOB Mundra · 29mm staple |
| JUT330 | Jute Fiber (TD-6) | Textiles | bale | **$412** | 610 | 50 | IN_STOCK | FOB Kolkata · TD-6 grade |
| SPR012 | Refined Sugar (ICUMSA 45) | Agri | tonne | **$525** | 780 | 30 | IN_STOCK | FOB Nhava Sheva · ICUMSA 45 |

### Freshness fact keys (what Continuum re-verifies)

Every product price is a **freshness fact**. When you mention a product in
call one, the extractor stores the price under the product's key; the callback
recap checks that key against the live feed.

| SKU | Fact key | Example stored value |
|-----|----------|---------------------|
| BAS112 | `price_bas112` | `$940` |
| WHT450 | `price_wht450` | `$320` |
| CRN220 | `price_crn220` | `$215` |
| SLN005 | `price_sln005` | `$410` |
| STLHRC | `price_stlhrc` | `$585` |
| STLCRC | `price_stlcrc` | `$642` |
| CPR300 | `price_cpr300` | `$8,940` |
| COT101 | `price_cot101` | `$1,275` |
| JUT330 | `price_jut330` | `$412` |
| SPR012 | `price_spr012` | `$525` |

Say the **product name** and a **$ price in the same sentence** and the fact
is captured — e.g. *"Basmati rice is $940 per tonne."*

---

## 🎭 Role-play scripts

### Script A — Sales rep vs buyer (recommended freshness demo)

**Call 1 (yesterday, mid-conversation, then the line drops):**

> **Z:** Hey — basmati rice ke liye kya rate hai is quarter? Hum 40 tonne ka
> order plan kar rahe hain.
>
> **You:** Basmati rice is $940 per tonne, FOB Mumbai. 25 tonne minimum, and
> for 40+ I can push for a volume discount.
>
> **Z:** Achha. Aur wheat ka kya scene hai?
>
> **You:** Wheat is $320 per tonne — I'll check with the boss on a combined
> deal and get back to you tomorrow morning.
>
> **Z:** Perfect. Please call me first thing — before I finalise with the other
> supplier.
>
> **You:** Done, I'll call you at 9. *(line drops — the conversation is
> interrupted)*

**Overnight:** click **"Simulate overnight market move"** in the Meridian
console → Basmati moves **$940 → $955** (and another product moves too).

**Callback (next morning — the demo moment):**

> Continuum whispers (Rime, private track): *"Z wanted the Basmati quote; you
> said you'd check with the boss. Heads up — Basmati Rice price was $940, it's
> now $955. Your move: call Z back with the updated number."*

**You answer** already knowing the price moved — that is the freshness catch.

### Script B — Boss to salesman (internal call, price changed overnight)

Use this to demo that Continuum catches *any* price the enterprise feed serves,
even one you didn't change yourself.

> **Boss:** Morning. Have you sent the new basmati quote to Horizon Foods yet?
>
> **You:** Not yet, I was going to send $940.
>
> **Boss:** Don't — the exchange feed updated overnight. Check the console
> before you quote. *(the feed shows $955)*
>
> **You:** Got it, I'll re-send at $955 and let Z know before her 9 AM call.
>
> *(drop / callback → the recap re-verifies `price_bas112` and confirms $955)*

### Script C — Pure English quick run (no Hinglish needed)

> **Z:** Hi, what's your current price on hot rolled steel coil?
>
> **You:** Hot rolled steel coil is $585 per tonne, CFR Nhava Sheva.
>
> **Z:** Great, can you hold that price until Friday?
>
> **You:** I'll confirm with my manager and call you back.
>
> **Z:** Perfect, call me tomorrow morning.
>
> *(drop → overnight tick moves `price_stlhrc` $585 → $603 → the recap flags it)*

---

## 🧪 Full demo checklist (5 minutes)

1. **Start the enterprise feed:** `python -m mocks.mock_freshness` (port 8001)
   → open `http://localhost:8001/` — the Meridian console shows live prices.
2. **Start the Continuum dashboard** (`uvicorn dashboard.server:app --port 8000`
   + `pnpm dev` in `web/`), pick a scenario, and **record call 1** using
   Script A/B/C (one person = User 1, the other = User 2).
3. **Drop the call** — the thread is stored with the product price(s) as facts.
4. **Simulate overnight:** in the Meridian console click **"Simulate overnight
   market move"** (or edit a single price) — watch the feed update.
5. **Run the callback** — during the ring window the freshness check compares
   the stored price to the live feed; the Rime recap says *"Heads up — … was
   $940, it's now $955."* The dashboard's memory card + event log show the
   `freshness.discrepancy_found` entry with old → new values.
6. **Reset** (`↺ Reset baseline prices` in the console, then Reset & replay in
   the dashboard) for another take.

## 🔌 API reference (handy during the demo)

| Endpoint | Purpose |
|----------|---------|
| `GET /` | The enterprise console (this presentation) |
| `GET /api/enterprise` | Company + full live product catalog |
| `GET /api/enterprise/products/{sku}` | One product's live price |
| `POST /api/enterprise/products/{sku}/price` `{"price":"$955"}` | Edit a price live |
| `POST /api/enterprise/market-tick` | Simulate an overnight market move |
| `POST /api/enterprise/reset` | Restore baseline prices |
| `GET /facts/{key}` | Freshness-checker contract (`price_bas112`, …) |

**Where the data lives:** prices are stored in the SQLite database
`enterprise.db` (seeded from `mocks/enterprise/catalog.py` on first boot) —
that is the *database containing info about the enterprise* that the freshness
checker reads. Edits and market ticks persist across restarts; the console's
**Reset baseline prices** (or `POST /api/enterprise/reset`) restores the
catalog baseline. Add or tweak products in `catalog.py`, then reset — the
console, the extractor and the freshness checker all pick them up
automatically.