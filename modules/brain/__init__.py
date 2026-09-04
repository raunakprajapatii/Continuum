"""
modules/brain
-------------
Pair C — Thread Memory Store + Recap Generator.

Exports:
  - BrainService: Central coordinator
  - ThreadMemoryStore: SQLite persistence layer
  - ConversationExtractor: Memory extraction (Gemini / Heuristic)
  - build_recap_request: RecapRequest factory
"""

from .extractor import ConversationExtractor
from .recap import build_recap_request, determine_urgency
from .service import BrainService
from .store import ThreadMemoryStore

__all__ = [
    "BrainService",
    "ConversationExtractor",
    "ThreadMemoryStore",
    "build_recap_request",
    "determine_urgency",
]
