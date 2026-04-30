# src/slop_research_factory/tools/__init__.py

"""External tool clients — Crossref, Semantic Scholar, Tavily.

Spec references:
    D-2 §11   Tool query/result types.
    D-4 §5    Tool-grounded citation checking sequence.
    D-5 §5.3  TOOL_CALL seal contract.

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
