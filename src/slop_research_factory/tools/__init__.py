# src/slop_research_factory/tools/__init__.py

"""External tool clients — Crossref, Semantic Scholar, Tavily.


The :class:`CitationCheckClient` Protocol abstracts the wire-level
client. M2 ships canned (deterministic fake) implementations only;
real HTTP-backed clients land in M3.
"""

from __future__ import annotations

from slop_research_factory.tools.canned import (
    CannedCitationCheckClient,
    CannedScript,
    CrossrefScript,
    SemanticScholarScript,
    TavilyScript,
    default_canned_client,
)
from slop_research_factory.tools.protocol import (
    CitationCheckClient,
    ToolError,
    ToolInvocation,
)

__all__ = [
    "CannedCitationCheckClient",
    "CannedScript",
    "CitationCheckClient",
    "CrossrefScript",
    "SemanticScholarScript",
    "TavilyScript",
    "ToolError",
    "ToolInvocation",
    "default_canned_client",
]
