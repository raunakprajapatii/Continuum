"""
modules/signal/tests/conftest.py
---------------------------------
Fixes the Python import path for the signal module tests.

Python's standard library has a built-in `signal` module. Because our package
is named `modules.signal`, we need to ensure pytest adds the repo root to
sys.path so our package name wins over the stdlib `signal` module.

This conftest.py is picked up automatically by pytest before test collection.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make sure the repo root is first in sys.path so that
# `from modules.signal import ...` resolves to OUR package,
# not the stdlib `signal` module.
REPO_ROOT = str(Path(__file__).parents[3])  # …/Continuum
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
