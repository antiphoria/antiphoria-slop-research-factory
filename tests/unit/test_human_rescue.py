# tests/unit/test_human_rescue.py

"""
Unit tests for types/human_rescue.py.

Covers:
  - HumanRescueRequest: construction, validation,

    immutability, optional field handling.
  - HumanRescueResolution: construction, validation,

    immutability, action-specific invariants.

Spec references:
    D-2 §12    Human rescue schema.
    D-5 §5.5   Human gate node contract.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slop_research_factory.types.enums import (
    HumanRescueAction,
    NodeName,
    Verdict,
)
from slop_research_factory.types.human_rescue import (
    HumanRescueRequest,
    HumanRescueResolution,
)

# ── Constants ────────────────────────────────────────────

HASH_A = "a" * 64
HASH_B = "b" * 64

TS_1 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
TS_2 = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
TS_NAIVE = datetime(2025, 1, 1, 0, 0, 0)

REASON_MAX_REJ = "max_rejections_exceeded"
REASON_MAX_REV = "max_revisions_exceeded"
REASON_MAX_CYC = "max_total_cycles_exceeded"


# ── Helpers ──────────────────────────────────────────────


def _request(**overrides: object) -> HumanRescueRequest:
    defaults: dict[str, object] = dict(
        request_id="req-001",
        run_id="run-001",
        created_at=TS_1,
        rescue_reason=REASON_MAX_REJ,
        node_name=NodeName.VERIFICATION,
        step_index=4,
        cycle_count=3,
        rejection_count=3,
        revision_count=1,
        brief_title="Test Brief",
        summary="WRONG verdict exceeded max_rejections.",
    )
    defaults.update(overrides)
    return HumanRescueRequest(**defaults)  # type: ignore[arg-type]


def _resolution(**overrides: object) -> HumanRescueResolution:
    defaults: dict[str, object] = dict(
        request_id="req-001",
        resolved_at=TS_2,
        resolver_id="reviewer@example.com",
        action=HumanRescueAction.APPROVE_OUTPUT,
    )
    defaults.update(overrides)
    return HumanRescueResolution(**defaults)  # type: ignore[arg-type]


# ── HumanRescueRequest: construction ────────────────────


class TestHumanRescueRequestConstruction:
    """Valid construction paths."""

    def test_minimal_required_fields(self) -> None:
        req = _request()
        assert req.request_id == "req-001"
        assert req.run_id == "run-001"
        assert req.created_at == TS_1
        assert req.rescue_reason == REASON_MAX_REJ
        assert req.node_name is NodeName.VERIFICATION
        assert req.step_index == 4
        assert req.cycle_count == 3
        assert req.rejection_count == 3
        assert req.revision_count == 1
        assert req.brief_title == "Test Brief"
        assert req.summary.startswith("WRONG")

    def test_defaults_for_optional_fields(self) -> None:
        req = _request()
        assert req.latest_verdict is None
        assert req.verdict_confidence is None
        assert req.latest_seal_hash is None

    def test_full_construction(self) -> None:
        req = _request(
            latest_verdict=Verdict.WRONG,
            verdict_confidence=0.92,
            latest_seal_hash=HASH_A,
        )
        assert req.latest_verdict is Verdict.WRONG
        assert req.verdict_confidence == 0.92
        assert req.latest_seal_hash == HASH_A

    def test_fixable_verdict_accepted(self) -> None:
        req = _request(
            latest_verdict=Verdict.FIXABLE,
            rescue_reason=REASON_MAX_REV,
        )
        assert req.latest_verdict is Verdict.FIXABLE

    def test_zero_counts_accepted(self) -> None:
        req = _request(
            step_index=0,
            cycle_count=0,
            rejection_count=0,
            revision_count=0,
        )
        assert req.step_index == 0
        assert req.cycle_count == 0

    def test_confidence_boundaries(self) -> None:
        assert _request(
            verdict_confidence=0.0,
        ).verdict_confidence == 0.0
        assert _request(
            verdict_confidence=1.0,
        ).verdict_confidence == 1.0


# ── HumanRescueRequest: frozen ───────────────────────────


class TestHumanRescueRequestFrozen:
    """Immutability enforcement."""

    def test_cannot_reassign_request_id(self) -> None:
        req = _request()
        with pytest.raises(AttributeError):
            req.request_id = "other"  # type: ignore[misc]

    def test_cannot_reassign_rescue_reason(self) -> None:
        req = _request()
        with pytest.raises(AttributeError):
            req.rescue_reason = "x"  # type: ignore[misc]

    def test_cannot_reassign_latest_verdict(self) -> None:
        req = _request(latest_verdict=Verdict.WRONG)
        with pytest.raises(AttributeError):
            req.latest_verdict = (  # type: ignore[misc]
                Verdict.CORRECT
            )


# ── HumanRescueRequest: validation ───────────────────────


class TestHumanRescueRequestValidation:
    """Field validation at construction."""

    def test_empty_request_id_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="request_id",
        ):
            _request(request_id="")

    def test_empty_run_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="run_id"):
            _request(run_id="")

    def test_empty_rescue_reason_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="rescue_reason",
        ):
            _request(rescue_reason="")

    def test_empty_brief_title_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="brief_title",
        ):
            _request(brief_title="")

    def test_whitespace_brief_title_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="brief_title",
        ):
            _request(brief_title="   \t\n  ")

    def test_empty_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            _request(summary="")

    def test_whitespace_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="summary"):
            _request(summary="   ")

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="created_at",
        ):
            _request(created_at=TS_NAIVE)

    def test_negative_step_index_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="step_index",
        ):
            _request(step_index=-1)

    def test_negative_cycle_count_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="cycle_count",
        ):
            _request(cycle_count=-1)

    def test_negative_rejection_count_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="rejection_count",
        ):
            _request(rejection_count=-1)

    def test_negative_revision_count_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="revision_count",
        ):
            _request(revision_count=-1)

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="verdict_confidence",
        ):
            _request(verdict_confidence=-0.01)

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="verdict_confidence",
        ):
            _request(verdict_confidence=1.01)

    def test_invalid_seal_hash_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="latest_seal_hash",
        ):
            _request(latest_seal_hash="not-a-hash")

    def test_uppercase_seal_hash_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="latest_seal_hash",
        ):
            _request(latest_seal_hash="A" * 64)

    def test_short_seal_hash_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="latest_seal_hash",
        ):
            _request(latest_seal_hash="a" * 63)


# ── HumanRescueResolution: construction ──────────────────


class TestHumanRescueResolutionConstruction:
    """Valid construction paths per action type."""

    def test_approve_output(self) -> None:
        res = _resolution(
            action=HumanRescueAction.APPROVE_OUTPUT,
        )
        assert res.action is HumanRescueAction.APPROVE_OUTPUT
        assert res.request_id == "req-001"
        assert res.resolver_id == "reviewer@example.com"

    def test_reject_and_abort(self) -> None:
        res = _resolution(
            action=HumanRescueAction.REJECT_AND_ABORT,
            notes="Methodology fundamentally flawed.",
        )
        assert res.action is (
            HumanRescueAction.REJECT_AND_ABORT
        )
        assert res.notes == "Methodology fundamentally flawed."

    def test_revise_and_continue(self) -> None:
        res = _resolution(
            action=HumanRescueAction.REVISE_AND_CONTINUE,
            notes="Edited draft section 3.",
        )
        assert res.action is (
            HumanRescueAction.REVISE_AND_CONTINUE
        )

    def test_increase_limits_single(self) -> None:
        res = _resolution(
            action=HumanRescueAction.INCREASE_LIMITS,
            revised_max_rejections=5,
        )
        assert res.action is (
            HumanRescueAction.INCREASE_LIMITS
        )
        assert res.revised_max_rejections == 5

    def test_increase_limits_multiple(self) -> None:
        res = _resolution(
            action=HumanRescueAction.INCREASE_LIMITS,
            revised_max_rejections=5,
            revised_max_revisions=10,
            revised_max_total_cycles=20,
            revised_max_total_tokens=1_000_000,
            revised_max_total_cost_usd=10.0,
        )
        assert res.revised_max_total_cycles == 20
        assert res.revised_max_total_cost_usd == 10.0

    def test_provide_guidance(self) -> None:
        res = _resolution(
            action=HumanRescueAction.PROVIDE_GUIDANCE,
            guidance="Focus on methodology section.",
        )
        assert res.action is (
            HumanRescueAction.PROVIDE_GUIDANCE
        )
        assert res.guidance == "Focus on methodology section."

    def test_defaults_for_optional_fields(self) -> None:
        res = _resolution()
        assert res.notes == ""
        assert res.guidance == ""
        assert res.revised_max_rejections is None
        assert res.revised_max_revisions is None
        assert res.revised_max_total_cycles is None
        assert res.revised_max_total_tokens is None
        assert res.revised_max_total_cost_usd is None

    def test_zero_revised_limits_accepted(self) -> None:
        """Zero is valid (means 'no tolerance')."""
        res = _resolution(
            action=HumanRescueAction.INCREASE_LIMITS,
            revised_max_rejections=0,
        )
        assert res.revised_max_rejections == 0

    def test_zero_cost_accepted(self) -> None:
        res = _resolution(
            action=HumanRescueAction.INCREASE_LIMITS,
            revised_max_total_cost_usd=0.0,
        )
        assert res.revised_max_total_cost_usd == 0.0


# ── HumanRescueResolution: frozen ────────────────────────


class TestHumanRescueResolutionFrozen:
    """Immutability enforcement."""

    def test_cannot_reassign_action(self) -> None:
        res = _resolution()
        with pytest.raises(AttributeError):
            res.action = (  # type: ignore[misc]
                HumanRescueAction.REJECT_AND_ABORT
            )

    def test_cannot_reassign_resolver_id(self) -> None:
        res = _resolution()
        with pytest.raises(AttributeError):
            res.resolver_id = "other"  # type: ignore[misc]


# ── HumanRescueResolution: basic validation ──────────────


class TestHumanRescueResolutionValidation:
    """Field validation at construction."""

    def test_empty_request_id_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="request_id",
        ):
            _resolution(request_id="")

    def test_empty_resolver_id_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="resolver_id",
        ):
            _resolution(resolver_id="")

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="resolved_at",
        ):
            _resolution(resolved_at=TS_NAIVE)

    def test_negative_revised_rejections_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="revised_max_rejections",
        ):
            _resolution(
                action=HumanRescueAction.INCREASE_LIMITS,
                revised_max_rejections=-1,
            )

    def test_negative_revised_revisions_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="revised_max_revisions",
        ):
            _resolution(
                action=HumanRescueAction.INCREASE_LIMITS,
                revised_max_revisions=-1,
            )

    def test_negative_revised_cycles_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="revised_max_total_cycles",
        ):
            _resolution(
                action=HumanRescueAction.INCREASE_LIMITS,
                revised_max_total_cycles=-1,
            )

    def test_negative_revised_tokens_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="revised_max_total_tokens",
        ):
            _resolution(
                action=HumanRescueAction.INCREASE_LIMITS,
                revised_max_total_tokens=-1,
            )

    def test_negative_revised_cost_rejected(self) -> None:
        with pytest.raises(
            ValueError,
            match="revised_max_total_cost_usd",
        ):
            _resolution(
                action=HumanRescueAction.INCREASE_LIMITS,
                revised_max_total_cost_usd=-0.01,
            )


# ── HumanRescueResolution: action-specific invariants ────


class TestHumanRescueResolutionActionInvariants:
    """INCREASE_LIMITS and PROVIDE_GUIDANCE constraints."""

    def test_increase_limits_no_revised_fields_rejected(
        self,
    ) -> None:
        """INCREASE_LIMITS with no revised_* → ValueError."""
        with pytest.raises(
            ValueError, match="revised_",
        ):
            _resolution(
                action=HumanRescueAction.INCREASE_LIMITS,
            )

    def test_increase_limits_with_one_field_accepted(
        self,
    ) -> None:
        res = _resolution(
            action=HumanRescueAction.INCREASE_LIMITS,
            revised_max_total_cycles=15,
        )
        assert res.revised_max_total_cycles == 15

    def test_increase_limits_cost_only_accepted(
        self,
    ) -> None:
        res = _resolution(
            action=HumanRescueAction.INCREASE_LIMITS,
            revised_max_total_cost_usd=20.0,
        )
        assert res.revised_max_total_cost_usd == 20.0

    def test_provide_guidance_empty_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="guidance",
        ):
            _resolution(
                action=HumanRescueAction.PROVIDE_GUIDANCE,
                guidance="",
            )

    def test_provide_guidance_whitespace_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="guidance",
        ):
            _resolution(
                action=HumanRescueAction.PROVIDE_GUIDANCE,
                guidance="   \t\n  ",
            )

    def test_provide_guidance_with_text_accepted(
        self,
    ) -> None:
        res = _resolution(
            action=HumanRescueAction.PROVIDE_GUIDANCE,
            guidance="Strengthen the literature review.",
        )
        assert res.guidance.startswith("Strengthen")

    def test_approve_output_ignores_revised_fields(
        self,
    ) -> None:
        """Non-INCREASE_LIMITS actions accept revised_* fields
        without error (they are simply ignored by the
        orchestrator).
        """
        res = _resolution(
            action=HumanRescueAction.APPROVE_OUTPUT,
            revised_max_rejections=99,
        )
        assert res.revised_max_rejections == 99

    def test_reject_and_abort_ignores_guidance(
        self,
    ) -> None:
        """Non-PROVIDE_GUIDANCE actions accept guidance text
        without error.
        """
        res = _resolution(
            action=HumanRescueAction.REJECT_AND_ABORT,
            guidance="This is ignored.",
        )
        assert res.guidance == "This is ignored."

    def test_revise_and_continue_no_extras_needed(
        self,
    ) -> None:
        """REVISE_AND_CONTINUE requires no special fields."""
        res = _resolution(
            action=HumanRescueAction.REVISE_AND_CONTINUE,
        )
        assert res.action is (
            HumanRescueAction.REVISE_AND_CONTINUE
        )
