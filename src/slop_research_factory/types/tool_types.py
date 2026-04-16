# src/slop_research_factory/types/tool_types.py

"""
Tool invocation types — D-2 §11.

External API interaction types (Crossref, Semantic Scholar, Tavily).
All frozen dataclasses because they are produced exclusively by
factory code, never by an LLM (D-2 §2).

Human rescue types live in ``human_rescue.py`` (D-2 §12).

Sealing contract (D-5 §5.3):
  Every external tool invocation produces a TOOL_CALL seal step
  whose ``content_hash`` covers the serialized query AND result
  together, ensuring the complete interaction is chained.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CrossrefQuery",
    "CrossrefResult",
    "SemanticScholarQuery",
    "SemanticScholarResult",
    "TavilyQuery",
    "TavilyResult",
]


# ── D-2 §11.1  Crossref ─────────────────────────────────────


@dataclass(frozen=True)
class CrossrefQuery:
    """Query parameters for the Crossref API.

    Endpoint: ``https://api.crossref.org/works/{doi}``

    At least one of *doi*, *query_title*, or *query_author*
    should be non-None; the caller decides which lookup
    strategy to use based on available citation metadata.
    """

    doi: str | None = None
    query_title: str | None = None
    query_author: str | None = None


@dataclass(frozen=True)
class CrossrefResult:
    """Parsed Crossref API response.

    ``raw_response`` stores the complete JSON body for audit
    (D-1 §6, Attack 3 mitigation: seal the verification
    sources so post-hoc auditing is possible).
    """

    found: bool
    doi: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    journal: str | None = None
    raw_response: dict[str, Any] = field(
        default_factory=dict,
    )


# ── D-2 §11.2  Semantic Scholar ──────────────────────────────


@dataclass(frozen=True)
class SemanticScholarQuery:
    """Query for the Semantic Scholar Graph API.

    ``paper_id`` accepts a DOI (``DOI:10.xxx``), arXiv ID
    (``arXiv:YYMM.NNNNN``), or native S2 paper ID.
    """

    paper_id: str | None = None
    query_title: str | None = None


@dataclass(frozen=True)
class SemanticScholarResult:
    """Parsed Semantic Scholar response.

    ``abstract`` is used for CV-5 claim-citation relevance
    checking (D-4 §3.1) when available.  If absent, CV-5 is
    skipped and the result is ``INCONCLUSIVE``.
    """

    found: bool
    paper_id: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    abstract: str | None = None
    citation_count: int | None = None
    raw_response: dict[str, Any] = field(
        default_factory=dict,
    )


# ── D-2 §11.3  Tavily Search ────────────────────────────────


@dataclass(frozen=True)
class TavilyQuery:
    """Query for the Tavily Search API.

    Used for NV-2 novelty search and general fact-checking
    (D-4 §3.4, §6.3).
    """

    query: str
    search_depth: str = "basic"   # "basic" or "advanced"
    max_results: int = 5


@dataclass(frozen=True)
class TavilyResult:
    """Parsed Tavily search response.

    Each entry in ``results`` follows::

        {"title": str, "url": str,
         "content": str, "score": float}

    Security note (D-1 §6, Attack 3): results may contain
    adversarial content.  All results are sealed as TOOL_CALL
    steps and injected inside ``<tool_result>`` XML tags per
    D-3 §4.2.
    """

    query: str
    results: list[dict[str, Any]] = field(
        default_factory=list,
    )
    raw_response: dict[str, Any] = field(
        default_factory=dict,
    )
