"""
mocks/enterprise/
------------------
Meridian Commodities & Exports — the simulated enterprise "live" data source
that powers the freshness feature demonstration.

    catalog.py    → company + product definitions and lookup helpers
    service.py    → runtime state (prices, history, market tick, fact keys)
    router.py     → FastAPI router: console page + /api/enterprise + /facts
    console.html  → the presentation console served at http://localhost:8001/
    ENTERPRISE_BRIEF.md → product cheat-sheet + role-play script for demos

Start the whole thing with:

    python -m mocks.mock_freshness          # serves on port 8001

Or programmatically:

    from mocks.enterprise.service import get_fact_value, market_tick
"""

from . import catalog, service

__all__ = ["catalog", "service"]