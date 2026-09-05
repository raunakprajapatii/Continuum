"""
Root pytest configuration.

The demo `.env` may carry real provider keys with ``USE_MOCKS=false`` (live
voice / Gemini / Rime).  The test suite is written against the mock
implementations and must stay deterministic and offline, so unless the caller
explicitly exports ``USE_MOCKS`` (e.g. ``USE_MOCKS=false pytest ...``) the
session is pinned to mock mode before any settings are loaded.

Note: pydantic-settings prefers the process environment over `.env`, which is
exactly why setting the variable here wins.
"""

from __future__ import annotations

import os

os.environ.setdefault("USE_MOCKS", "true")

import pytest  # noqa: E402


def pytest_configure(config) -> None:  # noqa: ANN001, ARG001
    """Re-load settings after the environment is pinned to mock mode."""
    from shared.config import get_settings

    get_settings.cache_clear()