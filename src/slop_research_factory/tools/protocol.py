# src/slop_research_factory/tools/protocol.py

"""External tool client Protocol.

The Verifier node executes citation checks before its own LLM
inference. Each lookup is sealed as a
TOOL_CALL step. To keep the node testable without HTTP
mocks, the wire-level client is abstracted behind a Protocol; the
node accepts any object that satisfies this contract.

Design notes:

* Methods are async because the production client will be HTTP-
  backed (httpx). Canned fakes simply ``return`` synchronously.

* Methods MUST return a populated ``raw_response`` dict even on
  failure — the seal stores the full request/response interaction
  for audit.

* :class:`ToolInvocation` is the serialisable record handed to
  :func:`json.dumps` and persisted to ``tools/{tool}_{idx}.json``
  under the workspace root before sealing as a TOOL_CALL step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Protocol, runtime_checkable

from slop_research_factory.types.tool_types import (
    CrossrefQuery,
    SemanticScholarQuery,
    TavilyQuery,
)

__all__ = [
    "CitationCheckClient",
    "ToolError",
    "ToolInvocation",
]


class ToolError(RuntimeError):
    """Wire-level tool failure (timeout, 5xx, auth, malformed body)."""


@dataclass(frozen=True)
class ToolInvocation:
    """Serialisable record of a single tool call.

    Persisted to ``{workspace}/tools/{tool_name}_{idx}.json`` and
    sealed under :class:`StepType.TOOL_CALL`.

    Both *query* and *result* dataclasses are serialised by
    :meth:`to_dict` to produce a single canonical JSON document.
    """

    tool_name: str
    query: Any
    result: Any
    elapsed_seconds: float
    status: str  # "ok" | "not_found" | "error"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict for canonical serialisation."""

        def _coerce(value: Any) -> Any:
            if value is None:
                return None
            if is_dataclass(value) and not isinstance(value, type):
                return asdict(value)
            if isinstance(value, dict):
                return {k: _coerce(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_coerce(v) for v in value]
            return value

        return {
            "_schema_version": "0.1",
            "tool_name": self.tool_name,
            "query": _coerce(self.query),
            "result": _coerce(self.result),
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "status": self.status,
            "error": self.error,
        }


@runtime_checkable
class CitationCheckClient(Protocol):
    """Async client capable of looking up citations and supporting evidence.

    Implementations:

    * :class:`~slop_research_factory.tools.canned.CannedCitationCheckClient`
      deterministic fake (M2 ships this).
    * ``HTTPCitationCheckClient`` — real Crossref / Semantic Scholar /
      Tavily client (M3, not part of M2).

    The Protocol does NOT mandate sealing; sealing is the Verifier
    node's responsibility. Implementations focus on the wire layer
    only.
    """

    async def crossref(
        self,
        query: CrossrefQuery,
    ) -> ToolInvocation:
        """Look up *query* against Crossref.

        Implementations MUST embed a :class:`CrossrefResult` (with
        ``found = False`` on miss) inside ``ToolInvocation.result``.
        Network failures raise :class:`ToolError`.
        """

    async def semantic_scholar(
        self,
        query: SemanticScholarQuery,
    ) -> ToolInvocation:
        """Look up *query* against Semantic Scholar.

        Embeds a :class:`SemanticScholarResult` in the invocation.
        """

    async def tavily(
        self,
        query: TavilyQuery,
    ) -> ToolInvocation:
        """Run a Tavily search.

        Optional path (NV-2 novelty signal).
        Embeds a :class:`TavilyResult` in the invocation.
        """
