# src/slop_research_factory/engine/routing.py

"""
Verdict routing logic — D-2 §8.4, D-0 §4C, D-0 §8.1.

Determines the next node after Verifier assessment:

  - **Demotion** (D-0 §8.1): CORRECT with sub-threshold

    confidence is demoted to FIXABLE.
  - **Routing** (D-2 §8.4): effective verdict × state limits

    → next node.
  - **Counter mutation**: ``rejection_count`` and

    ``revision_count`` are incremented only when routing to
    the Reviser node.

This module operates on ``FactoryState`` directly.  It makes
no LLM calls, no network requests, and no seal-engine
invocations.

Loop-limit precedence (D-2 §4)::

    1. max_rejections       (WRONG only)
    2. max_revisions        (FIXABLE only)
    3. max_total_tokens / max_total_cost_usd
    4. max_total_cycles

Spec references:
    D-0 §4C   Routing semantics (verdict → next node).
    D-0 §8.1  Composition and demotion.
    D-2 §4    Loop-limit precedence.
    D-2 §8.4  Routing pseudocode.
    D-8 §3.2  E1-R01 through E1-R10 test specifications.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from slop_research_factory.types.enums import Verdict

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
    "compute_effective_verdict",
    "route_after_verification",
]

logger = logging.getLogger(__name__)


# ── Node identifiers ─────────────────────────────────────────────────

FINALIZE_NODE: str = "finalize_manifest"
REVISER_NODE: str = "reviser_node"
HUMAN_RESCUE_NODE: str = "human_rescue_queue"

# ── Reviser modes (D-0 §4C) ─────────────────────────────────────────

TARGETED_REPAIR: str = "targeted_repair"
"""FIXABLE → patch the existing draft."""

FULL_REWRITE: str = "full_rewrite"
"""WRONG → discard draft, regenerate from brief + critique."""

# ── Rescue reasons ───────────────────────────────────────────────────

REASON_MAX_REJECTIONS: str = "max_rejections_exceeded"
REASON_MAX_REVISIONS: str = "max_revisions_exceeded"
REASON_MAX_TOKENS: str = "max_total_tokens_exceeded"
REASON_MAX_COST: str = "max_total_cost_exceeded"
REASON_MAX_CYCLES: str = "max_total_cycles_exceeded"


# ── RoutingDecision ──────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingDecision:
    """Immutable result of the verdict routing logic.

    Spec: D-2 §8.4, D-0 §4C.

    Attributes:
        next_node:     One of :data:`FINALIZE_NODE`,
                       :data:`REVISER_NODE`, or
                       :data:`HUMAN_RESCUE_NODE`.
        reviser_mode:  ``"targeted_repair"`` or ``"full_rewrite"``
                       when *next_node* is the Reviser;
                       ``None`` otherwise.
        rescue_reason: Limit that triggered rescue when
                       *next_node* is the human rescue queue;
                       ``None`` otherwise.
    """

    next_node: str
    reviser_mode: str | None = None
    rescue_reason: str | None = None


# ── Demotion rule (D-0 §8.1) ────────────────────────────────────────

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
    The system fails safe (D-2 §8.4).

    Args:
        verdict:            Raw verdict from the Verifier LLM.
        verdict_confidence: Composed confidence score (0.0–1.0).
        threshold:          Value of
            ``config.verifier_confidence_threshold``.

    Returns:
        Effective verdict after demotion (if any).
    """
    if (
        verdict is Verdict.CORRECT
        and verdict_confidence < threshold
    ):
        logger.info(
            "Demotion: CORRECT confidence %.3f < threshold "
            "%.3f → effective FIXABLE",
            verdict_confidence,
            threshold,
        )
        return Verdict.FIXABLE
    return verdict


# ── Budget / cycle guard (D-2 §4, precedence 3–4) ───────────────────

def _check_budget_and_cycles(
    state: FactoryState,
) -> str | None:
    """Return the rescue reason if a budget or cycle cap is hit.

    Checks follow loop-limit precedence (D-2 §4):

    3. ``max_total_tokens`` / ``max_total_cost_usd``
    4. ``max_total_cycles``

    Returns ``None`` when no cap is breached.
    """
    config = state.config

    # Precedence 3a: token budget
    if config.max_total_tokens is not None:
        consumed = (
            state.total_input_tokens
            + state.total_output_tokens
            + state.total_think_tokens

        )
        if consumed >= config.max_total_tokens:
            return REASON_MAX_TOKENS

    # Precedence 3b: cost budget
    if config.max_total_cost_usd is not None:
        if (
            state.total_estimated_cost_usd
            >= config.max_total_cost_usd
        ):
            return REASON_MAX_COST

    # Precedence 4: absolute cycle cap
    if state.cycle_count >= config.max_total_cycles:
        return REASON_MAX_CYCLES

    return None


# ── Main routing function (D-2 §8.4 pseudocode) ─────────────────────

def route_after_verification(
    state: FactoryState,
    effective_verdict: Verdict,
) -> RoutingDecision:
    """Determine the next node and mutate state counters.

    Counter increments (``rejection_count``,
    ``revision_count``) occur **only** when routing to the
    Reviser.  When routing to human rescue the counters are
    left unchanged so the rescue handler sees the exact
    state that triggered escalation.

    Loop-limit precedence (D-2 §4)::

        1. max_rejections   (WRONG only)
        2. max_revisions    (FIXABLE only)
        3. max_total_tokens / max_total_cost_usd
        4. max_total_cycles

    Args:
        state:             Current ``FactoryState``.
                           **Mutated** when routing to the
                           Reviser (counter increment).
        effective_verdict: Post-demotion verdict from
                           :func:`compute_effective_verdict`.

    Returns:
        Frozen :class:`RoutingDecision`.
    """
    # ── CORRECT → finalize ───────────────────────────────
    if effective_verdict is Verdict.CORRECT:
        logger.info(
            "Routing: CORRECT → %s", FINALIZE_NODE,
        )
        return RoutingDecision(next_node=FINALIZE_NODE)

    # ── FIXABLE ──────────────────────────────────────────
    if effective_verdict is Verdict.FIXABLE:
        return _route_fixable(state)

    # ── WRONG ────────────────────────────────────────────
    # (the only remaining Verdict member)
    return _route_wrong(state)


# ── Per-verdict routing helpers ──────────────────────────────────────

def _route_fixable(state: FactoryState) -> RoutingDecision:
    """Route a FIXABLE verdict (D-2 §8.4, FIXABLE branch)."""
    cfg = state.config

    # Precedence 2: per-verdict revision cap
    if state.revision_count >= cfg.max_revisions:
        logger.info(
            "Routing: FIXABLE → rescue (%s, "
            "revision_count=%d >= max=%d)",
            REASON_MAX_REVISIONS,
            state.revision_count,
            cfg.max_revisions,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=REASON_MAX_REVISIONS,
        )

    # Precedence 3–4: shared budget / cycle checks
    budget_reason = _check_budget_and_cycles(state)
    if budget_reason is not None:
        logger.info(
            "Routing: FIXABLE → rescue (%s)", budget_reason,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=budget_reason,
        )

    # All caps clear → reviser (targeted repair)
    state.revision_count += 1
    logger.info(
        "Routing: FIXABLE → %s (%s), revision_count=%d",
        REVISER_NODE,
        TARGETED_REPAIR,
        state.revision_count,
    )
    return RoutingDecision(
        next_node=REVISER_NODE,
        reviser_mode=TARGETED_REPAIR,
    )


def _route_wrong(state: FactoryState) -> RoutingDecision:
    """Route a WRONG verdict (D-2 §8.4, WRONG branch)."""
    cfg = state.config

    # Precedence 1: per-verdict rejection cap
    if state.rejection_count >= cfg.max_rejections:
        logger.info(
            "Routing: WRONG → rescue (%s, "
            "rejection_count=%d >= max=%d)",
            REASON_MAX_REJECTIONS,
            state.rejection_count,
            cfg.max_rejections,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=REASON_MAX_REJECTIONS,
        )

    # Precedence 3–4: shared budget / cycle checks
    budget_reason = _check_budget_and_cycles(state)
    if budget_reason is not None:
        logger.info(
            "Routing: WRONG → rescue (%s)", budget_reason,
        )
        return RoutingDecision(
            next_node=HUMAN_RESCUE_NODE,
            rescue_reason=budget_reason,
        )

    # All caps clear → reviser (full rewrite)
    state.rejection_count += 1
    logger.info(
        "Routing: WRONG → %s (%s), rejection_count=%d",
        REVISER_NODE,
        FULL_REWRITE,
        state.rejection_count,
    )
    return RoutingDecision(
        next_node=REVISER_NODE,
        reviser_mode=FULL_REWRITE,
    )