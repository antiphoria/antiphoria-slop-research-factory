# nodes/human_rescue_node.py
# src/slop_research_factory/nodes/human_rescue_node.py

"""
Human rescue node — escalation endpoint when loop limits are exhausted.

This node fires when routing determines that no further automated
progress is possible (max rejections, max revisions, budget exceeded,
or cycle cap hit). Its responsibilities:

  1. Extract the rescue reason from the routing decision.
  2. Build a :class:`~slop_research_factory.types.human_rescue.HumanRescueRequest`.
  3. Persist the request as JSON to ``rescue/request.json``.
  4. Seal a HUMAN_GATE step covering the request file.
  5. Transition state to AWAITING_HUMAN.

The node performs **no LLM inference**. It is a deterministic
checkpoint that preserves all context needed for a human operator
to inspect the failure, make corrections, and resume the pipeline.

v0.1.0 scope: The rescue node writes the request and halts.
Actual human input is manual file editing + CLI ``resume``.
Full queue UI is post-v0.1.

Spec references:
    D-0 §4C   Escalation to human rescue.
    D-2 §4    Loop limits triggering rescue.
    D-2 §8.4  Routing → HUMAN_RESCUE_NODE.
    D-5 §5.5  Human rescue node contract.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from slop_research_factory.types.enums import (
    RescueReason,
    RunStatus,
    StepType,
)
from slop_research_factory.types.human_rescue import HumanRescueRequest

if TYPE_CHECKING:
    from slop_research_factory.seal.engine import SealEngine
    from slop_research_factory.types.state import FactoryState
    from slop_research_factory.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

__all__ = ["human_rescue_node"]


# ── Helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 with milliseconds."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _extract_rescue_reason(state: FactoryState) -> RescueReason:
    """Extract the rescue reason from stashed routing decision.

    The verifier node stashes ``rescue_reason`` on
    ``state.current_critique`` after routing decides escalation.
    If missing (defensive), fall back to a generic reason based
    on state counters.
    """
    critique = state.current_critique or {}
    raw_reason = critique.get("rescue_reason")

    if raw_reason is not None:
        if isinstance(raw_reason, RescueReason):
            return raw_reason
        try:
            return RescueReason(str(raw_reason))
        except (TypeError, ValueError):
            pass

    # Defensive fallback: infer from state
    config = state.config
    if state.rejection_count >= config.max_rejections:
        return RescueReason.MAX_REJECTIONS_EXCEEDED
    if state.revision_count >= config.max_revisions:
        return RescueReason.MAX_REVISIONS_EXCEEDED
    if config.max_total_tokens is not None:
        consumed = state.total_input_tokens + state.total_output_tokens + state.total_think_tokens
        if consumed >= config.max_total_tokens:
            return RescueReason.MAX_TOTAL_TOKENS_EXCEEDED
    if (
        config.max_total_cost_usd is not None
        and state.total_estimated_cost_usd >= config.max_total_cost_usd
    ):
        return RescueReason.MAX_TOTAL_COST_EXCEEDED
    if state.cycle_count >= config.max_total_cycles:
        return RescueReason.MAX_TOTAL_CYCLES_EXCEEDED

    logger.warning(
        "[rescue] [%s] Could not determine rescue reason — defaulting to MAX_TOTAL_CYCLES",
        state.run_id[:8],
    )
    return RescueReason.MAX_TOTAL_CYCLES_EXCEEDED


def _build_rescue_context(state: FactoryState) -> dict[str, Any]:
    """Build the diagnostic context dict persisted with the request.

    Contains everything a human operator needs to understand the
    failure without reading the full chain.
    """
    critique = state.current_critique or {}

    return {
        "last_verdict": critique.get("effective_verdict") or critique.get("verdict"),
        "verdict_confidence": critique.get("verdict_confidence"),
        "critique_summary": critique.get("summary") or critique.get("critique_text"),
        "issues": critique.get("issues", []),
        "cycle_count": state.cycle_count,
        "revision_count": state.revision_count,
        "rejection_count": state.rejection_count,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "total_estimated_cost_usd": round(state.total_estimated_cost_usd, 6),
        "total_wall_clock_seconds": round(state.total_wall_clock_seconds, 3),
        "config_limits": {
            "max_rejections": state.config.max_rejections,
            "max_revisions": state.config.max_revisions,
            "max_total_cycles": state.config.max_total_cycles,
            "max_total_tokens": state.config.max_total_tokens,
            "max_total_cost_usd": state.config.max_total_cost_usd,
        },
    }


# ── Node entry point ─────────────────────────────────────────────────


async def human_rescue_node(
    state: FactoryState,
    *,
    seal_engine: SealEngine,
    workspace: WorkspaceManager,
) -> FactoryState:
    """Persist a human rescue request and seal the HUMAN_GATE step.

    Args:
        state:       Current ``FactoryState`` — mutated in place.
        seal_engine: Engine instance scoped to the run.
        workspace:   Workspace I/O helper.

    Returns:
        The updated ``FactoryState`` with ``status == AWAITING_HUMAN``.
    """
    from slop_research_factory.seal.helpers import seal_step

    logger.info(
        "[rescue] [%s] Human rescue triggered — entering escalation",
        state.run_id[:8],
    )

    # ── 1. Determine rescue reason ────────────────────────────────
    rescue_reason = _extract_rescue_reason(state)

    logger.info(
        "[rescue] [%s] Reason: %s (cycles=%d, rejections=%d, revisions=%d)",
        state.run_id[:8],
        rescue_reason.value,
        state.cycle_count,
        state.rejection_count,
        state.revision_count,
    )

    # ── 2. Build HumanRescueRequest ──────────────────────────────
    request = HumanRescueRequest(
        run_id=state.run_id,
        rescue_reason=rescue_reason,
        created_at=_now_iso(),
        brief=dict(state.brief) if state.brief else {},
        current_draft=state.current_draft,
        current_critique=state.current_critique,
        context=_build_rescue_context(state),
        latest_seal_hash=state.latest_hash,
        step_index=state.step_index,
    )

    # ── 3. Persist request to rescue/ ─────────────────────────────
    rescue_dir = workspace.workspace_path / "rescue"
    rescue_dir.mkdir(parents=True, exist_ok=True)

    request_data = request.to_dict()
    request_content = json.dumps(
        request_data,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )

    request_path = rescue_dir / "request.json"
    request_path.write_text(request_content + "\n", encoding="utf-8")

    logger.info(
        "[rescue] [%s] Request persisted to %s",
        state.run_id[:8],
        request_path,
    )

    # ── 4. Persist current draft snapshot (if any) ────────────────
    content_files: list[str] = []

    # Always include the request
    request_relative = workspace.relative(request_path)
    content_files.append(request_relative)

    # Include draft snapshot for easy human access
    if state.current_draft:
        draft_path = rescue_dir / "draft_at_rescue.md"
        draft_path.write_text(state.current_draft, encoding="utf-8")
        content_files.append(workspace.relative(draft_path))

    # Include critique snapshot
    if state.current_critique:
        critique_content = json.dumps(
            state.current_critique,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        critique_path = rescue_dir / "critique_at_rescue.json"
        critique_path.write_text(critique_content + "\n", encoding="utf-8")
        content_files.append(workspace.relative(critique_path))

    # ── 5. Seal HUMAN_GATE ────────────────────────────────────────
    seal_metadata = {
        "rescue_reason": rescue_reason.value,
        "cycle_count": state.cycle_count,
        "revision_count": state.revision_count,
        "rejection_count": state.rejection_count,
    }

    state, receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.HUMAN_GATE,
        content_file_paths=content_files,
        metadata=seal_metadata,
    )

    logger.info(
        "[rescue] [%s] HUMAN_GATE sealed (step %d, hash %s…)",
        state.run_id[:8],
        state.step_index,
        state.latest_hash[:12],
    )

    # ── 6. State transition → AWAITING_HUMAN ─────────────────────
    state.status = RunStatus.AWAITING_HUMAN
    state.updated_at = _now_iso()
    workspace.write_state(state)

    logger.info(
        "[rescue] [%s] Status → AWAITING_HUMAN. "
        "Human operator must inspect rescue/ and resume via CLI.",
        state.run_id[:8],
    )

    return state
