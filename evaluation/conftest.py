"""
evaluation/conftest.py
-----------------------
Shared pytest fixtures for all acceptance tests.

Each test produces a saved artifact (clip, log, or screenshot) for
RIME_EVIDENCE.md, per blueprint § 13.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────

EVAL_DIR = Path(__file__).parent
ARTIFACTS_DIR = EVAL_DIR / "artifacts"
RESULTS_LOG = EVAL_DIR / "results.json"


def pytest_configure(config: pytest.Config) -> None:
    """Ensure artifact directory exists before any test runs."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def use_mocks() -> bool:
    """Return True when USE_MOCKS env var is set (default True for CI)."""
    return os.getenv("USE_MOCKS", "true").lower() in ("true", "1", "yes")


@pytest.fixture(autouse=True)
def log_result(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """
    After each test, append a result entry to results.json.
    This feeds directly into RIME_EVIDENCE.md.
    """
    start = datetime.now(tz=timezone.utc)
    outcome: dict = {}

    yield  # test runs here

    end = datetime.now(tz=timezone.utc)
    rep = getattr(request.node, "_report_sections", [])

    entry = {
        "test": request.node.nodeid,
        "status": "UNKNOWN",
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "duration_s": (end - start).total_seconds(),
    }

    # Update results log
    results: list = []
    if RESULTS_LOG.exists():
        results = json.loads(RESULTS_LOG.read_text())
    results.append(entry)
    RESULTS_LOG.write_text(json.dumps(results, indent=2))


@pytest.fixture
def mock_brain_request():
    """Return a deterministic RecapRequest from the Brain mock."""
    from mocks.mock_brain import make_recap_request
    return make_recap_request()


@pytest.fixture
def mock_freshness_values():
    """
    Return and reset mock freshness store values.
    Restores original values after each test so tests are isolated.
    """
    from mocks.mock_freshness import _FACT_STORE, get_fact_value, set_fact_value

    original = dict(_FACT_STORE)
    yield _FACT_STORE

    # Restore
    for key, value in original.items():
        set_fact_value(key, value)
