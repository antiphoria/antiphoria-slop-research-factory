# engine/graph.py
# src/slop_research_factory/engine/graph.py

"""LangGraph wiring for the slop-research-factory pipeline.

The compiled graph encodes the M2 control flow:

    genesis (already sealed by orchestrator)
        │
        ▼
    GENERATOR ──► VERIFIER ──┬── CORRECT  ─► FINALIZE
                             ├── FIXABLE  ─► REVISER ──► VERIFIER ↻
                             ├── WRONG    ─► REVISER ──► VERIFIER ↻
                             └── caps hit ─► HUMAN_RESCUE

Implementation notes:

* :class:`FactoryState` is a regular dataclass; LangGraph supports it
  via the :class:`StateGraph` constructor. Nodes mutate ``state`` in
  place and return it.
* Routing decisions come from
  :func:`~slop_research_factory.engine.routing.route_after_verification`
  which is the single source of truth for verdict → next-node logic.
* FINALIZE assembles terminal output artifacts and seals the MANIFEST.
* HUMAN_RESCUE persists a rescue request and halts the pipeline.

Spec references:
    D-0 §13   Implementation step plan.
    D-2 §8.4  Verdict routing.
    D-5 §4    Four-phase node protocol.
    D-5 §5.5  Finalize + rescue node contracts.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from slop_research_factory.engine.routing import (
    FINALIZE_NODE,
    FULL_REWRITE,
    HUMAN_RESCUE_NODE,
    REVISER_NODE,
    TARGETED_REPAIR,
)
from slop_research_factory.nodes.finalize_node import finalize_node
from slop_research_factory.nodes.generator_node import generator_node
from slop_research_factory.nodes.human_rescue_node import human_rescue_node
from slop_research_factory.nodes.reviser_node import reviser_node
from slop_research_factory.nodes.verifier_node import (
    StructuredCompleteFn,
    verifier_node,
)
from slop_research_factory.types.enums import RunStatus, Verdict
from slop_research_factory.types.state import FactoryState

NodeFn = Callable[[FactoryState], Awaitable[FactoryState]]

if TYPE_CHECKING:
    from slop_research_factory.llm.client import LLMClient
    from slop_research_factory.seal.engine import SealEngine
    from slop_research_factory.tools.protocol import CitationCheckClient
    from slop_research_factory.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

__all__ = [
    "GENERATOR_NODE_ID",
    "GraphDependencies",
    "VERIFIER_NODE_ID",
    "build_graph",
    "run_graph",
]


GENERATOR_NODE_ID = "generator_node"
VERIFIER_NODE_ID = "verifier_node"


# ── Dependencies ────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class GraphDependencies:
    """Bundle of injectables passed to every graph node.

    Stored on a single object so the LangGraph state stays free of
    non-serialisable handles (engines, clients, workspace I/O).
    """

    seal_engine: SealEngine
    workspace: WorkspaceManager
    llm_client: LLMClient
    citation_check_client: CitationCheckClient
    structured_complete: StructuredCompleteFn | None = None


# ── Node adapters ───────────────────────────────────────


def _make_generator(deps: GraphDependencies) -> NodeFn:
    async def _node(state: FactoryState) -> FactoryState:
        return await generator_node(
            state,
            seal_engine=deps.seal_engine,
            llm_client=deps.llm_client,
            workspace=deps.workspace,
        )

    return _node


def _make_verifier(deps: GraphDependencies) -> NodeFn:
    async def _node(state: FactoryState) -> FactoryState:
        return await verifier_node(
            state,
            seal_engine=deps.seal_engine,
            workspace=deps.workspace,
            citation_check_client=deps.citation_check_client,
            structured_complete=deps.structured_complete,
        )

    return _node


def _make_reviser(deps: GraphDependencies) -> NodeFn:
    async def _node(state: FactoryState) -> FactoryState:
        critique = state.current_critique or {}
        mode_value = critique.get("reviser_mode")
        if mode_value not in {TARGETED_REPAIR, FULL_REWRITE}:
            # Fall back to verdict mapping for tests / call sites that
            # invoke the reviser node directly without routing.
            verdict_raw = critique.get("effective_verdict") or critique.get("verdict")
            verdict_str = str(verdict_raw) if verdict_raw is not None else ""
            try:
                verdict = Verdict(verdict_str)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"reviser_node received unknown verdict {verdict_str!r}",
                ) from exc
            mode_value = TARGETED_REPAIR if verdict is Verdict.FIXABLE else FULL_REWRITE

        return await reviser_node(
            state,
            seal_engine=deps.seal_engine,
            llm_client=deps.llm_client,
            workspace=deps.workspace,
            mode=mode_value,  # type: ignore[arg-type]
        )

    return _node


def _make_finalize(deps: GraphDependencies) -> NodeFn:
    """Finalize node — assembles output artifacts and seals MANIFEST."""

    async def _node(state: FactoryState) -> FactoryState:
        return await finalize_node(
            state,
            seal_engine=deps.seal_engine,
            workspace=deps.workspace,
        )

    return _node


def _make_rescue(deps: GraphDependencies) -> NodeFn:
    """Human rescue node — persists rescue request and seals HUMAN_GATE."""

    async def _node(state: FactoryState) -> FactoryState:
        return await human_rescue_node(
            state,
            seal_engine=deps.seal_engine,
            workspace=deps.workspace,
        )

    return _node


# ── Routing edges ───────────────────────────────────────


def _route_after_verifier(state: FactoryState) -> str:
    """Read the routing target stashed on ``state.current_critique`` by
    :func:`verifier_node`.

    The verifier owns routing because:

    * It already computes the effective verdict (after demotion).
    * Counter mutations (``apply_routing_deltas``) need to land on the
      persisted state, not on a LangGraph conditional snapshot.

    The fallback path here only fires when the verifier raised before
    populating ``current_critique`` — escalate to human rescue so the
    failure is visible in the audit trail.
    """
    critique = state.current_critique or {}
    next_node = critique.get("next_node")
    if isinstance(next_node, str) and next_node:
        return next_node
    logger.error(
        "[router] [%s] verifier did not stash next_node — escalating to rescue",
        state.run_id[:8],
    )
    return HUMAN_RESCUE_NODE


# ── Graph builder ───────────────────────────────────────


def build_graph(deps: GraphDependencies) -> Any:
    """Compile the LangGraph for the factory pipeline.

    Returns a compiled LangGraph object exposing ``ainvoke(state)``.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - install hygiene
        raise RuntimeError(
            "build_graph requires langgraph; install with `pip install langgraph`.",
        ) from exc

    graph = StateGraph(FactoryState)

    # LangGraph's overload set is too narrow for our async callables;
    # they accept any awaitable returning the state at runtime.
    add_node = cast(Callable[[str, Any], None], graph.add_node)
    add_node(GENERATOR_NODE_ID, _make_generator(deps))
    add_node(VERIFIER_NODE_ID, _make_verifier(deps))
    add_node(REVISER_NODE, _make_reviser(deps))
    add_node(FINALIZE_NODE, _make_finalize(deps))
    add_node(HUMAN_RESCUE_NODE, _make_rescue(deps))

    graph.add_edge(START, GENERATOR_NODE_ID)
    graph.add_edge(GENERATOR_NODE_ID, VERIFIER_NODE_ID)

    graph.add_conditional_edges(
        VERIFIER_NODE_ID,
        _route_after_verifier,
        {
            FINALIZE_NODE: FINALIZE_NODE,
            REVISER_NODE: REVISER_NODE,
            HUMAN_RESCUE_NODE: HUMAN_RESCUE_NODE,
        },
    )

    graph.add_edge(REVISER_NODE, VERIFIER_NODE_ID)
    graph.add_edge(FINALIZE_NODE, END)
    graph.add_edge(HUMAN_RESCUE_NODE, END)

    return graph.compile()


async def run_graph(
    state: FactoryState,
    deps: GraphDependencies,
    *,
    config: dict[str, Any] | None = None,
) -> FactoryState:
    """Convenience helper: build the graph, invoke it, return the state.

    Tests that don't care about graph reuse (and want a single-call
    happy path) can drop this in. LangGraph internally serialises the
    dataclass through a dict snapshot; we reconstruct ``FactoryState``
    on the way out so callers always see a proper dataclass.
    """
    graph = build_graph(deps)
    invoke: Callable[..., Awaitable[Any]] = graph.ainvoke
    raw = await invoke(state, config or {})
    if isinstance(raw, FactoryState):
        return raw
    if isinstance(raw, dict):
        # LangGraph hands back a flat dict snapshot. Map enum / config
        # fields back into proper instances via the dataclass loader.
        return _state_from_runtime_dict(raw)
    return cast("FactoryState", raw)


def _state_from_runtime_dict(raw: dict[str, Any]) -> FactoryState:
    """Coerce a LangGraph dataclass-state dict back into FactoryState."""
    from slop_research_factory.config import (
        FactoryConfig,
        factory_config_from_mapping,
    )
    from slop_research_factory.types.state import AppendOnlyList

    data: dict[str, Any] = dict(raw)

    config_value = data.pop("config", None)
    if isinstance(config_value, FactoryConfig):
        config_obj = config_value
    elif isinstance(config_value, dict):
        config_obj = factory_config_from_mapping(config_value)
    else:
        config_obj = FactoryConfig()

    status_value = data.pop("status", RunStatus.GENERATING)
    status = status_value if isinstance(status_value, RunStatus) else RunStatus(status_value)

    messages = data.pop("messages", [])
    citation_checks = data.pop("citation_checks", [])

    return FactoryState(
        config=config_obj,
        status=status,
        messages=AppendOnlyList(list(messages)),
        citation_checks=AppendOnlyList(list(citation_checks)),
        **data,
    )
