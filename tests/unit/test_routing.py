# tests/unit/test_routing.py

"""
E1 unit tests for engine/routing.py — D-8 §3.2.

No LLM calls, no network, no filesystem side-effects.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-R01  CORRECT above threshold → finalize_manifest.
  E1-R02  CORRECT below threshold → demote FIXABLE → reviser.
  E1-R03  FIXABLE → reviser_node, increment revision_count.
  E1-R04  WRONG below max → reviser_node, increment rejection_count.
  E1-R05  WRONG at max_rejections → human_rescue_queue.
  E1-R06  FIXABLE at max_revisions → human_rescue_queue.
  E1-R07  cycle_count >= max_total_cycles → rescue (both verdicts).
  E1-R08  Composite: two FIXABLE at max_revisions=1 → rescue on 2nd.
  E1-R09  Composite: total cycle cap fires before revision cap.
  E1-R10  Composite: per-cap ordered before total cycle cap.
"""

from __future__ import annotations

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.engine.routing import (
    FINALIZE_NODE,
    FULL_REWRITE,
    HUMAN_RESCUE_NODE,
    REASON_MAX_COST,
    REASON_MAX_CYCLES,
    REASON_MAX_REJECTIONS,
    REASON_MAX_REVISIONS,
    REASON_MAX_TOKENS,
    REVISER_NODE,
    TARGETED_REPAIR,
    compute_effective_verdict,
    route_after_verification,
)
from slop_research_factory.types.enums import RunStatus, Verdict
from slop_research_factory.types.state import FactoryState


# ── Helper ───────────────────────────────────────────────────────────


def _make_state(
    *,
    rejection_count: int = 0,
    revision_count: int = 0,
    cycle_count: int = 0,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    total_think_tokens: int = 0,
    total_estimated_cost_usd: float = 0.0,
    max_rejections: int = 3,
    max_revisions: int = 5,
    max_total_cycles: int = 10,
    max_total_tokens: int | None = None,
    max_total_cost_usd: float | None = None,
) -> FactoryState:
    """Build a ``FactoryState`` with routing-relevant fields."""
    config = FactoryConfig(
        max_rejections=max_rejections,
        max_revisions=max_revisions,
        max_total_cycles=max_total_cycles,
        max_total_tokens=max_total_tokens,
        max_total_cost_usd=max_total_cost_usd,
    )
    return FactoryState(
        run_id="test-routing-00000000",
        status=RunStatus.VERIFYING,
        config=config,
        brief={"thesis": "Test thesis"},
        step_index=0,
        latest_hash="",
        rejection_count=rejection_count,
        revision_count=revision_count,
        cycle_count=cycle_count,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_think_tokens=total_think_tokens,
        total_estimated_cost_usd=total_estimated_cost_usd,
    )


# ── E1-R01 / E1-R02: Demotion rule (D-0 §8.1) ──────────────────────


class TestComputeEffectiveVerdict:
    """Demotion: CORRECT below threshold → FIXABLE."""

    def test_r01_correct_above_threshold(self) -> None:
        """CORRECT, confidence=0.85, threshold=0.8 → CORRECT."""
        result = compute_effective_verdict(
            Verdict.CORRECT, 0.85, 0.8,
        )
        assert result is Verdict.CORRECT

    def test_r02_correct_below_threshold(self) -> None:
        """CORRECT, confidence=0.7, threshold=0.8 → FIXABLE."""
        result = compute_effective_verdict(
            Verdict.CORRECT, 0.7, 0.8,
        )
        assert result is Verdict.FIXABLE

    def test_correct_at_exact_threshold_stays(self) -> None:
        """Boundary: confidence == threshold → no demotion."""
        result = compute_effective_verdict(
            Verdict.CORRECT, 0.8, 0.8,
        )
        assert result is Verdict.CORRECT

    def test_fixable_never_promoted(self) -> None:
        """FIXABLE stays FIXABLE regardless of confidence."""
        for conf in (0.0, 0.5, 0.99, 1.0):
            result = compute_effective_verdict(
                Verdict.FIXABLE, conf, 0.8,
            )
            assert result is Verdict.FIXABLE

    def test_wrong_never_promoted(self) -> None:
        """WRONG stays WRONG regardless of confidence.

        D-2 §8.4: no promotion rule for WRONG.
        """
        for conf in (0.0, 0.5, 0.99, 1.0):
            result = compute_effective_verdict(
                Verdict.WRONG, conf, 0.8,
            )
            assert result is Verdict.WRONG


# ── E1-R01: CORRECT → finalize ───────────────────────────────────────


class TestRoutingCorrect:
    """CORRECT effective verdict → finalize_manifest."""

    def test_r01_correct_routes_to_finalize(self) -> None:
        """E1-R01: CORRECT confidence=0.85 threshold=0.8."""
        effective = compute_effective_verdict(
            Verdict.CORRECT, 0.85, 0.8,
        )
        assert effective is Verdict.CORRECT

        state = _make_state()
        decision = route_after_verification(state, effective)

        assert decision.next_node == FINALIZE_NODE
        assert decision.reviser_mode is None
        assert decision.rescue_reason is None

    def test_correct_ignores_high_cycle_count(self) -> None:
        """CORRECT always finalizes, even at max cycles."""
        state = _make_state(cycle_count=999, max_total_cycles=10)
        decision = route_after_verification(
            state, Verdict.CORRECT,
        )
        assert decision.next_node == FINALIZE_NODE


# ── E1-R02: Demoted CORRECT → reviser ───────────────────────────────


class TestRoutingDemotedCorrect:
    """Demoted CORRECT (→ FIXABLE) routes to reviser."""

    def test_r02_demoted_correct_to_reviser(self) -> None:
        """E1-R02: confidence=0.7 threshold=0.8 → reviser."""
        effective = compute_effective_verdict(
            Verdict.CORRECT, 0.7, 0.8,
        )
        assert effective is Verdict.FIXABLE

        state = _make_state()
        decision = route_after_verification(state, effective)

        assert decision.next_node == REVISER_NODE
        assert decision.reviser_mode == TARGETED_REPAIR
        assert state.revision_count == 1


# ── E1-R03 / E1-R06: FIXABLE routing ────────────────────────────────


class TestRoutingFixable:
    """FIXABLE verdict: reviser or rescue."""

    def test_r03_fixable_routes_to_reviser(self) -> None:
        """E1-R03: FIXABLE with headroom → targeted repair."""
        state = _make_state()
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == REVISER_NODE
        assert decision.reviser_mode == TARGETED_REPAIR

    def test_r03_fixable_increments_revision_count(
        self,
    ) -> None:
        """E1-R03: revision_count incremented on reviser route."""
        state = _make_state(revision_count=0)
        route_after_verification(state, Verdict.FIXABLE)
        assert state.revision_count == 1

    def test_r06_fixable_at_max_revisions(self) -> None:
        """E1-R06: revision_count >= max_revisions → rescue."""
        state = _make_state(
            revision_count=5, max_revisions=5,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_REVISIONS

    def test_r06_revision_count_unchanged_on_rescue(
        self,
    ) -> None:
        """Counter NOT incremented when routing to rescue."""
        state = _make_state(
            revision_count=5, max_revisions=5,
        )
        route_after_verification(state, Verdict.FIXABLE)
        assert state.revision_count == 5


# ── E1-R04 / E1-R05: WRONG routing ──────────────────────────────────


class TestRoutingWrong:
    """WRONG verdict: reviser (full rewrite) or rescue."""

    def test_r04_wrong_routes_to_reviser(self) -> None:
        """E1-R04: WRONG with headroom → full rewrite."""
        state = _make_state()
        decision = route_after_verification(
            state, Verdict.WRONG,
        )
        assert decision.next_node == REVISER_NODE
        assert decision.reviser_mode == FULL_REWRITE

    def test_r04_wrong_increments_rejection_count(
        self,
    ) -> None:
        """E1-R04: rejection_count incremented on reviser route."""
        state = _make_state(rejection_count=0)
        route_after_verification(state, Verdict.WRONG)
        assert state.rejection_count == 1

    def test_r05_wrong_at_max_rejections(self) -> None:
        """E1-R05: rejection_count >= max_rejections → rescue."""
        state = _make_state(
            rejection_count=3, max_rejections=3,
        )
        decision = route_after_verification(
            state, Verdict.WRONG,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_REJECTIONS

    def test_r05_rejection_count_unchanged_on_rescue(
        self,
    ) -> None:
        """Counter NOT incremented when routing to rescue."""
        state = _make_state(
            rejection_count=3, max_rejections=3,
        )
        route_after_verification(state, Verdict.WRONG)
        assert state.rejection_count == 3


# ── E1-R07: cycle cap ────────────────────────────────────────────────


class TestCycleCapRouting:
    """cycle_count >= max_total_cycles → rescue for any verdict."""

    def test_r07_fixable_with_cycle_cap(self) -> None:
        """FIXABLE + cycle cap hit → rescue."""
        state = _make_state(
            cycle_count=10, max_total_cycles=10,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_CYCLES

    def test_r07_wrong_with_cycle_cap(self) -> None:
        """WRONG + cycle cap hit → rescue."""
        state = _make_state(
            cycle_count=10, max_total_cycles=10,
        )
        decision = route_after_verification(
            state, Verdict.WRONG,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_CYCLES

    def test_r07_counters_unchanged_on_cycle_rescue(
        self,
    ) -> None:
        """Neither counter is incremented when cycle cap fires."""
        state = _make_state(
            cycle_count=10,
            max_total_cycles=10,
            rejection_count=0,
            revision_count=0,
        )
        route_after_verification(state, Verdict.FIXABLE)
        assert state.revision_count == 0
        route_after_verification(
            _make_state(
                cycle_count=10,
                max_total_cycles=10,
            ),
            Verdict.WRONG,
        )


# ── E1-R08 / E1-R09 / E1-R10: composite scenarios ──────────────────


class TestCompositeRouting:
    """Multi-step and precedence-ordering scenarios."""

    def test_r08_two_fixable_at_max_revisions_1(self) -> None:
        """E1-R08: max_revisions=1 → 1st FIXABLE passes,
        2nd triggers rescue.

        Sequence on the SAME state object:
          1st FIXABLE: revision_count 0 < 1 → reviser (count→1)
          2nd FIXABLE: revision_count 1 >= 1 → rescue
        """
        state = _make_state(
            max_rejections=1,
            max_revisions=1,
            max_total_cycles=10,
        )

        # 1st FIXABLE
        d1 = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert d1.next_node == REVISER_NODE
        assert d1.reviser_mode == TARGETED_REPAIR
        assert state.revision_count == 1

        # 2nd FIXABLE on the same (mutated) state
        d2 = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert d2.next_node == HUMAN_RESCUE_NODE
        assert d2.rescue_reason == REASON_MAX_REVISIONS

    def test_r09_cycle_cap_before_revision_cap(self) -> None:
        """E1-R09: max_total_cycles=3 fires even though
        revision_count (2) is still below max_revisions (5).
        """
        state = _make_state(
            cycle_count=3,
            revision_count=2,
            max_rejections=3,
            max_revisions=5,
            max_total_cycles=3,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_CYCLES

    def test_r10_per_cap_ordered_before_cycle_cap(
        self,
    ) -> None:
        """E1-R10: max_revisions=1 fires before
        max_total_cycles=100 (per-cap has higher precedence).

        State simulates two prior cycles:
          cycle 1 — WRONG  (rejection_count → 1)
          cycle 2 — FIXABLE (revision_count → 1)
        Now a 3rd FIXABLE hits revision cap first.
        """
        state = _make_state(
            rejection_count=1,
            revision_count=1,
            cycle_count=2,
            max_rejections=1,
            max_revisions=1,
            max_total_cycles=100,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_REVISIONS

    def test_r10_precedence_when_both_caps_breached(
        self,
    ) -> None:
        """Supplementary: when BOTH revision cap AND cycle cap
        are breached, the per-verdict cap reason is recorded
        (higher precedence per D-2 §4).
        """
        state = _make_state(
            revision_count=5,
            cycle_count=10,
            max_revisions=5,
            max_total_cycles=10,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_REVISIONS


# ── Budget cap routing (supplementary) ───────────────────────────────


class TestBudgetCapRouting:
    """Token and cost budget caps (D-2 §4, precedence 3)."""

    def test_token_budget_triggers_rescue_fixable(
        self,
    ) -> None:
        """max_total_tokens breached → rescue for FIXABLE."""
        state = _make_state(
            total_input_tokens=400_000,
            total_output_tokens=200_000,
            max_total_tokens=500_000,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_TOKENS

    def test_token_budget_triggers_rescue_wrong(
        self,
    ) -> None:
        """max_total_tokens breached → rescue for WRONG."""
        state = _make_state(
            total_input_tokens=300_000,
            total_output_tokens=300_000,
            max_total_tokens=500_000,
        )
        decision = route_after_verification(
            state, Verdict.WRONG,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_TOKENS

    def test_cost_budget_triggers_rescue(self) -> None:
        """max_total_cost_usd breached → rescue."""
        state = _make_state(
            total_estimated_cost_usd=5.50,
            max_total_cost_usd=5.00,
        )
        decision = route_after_verification(
            state, Verdict.WRONG,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_COST

    def test_token_precedence_over_cycle_cap(self) -> None:
        """Token budget has higher precedence than cycle cap."""
        state = _make_state(
            total_input_tokens=300_000,
            total_output_tokens=300_000,
            max_total_tokens=500_000,
            cycle_count=10,
            max_total_cycles=10,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.rescue_reason == REASON_MAX_TOKENS

    def test_per_cap_precedence_over_token_budget(
        self,
    ) -> None:
        """Per-verdict cap has higher precedence than tokens."""
        state = _make_state(
            revision_count=5,
            max_revisions=5,
            total_input_tokens=600_000,
            total_output_tokens=0,
            max_total_tokens=500_000,
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.rescue_reason == REASON_MAX_REVISIONS

    def test_budget_not_checked_when_none(self) -> None:
        """No rescue when budget caps are None (default)."""
        state = _make_state(
            total_input_tokens=999_999,
            total_output_tokens=999_999,
            total_estimated_cost_usd=999.0,
            # max_total_tokens=None (default)
            # max_total_cost_usd=None (default)
        )
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == REVISER_NODE

    def test_think_tokens_counted_in_budget(self) -> None:
        """Think tokens push total over budget cap."""
        state = _make_state(
            total_input_tokens=200_000,
            total_output_tokens=200_000,
            total_think_tokens=200_000,
            max_total_tokens=500_000,
        )
        # input+output = 400k (under), but +think = 600k (over)
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == HUMAN_RESCUE_NODE
        assert decision.rescue_reason == REASON_MAX_TOKENS

    def test_think_tokens_under_budget_still_routes(self) -> None:
        """All three token types summed but under cap → reviser."""
        state = _make_state(
            total_input_tokens=100_000,
            total_output_tokens=100_000,
            total_think_tokens=100_000,
            max_total_tokens=500_000,
        )
        # total = 300k < 500k → no rescue
        decision = route_after_verification(
            state, Verdict.FIXABLE,
        )
        assert decision.next_node == REVISER_NODE


# ── RoutingDecision dataclass (supplementary) ────────────────────────


class TestRoutingDecisionFrozen:
    """RoutingDecision is a frozen dataclass."""

    def test_frozen(self) -> None:
        d = route_after_verification(
            _make_state(), Verdict.CORRECT,
        )
        with pytest.raises(AttributeError):
            d.next_node = "other"  # type: ignore[misc]
