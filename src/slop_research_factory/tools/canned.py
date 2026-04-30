# src/slop_research_factory/tools/canned.py

"""Deterministic fake :class:`CitationCheckClient` for tests and offline runs.

A canned client returns pre-scripted results keyed on the query payload.
Two lookup strategies are layered:

1. **Exact match** — ``script[doi]`` / ``script[paper_id]`` /
   ``script[query]`` return whatever the test author registered.

2. **Fallback** — when no script entry matches, the client returns a
   ``not_found`` :class:`ToolInvocation` whose result has ``found=False``.

This is enough for M2: real HTTP backends arrive in M3.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from slop_research_factory.tools.protocol import (
    ToolError,
    ToolInvocation,
)
from slop_research_factory.types.tool_types import (
    CrossrefQuery,
    CrossrefResult,
    SemanticScholarQuery,
    SemanticScholarResult,
    TavilyQuery,
    TavilyResult,
)

__all__ = [
    "CannedCitationCheckClient",
    "CannedScript",
    "CrossrefScript",
    "SemanticScholarScript",
    "TavilyScript",
    "default_canned_client",
]


# ── Per-tool scripts ─────────────────────────────────────


@dataclass(slots=True)
class CrossrefScript:
    """Map ``doi → CrossrefResult``.

    A registered ``None`` value triggers :class:`ToolError` on lookup
    (used to test failure paths).
    """

    by_doi: dict[str, CrossrefResult | None] = field(default_factory=dict)

    def lookup(self, query: CrossrefQuery) -> CrossrefResult:
        if query.doi is None:
            return CrossrefResult(found=False)
        if query.doi in self.by_doi:
            value = self.by_doi[query.doi]
            if value is None:
                raise ToolError(f"crossref: simulated failure for doi {query.doi}")
            return value
        return CrossrefResult(found=False)


@dataclass(slots=True)
class SemanticScholarScript:
    """Map ``paper_id → SemanticScholarResult``."""

    by_paper_id: dict[str, SemanticScholarResult | None] = field(
        default_factory=dict,
    )

    def lookup(self, query: SemanticScholarQuery) -> SemanticScholarResult:
        key = query.paper_id or query.query_title or ""
        if key in self.by_paper_id:
            value = self.by_paper_id[key]
            if value is None:
                raise ToolError(f"semantic_scholar: simulated failure for {key}")
            return value
        return SemanticScholarResult(found=False)


@dataclass(slots=True)
class TavilyScript:
    """Map ``query string → TavilyResult``."""

    by_query: dict[str, TavilyResult | None] = field(default_factory=dict)

    def lookup(self, query: TavilyQuery) -> TavilyResult:
        key = query.query
        if key in self.by_query:
            value = self.by_query[key]
            if value is None:
                raise ToolError(f"tavily: simulated failure for {key!r}")
            return value
        return TavilyResult(query=key, results=[])


@dataclass(slots=True)
class CannedScript:
    """Bundles per-tool scripts behind a single object.

    Pass to :class:`CannedCitationCheckClient` to register fixtures.
    """

    crossref: CrossrefScript = field(default_factory=CrossrefScript)
    semantic_scholar: SemanticScholarScript = field(
        default_factory=SemanticScholarScript,
    )
    tavily: TavilyScript = field(default_factory=TavilyScript)

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, Mapping[str, Any]],
    ) -> CannedScript:
        """Build a script from a plain ``{tool: {key: result}}`` mapping.

        Used in tests for terse fixture declarations.
        """
        crossref = CrossrefScript(by_doi=dict(mapping.get("crossref", {})))
        s2 = SemanticScholarScript(
            by_paper_id=dict(mapping.get("semantic_scholar", {})),
        )
        tavily = TavilyScript(by_query=dict(mapping.get("tavily", {})))
        return cls(crossref=crossref, semantic_scholar=s2, tavily=tavily)


# ── Client implementation ────────────────────────────────


@dataclass(slots=True)
class CannedCitationCheckClient:
    """Deterministic fake :class:`CitationCheckClient`.

    All ``raw_response`` payloads on returned results are populated with
    the canonical serialisation of the registered fake; this gives the
    seal layer a stable byte sequence (TOOL_CALL ``content_hash`` is
    computed over the whole interaction file).

    The optional ``elapsed_seconds`` field is filled with the wall-clock
    delta between :meth:`time.monotonic` reads — typically microseconds
    — to make the field non-zero in audit dumps without violating
    determinism (the field is rounded to 6 decimal places).
    """

    script: CannedScript = field(default_factory=CannedScript)

    async def crossref(self, query: CrossrefQuery) -> ToolInvocation:
        start = time.monotonic()
        try:
            result = self.script.crossref.lookup(query)
            status = "ok" if result.found else "not_found"
            return ToolInvocation(
                tool_name="crossref",
                query=query,
                result=result,
                elapsed_seconds=time.monotonic() - start,
                status=status,
                error=None,
            )
        except ToolError as exc:
            return ToolInvocation(
                tool_name="crossref",
                query=query,
                result=CrossrefResult(found=False),
                elapsed_seconds=time.monotonic() - start,
                status="error",
                error=str(exc),
            )

    async def semantic_scholar(
        self,
        query: SemanticScholarQuery,
    ) -> ToolInvocation:
        start = time.monotonic()
        try:
            result = self.script.semantic_scholar.lookup(query)
            status = "ok" if result.found else "not_found"
            return ToolInvocation(
                tool_name="semantic_scholar",
                query=query,
                result=result,
                elapsed_seconds=time.monotonic() - start,
                status=status,
                error=None,
            )
        except ToolError as exc:
            return ToolInvocation(
                tool_name="semantic_scholar",
                query=query,
                result=SemanticScholarResult(found=False),
                elapsed_seconds=time.monotonic() - start,
                status="error",
                error=str(exc),
            )

    async def tavily(self, query: TavilyQuery) -> ToolInvocation:
        start = time.monotonic()
        try:
            result = self.script.tavily.lookup(query)
            status = "ok" if result.results else "not_found"
            return ToolInvocation(
                tool_name="tavily",
                query=query,
                result=result,
                elapsed_seconds=time.monotonic() - start,
                status=status,
                error=None,
            )
        except ToolError as exc:
            return ToolInvocation(
                tool_name="tavily",
                query=query,
                result=TavilyResult(query=query.query, results=[]),
                elapsed_seconds=time.monotonic() - start,
                status="error",
                error=str(exc),
            )


def default_canned_client() -> CannedCitationCheckClient:
    """Empty-script client — every lookup falls through to ``not_found``."""
    return CannedCitationCheckClient()
