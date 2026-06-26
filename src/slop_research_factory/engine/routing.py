# src/slop_research_factory/engine/routing.py

"""
Verdict routing logic.4, , .1.

Determines the next node after Verifier assessment:

  - **Demotion**: CORRECT with sub-threshold

    confidence is demoted to FIXABLE.
  - **Routing**: effective verdict × state limits

    → next node.
  - **Counter updates**: :func:`apply_routing_deltas` adds the
    ``revision_increment`` / ``rejection_increment`` fields
    on :class:`RoutingDecision` to ``FactoryState`` **after**
    routing (call once per routing decision; pure routing does
    not mutate state).

This module makes no LLM calls, no network requests, and no
seal-engine invocations.

Loop limits are evaluated per branch — see
:class:`~slop_research_factory.config.FactoryConfig` docstring.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from slop_research_factory.types.enums import RescueReason, Verdict

if TYPE_CHECKING:
    from slop_research_factory.types.state import FactoryState

__all__ = [
    "FINALIZE_NODE",
    "FULL_REWRITE",
    "HUMAN_RESCUE_NODE",
    "REASON_MAX_COST",
    "REASON_MAX_CYCLES",
    "REASON_MAX_REJECTIONS",
    "REASON_MAX_REVISIONS",
    "REASON_MAX_TOKENS",
    "REVISER_NODE",
    "RoutingDecision",
    "TARGETED_REPAIR",
    "apply_routing_deltas",
    "compute_effective_verdict",
    "route_after_verification",
]

logger = logging.getLogger(__name__)


# ── Node identifiers ─────────────────────────────────────────────────

FINALIZE_NODE: str = "finalize_manifest"
REVISER_NODE: str = "reviser_node"
HUMAN_RESCUE_NODE: str = "human_rescue_queue"

# ── Reviser modes ─────────────────────────────────────────

TARGETED_REPAIR: str = "targeted_repair"
"""FIXABLE → patch the existing draft."""

FULL_REWRITE: str = "full_rewrite"
"""WRONG → discard draft, regenerate from brief + critique."""

# ── Rescue reasons (see :class:`RescueReason`) ─────────────────────────

REASON_MAX_REJECTIONS: RescueReason = RescueReason.MAX_REJECTIONS_EXCEEDED
REASON_MAX_REVISIONS: RescueReason = RescueReason.MAX_REVISIONS_EXCEEDED
REASON_MAX_TOKENS: RescueReason = RescueReason.MAX_TOTAL_TOKENS_EXCEEDED
REASON_MAX_COST: RescueReason = RescueReason.MAX_TOTAL_COST_EXCEEDED
REASON_MAX_CYCLES: RescueReason = RescueReason.MAX_TOTAL_CYCLES_EXCEEDED


# ── RoutingDecision ──────────────────────────────────────────────────


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable result of the verdict routing logic.


    Attributes:
        next_node: One of :data:`FINALIZE_NODE`,
                       :data:`REVISER_NODE`, or
                       :data:`HUMAN_RESCUE_NODE`.
        reviser_mode: ``"targeted_repair"`` or ``"full_rewrite"``
                       when *next_node* is the Reviser;
                       ``None`` otherwise.
        rescue_reason: Limit that triggered rescue when
                       *next_node* is the human rescue queue;
                       ``None`` otherwise.
        revision_increment: Add to ``state.revision_count`` via
            :func:`apply_routing_deltas` (0 or 1).
        rejection_increment: Add to ``state.rejection_count`` via
            :func:`apply_routing_deltas` (0 or 1).
    """

    next_node: str
    reviser_mode: str | None = None
    rescue_reason: RescueReason | None = None
    revision_increment: int = 0
    rejection_increment: int = 0


def apply_routing_deltas(
    state: FactoryState,
    decision: RoutingDecision,
) -> None:
    """Apply counter increments from *decision* to *state* in place.

    Call this once after :func:`route_after_verification` when the
    orchestrator commits the transition. Idempotent *decisions* are
    safe to re-apply if you construct a new ``RoutingDecision`` each
    time; do **not** call twice for the same logical routing event.
    """
    if decision.revision_increment:
        state.revision_count += decision.revision_increment
    if decision.rejection_increment:
        state.rejection_count += decision.rejection_increment


# ── Demotion rule ────────────────────────────────────────


def compute_effective_verdict(
    verdict: Verdict,
    verdict_confidence: float,
    threshold: float,
) -> Verdict:
    """Apply the confidence demotion rule.

    If *verdict* is ``CORRECT`` but *verdict_confidence* is
    below *threshold*, the effective verdict is demoted to
    ``FIXABLE``.

    There is intentionally **no** promotion rule: a
    low-confidence ``WRONG`` verdict is never upgraded.
    The system fails safe.

    Args:
        verdict: Raw verdict from the Verifier LLM.
        verdict_confidence: Composed confidence score (0.0–1.0).
        threshold: Value of
            ``config.verifier_confidence_threshold``.

    Returns:
        Effective verdict after demotion (if any).
    """
    if verdict is Verdict.CORRECT and verdict_confidence < threshold:
        logger.info(
            "Demotion: CORRECT confidence %.3f < threshold %.3f → effective FIXABLE",
            verdict_confidence,
            threshold,
        )
        return Verdict.FIXABLE
    return verdict


# ── Budget / cycle guard ───────────────────


def _check_budget_and_cycles(
    state: FactoryState,
) -> RescueReason | None:
    """Return the rescue reason if a budget or cycle cap is hit.

    Checks: token budget, cost budget, then absolute cycle count.

    Returns ``None`` when no cap is breached.
    """
    config = state.config

    if config.max_total_tokens is not None:
        consumed = state.total_input_tokens + state.total_output_tokens + state.total_think_tokens
        if consumed >= config.max_total_tokens:
            return REASON_MAX_TOKENS

    if (
        config.max_total_cost_usd is not None
        and state.total_estimated_cost_usd >= config.max_total_cost_usd
    ):
        return REASON_MAX_COST

    if state.cycle_count >= config.max_total_cycles:
        return REASON_MAX_CYCLES

    return None


# ── Main routing function ─────────────────────


def route_after_verification(
    state: FactoryState,
    effective_verdict: Verdict,
) -> RoutingDecision:
    """Determine the next node; **does not** mutate *state*.

    Apply counter deltas with :func:`apply_routing_deltas` after
    this returns when the orchestrator records the step.

    Args:
        state: Current ``FactoryState`` (read-only).
        effective_verdict: Post-demotion verdict from
            :func:`compute_effective_verdict`.

    Returns:
        Frozen :class:`RoutingDecision` with optional
        ``revision_increment`` / ``rejection_increment``.
    """
    if effective_verdict is Verdict.CORRECT:
        logger.info(
            "Routing: CORRECT → %s",
            FINALIZE_NODE,
        )
        return RoutingDecision(next_node=FINALIZE_NODE)

    if effective_verdict is Verdict.FIXABLE:
        return _route_fixable(state)

    return _route_wrong(state)


# ── Per-verdict routing helpers ──────────────────────────────────────


def _route_fixable(state: FactoryState) -> RoutingDecision:
    """Route a FIXABLE verdict."""
    cfg = state.config

    if state.revision_count >= cfg.max_revisions:
        logger.info(
            "Routing: FIXABLE → rescue (%s, revision_count=%d >= max=%d)",
            REASON_MAX_REVISIONS.value,
            state.revision_count,
            cfg.max_revisions,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=REASON_MAX_REVISIONS,
        )

    budget_reason = _check_budget_and_cycles(state)
    if budget_reason is not None:
        logger.info(
            "Routing: FIXABLE → rescue (%s)",
            budget_reason.value,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=budget_reason,
        )

    new_rev = state.revision_count + 1
    logger.info(
        "Routing: FIXABLE → %s (%s), revision_count would be %d",
        REVISER_NODE,
        TARGETED_REPAIR,
        new_rev,
    )
    return RoutingDecision(
        next_node=REVISER_NODE,
        reviser_mode=TARGETED_REPAIR,
        revision_increment=1,
    )


def _route_wrong(state: FactoryState) -> RoutingDecision:
    """Route a WRONG verdict."""
    cfg = state.config

    if state.rejection_count >= cfg.max_rejections:
        logger.info(
            "Routing: WRONG → rescue (%s, rejection_count=%d >= max=%d)",
            REASON_MAX_REJECTIONS.value,
            state.rejection_count,
            cfg.max_rejections,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=REASON_MAX_REJECTIONS,
        )

    budget_reason = _check_budget_and_cycles(state)
    if budget_reason is not None:
        logger.info(
            "Routing: WRONG → rescue (%s)",
            budget_reason.value,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=budget_reason,
        )

    new_rej = state.rejection_count + 1
    logger.info(
        "Routing: WRONG → %s (%s), rejection_count would be %d",
        REVISER_NODE,
        FULL_REWRITE,
        new_rej,
    )
    return RoutingDecision(
        next_node=REVISER_NODE,
        reviser_mode=FULL_REWRITE,
        rejection_increment=1,
    )
