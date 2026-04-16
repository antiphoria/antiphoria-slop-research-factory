# tests/unit/test_hai_card.py

"""
Unit tests for types/hai_card.py.

Covers:
  - ModelUsageRecord: construction, validation, frozen.
  - ProcessSummary: construction, validation, frozen.
  - VerificationSummary: construction, validation,

    boundary conditions, frozen.
  - HaiCard: construction, defaults, frozen, hash

    validation, timestamp validation, human-review
    invariant, security guarantee byte-identity,
    disclaimer enforcement, non-negative numerics.

Spec references:
    D-1 §9    Security guarantee.
    D-2 §10   HAI Card schema.
    D-7 §7.4  Human review governance.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slop_research_factory.types.enums import (
    HumanReviewStatus,
    NodeName,
    Verdict,
)
from slop_research_factory.types.hai_card import (
    DEFAULT_DISCLAIMER,
    SECURITY_GUARANTEE,
    HaiCard,
    ModelUsageRecord,
    ProcessSummary,
    VerificationSummary,
)

# ── Constants ────────────────────────────────────────────

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64

TS_1 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
TS_2 = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
TS_NAIVE = datetime(2025, 1, 1, 0, 0, 0)


# ── Helpers ──────────────────────────────────────────────


def _usage(**overrides: object) -> ModelUsageRecord:
    defaults: dict[str, object] = dict(
        model_id="claude-sonnet-4-20250514",
        node_name=NodeName.GENERATOR,
        input_tokens=1000,
        output_tokens=2000,
        call_count=1,
    )
    defaults.update(overrides)
    return ModelUsageRecord(**defaults)  # type: ignore[arg-type]


def _process(**overrides: object) -> ProcessSummary:
    defaults: dict[str, object] = dict(
        total_cycles=2,
        rejection_count=0,
        revision_count=1,
    )
    defaults.update(overrides)
    return ProcessSummary(**defaults)  # type: ignore[arg-type]


def _verification(
    **overrides: object,
) -> VerificationSummary:
    defaults: dict[str, object] = dict(
        final_verdict=Verdict.CORRECT,
        verdict_confidence=0.85,
        tier_reached=2,
        deterministic_passed=5,
        deterministic_total=5,
        citations_verified=3,
        citations_total=5,
    )
    defaults.update(overrides)
    return VerificationSummary(**defaults)  # type: ignore[arg-type]


def _card(**overrides: object) -> HaiCard:
    defaults: dict[str, object] = dict(
        run_id="test-run-001",
        generated_at=TS_1,
        brief_title="Test Research Brief",
        brief_hash=HASH_A,
        models_used=(_usage(),),
        process=_process(),
        verification=_verification(),
        total_seals=4,
        chain_integrity_verified=True,
        final_seal_hash=HASH_B,
        output_hash=HASH_C,
        disclaimer=DEFAULT_DISCLAIMER,
        total_input_tokens=5000,
        total_output_tokens=10000,
        total_estimated_cost_usd=0.25,
        output_license="CC BY 4.0",
        code_license="Apache-2.0",
    )
    defaults.update(overrides)
    return HaiCard(**defaults)  # type: ignore[arg-type]


# ── ModelUsageRecord ─────────────────────────────────────


class TestModelUsageRecord:
    """Construction, validation, immutability."""

    def test_valid_construction(self) -> None:
        m = _usage()
        assert m.model_id == "claude-sonnet-4-20250514"
        assert m.node_name is NodeName.GENERATOR
        assert m.input_tokens == 1000
        assert m.output_tokens == 2000
        assert m.call_count == 1

    def test_zero_tokens_accepted(self) -> None:
        m = _usage(
            input_tokens=0, output_tokens=0, call_count=0,
        )
        assert m.input_tokens == 0

    def test_frozen(self) -> None:
        m = _usage()
        with pytest.raises(AttributeError):
            m.model_id = "other"  # type: ignore[misc]

    def test_empty_model_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="model_id"):
            _usage(model_id="")

    def test_negative_input_tokens_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="input_tokens",
        ):
            _usage(input_tokens=-1)

    def test_negative_output_tokens_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="output_tokens",
        ):
            _usage(output_tokens=-1)

    def test_negative_call_count_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="call_count",
        ):
            _usage(call_count=-1)


# ── ProcessSummary ───────────────────────────────────────


class TestProcessSummary:
    """Construction, validation, immutability."""

    def test_valid_construction(self) -> None:
        p = _process()
        assert p.total_cycles == 2
        assert p.rejection_count == 0
        assert p.revision_count == 1

    def test_all_zeros_accepted(self) -> None:
        p = _process(
            total_cycles=0,
            rejection_count=0,
            revision_count=0,
        )
        assert p.total_cycles == 0

    def test_frozen(self) -> None:
        p = _process()
        with pytest.raises(AttributeError):
            p.total_cycles = 99  # type: ignore[misc]

    def test_negative_total_cycles_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="total_cycles",
        ):
            _process(total_cycles=-1)

    def test_negative_rejection_count_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="rejection_count",
        ):
            _process(rejection_count=-1)

    def test_negative_revision_count_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="revision_count",
        ):
            _process(revision_count=-1)


# ── VerificationSummary ─────────────────────────────────


class TestVerificationSummary:
    """Construction, validation, boundaries."""

    def test_valid_construction(self) -> None:
        v = _verification()
        assert v.final_verdict is Verdict.CORRECT
        assert v.verdict_confidence == 0.85
        assert v.tier_reached == 2

    def test_tier_1_accepted(self) -> None:
        assert _verification(tier_reached=1).tier_reached == 1

    def test_tier_3_accepted(self) -> None:
        assert _verification(tier_reached=3).tier_reached == 3

    def test_tier_0_rejected(self) -> None:
        with pytest.raises(ValueError, match="tier_reached"):
            _verification(tier_reached=0)

    def test_tier_4_rejected(self) -> None:
        with pytest.raises(ValueError, match="tier_reached"):
            _verification(tier_reached=4)

    def test_confidence_0_accepted(self) -> None:
        v = _verification(verdict_confidence=0.0)
        assert v.verdict_confidence == 0.0

    def test_confidence_1_accepted(self) -> None:
        v = _verification(verdict_confidence=1.0)
        assert v.verdict_confidence == 1.0

    def test_confidence_negative_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="verdict_confidence",
        ):
            _verification(verdict_confidence=-0.01)

    def test_confidence_above_1_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="verdict_confidence",
        ):
            _verification(verdict_confidence=1.01)

    def test_deterministic_passed_exceeds_total(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="deterministic_passed",
        ):
            _verification(
                deterministic_passed=6,
                deterministic_total=5,
            )

    def test_citations_verified_exceeds_total(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="citations_verified",
        ):
            _verification(
                citations_verified=6,
                citations_total=5,
            )

    def test_negative_deterministic_passed_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="deterministic_passed",
        ):
            _verification(deterministic_passed=-1)

    def test_negative_deterministic_total_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="deterministic_total",
        ):
            _verification(deterministic_total=-1)

    def test_negative_citations_verified_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="citations_verified",
        ):
            _verification(citations_verified=-1)

    def test_negative_citations_total_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="citations_total",
        ):
            _verification(citations_total=-1)

    def test_zero_citations_accepted(self) -> None:
        """Tier 1 run: no citations extracted or verified."""
        v = _verification(
            citations_verified=0, citations_total=0,
        )
        assert v.citations_total == 0

    def test_frozen(self) -> None:
        v = _verification()
        with pytest.raises(AttributeError):
            v.tier_reached = 3  # type: ignore[misc]


# ── HaiCard: construction ────────────────────────────────


class TestHaiCardConstruction:
    """Valid construction paths."""

    def test_minimal_defaults(self) -> None:
        """All defaulted fields left at defaults."""
        card = _card()
        assert card.run_id == "test-run-001"
        assert card.human_review_status is (
            HumanReviewStatus.UNREVIEWED
        )
        assert card.human_reviewer is None
        assert card.human_review_timestamp is None
        assert card.human_review_notes == ""
        assert card.security_guarantee == SECURITY_GUARANTEE

    def test_full_construction(self) -> None:
        """All fields explicitly set."""
        card = _card(
            human_review_status=HumanReviewStatus.REVIEWED,
            human_reviewer="Dr. A. Reviewer",
            human_review_timestamp=TS_2,
            human_review_notes="Looks correct.",
        )
        assert card.human_review_status is (
            HumanReviewStatus.REVIEWED
        )
        assert card.human_reviewer == "Dr. A. Reviewer"

    def test_multiple_models(self) -> None:
        """Tuple of two ModelUsageRecords."""
        card = _card(
            models_used=(
                _usage(
                    model_id="model-a",
                    node_name=NodeName.GENERATOR,
                ),
                _usage(
                    model_id="model-b",
                    node_name=NodeName.VERIFIER,
                ),
            ),
        )
        assert len(card.models_used) == 2

    def test_zero_cost_accepted(self) -> None:
        card = _card(
            total_input_tokens=0,
            total_output_tokens=0,
            total_estimated_cost_usd=0.0,
        )
        assert card.total_estimated_cost_usd == 0.0


# ── HaiCard: frozen ──────────────────────────────────────


class TestHaiCardFrozen:
    """Immutability enforcement."""

    def test_cannot_reassign_run_id(self) -> None:
        card = _card()
        with pytest.raises(AttributeError):
            card.run_id = "other"  # type: ignore[misc]

    def test_cannot_reassign_review_status(self) -> None:
        card = _card()
        with pytest.raises(AttributeError):
            card.human_review_status = (  # type: ignore[misc]
                HumanReviewStatus.REVIEWED
            )


# ── HaiCard: hash validation ────────────────────────────


class TestHaiCardHashValidation:
    """SHA-256 hash format enforcement."""

    def test_invalid_brief_hash(self) -> None:
        with pytest.raises(ValueError, match="brief_hash"):
            _card(brief_hash="not-hex")

    def test_invalid_final_seal_hash(self) -> None:
        with pytest.raises(
            ValueError, match="final_seal_hash",
        ):
            _card(final_seal_hash="short")

    def test_invalid_output_hash(self) -> None:
        with pytest.raises(
            ValueError, match="output_hash",
        ):
            _card(output_hash="X" * 64)

    def test_short_hash_rejected(self) -> None:
        with pytest.raises(ValueError, match="brief_hash"):
            _card(brief_hash="a" * 63)

    def test_long_hash_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="output_hash",
        ):
            _card(output_hash="b" * 65)


# ── HaiCard: timestamp validation ────────────────────────


class TestHaiCardTimestampValidation:
    """Timezone-awareness enforcement."""

    def test_naive_generated_at_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="generated_at",
        ):
            _card(generated_at=TS_NAIVE)

    def test_naive_review_timestamp_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="human_review_timestamp",
        ):
            _card(
                human_review_status=(
                    HumanReviewStatus.REVIEWED
                ),
                human_reviewer="Dr. X",
                human_review_timestamp=TS_NAIVE,
            )


# ── HaiCard: human review invariant (D-7 §7.4) ─────────


class TestHaiCardHumanReview:
    """REVIEWED requires reviewer + timestamp."""

    def test_unreviewed_default(self) -> None:
        card = _card()
        assert card.human_review_status is (
            HumanReviewStatus.UNREVIEWED
        )

    def test_reviewed_requires_reviewer(self) -> None:
        with pytest.raises(
            ValueError, match="human_reviewer",
        ):
            _card(
                human_review_status=(
                    HumanReviewStatus.REVIEWED
                ),
                human_reviewer=None,
                human_review_timestamp=TS_2,
            )

    def test_reviewed_requires_timestamp(self) -> None:
        with pytest.raises(
            ValueError, match="human_review_timestamp",
        ):
            _card(
                human_review_status=(
                    HumanReviewStatus.REVIEWED
                ),
                human_reviewer="Dr. X",
                human_review_timestamp=None,
            )

    def test_reviewed_with_both_accepted(self) -> None:
        card = _card(
            human_review_status=(
                HumanReviewStatus.REVIEWED
            ),
            human_reviewer="Dr. X",
            human_review_timestamp=TS_2,
        )
        assert card.human_review_status is (
            HumanReviewStatus.REVIEWED
        )

    def test_contested_without_reviewer_accepted(
        self,
    ) -> None:
        """CONTESTED does not enforce reviewer fields."""
        card = _card(
            human_review_status=(
                HumanReviewStatus.CONTESTED
            ),
        )
        assert card.human_review_status is (
            HumanReviewStatus.CONTESTED
        )

    def test_contested_with_reviewer_accepted(
        self,
    ) -> None:
        card = _card(
            human_review_status=(
                HumanReviewStatus.CONTESTED
            ),
            human_reviewer="Dr. Y",
            human_review_timestamp=TS_2,
            human_review_notes="Disagree with methodology.",
        )
        assert card.human_reviewer == "Dr. Y"


# ── HaiCard: security guarantee (D-1 §9) ────────────────


class TestHaiCardSecurityGuarantee:
    """Byte-identity enforcement."""

    def test_default_matches_constant(self) -> None:
        card = _card()
        assert card.security_guarantee == SECURITY_GUARANTEE

    def test_mismatch_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="byte-identical",
        ):
            _card(security_guarantee="wrong text")

    def test_whitespace_diff_rejected(self) -> None:
        """Even a trailing space breaks byte-identity."""
        with pytest.raises(
            ValueError, match="byte-identical",
        ):
            _card(
                security_guarantee=(
                    SECURITY_GUARANTEE + " "
                ),
            )

    def test_empty_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="byte-identical",
        ):
            _card(security_guarantee="")


# ── HaiCard: disclaimer validation ───────────────────────


class TestHaiCardDisclaimerValidation:
    """Non-empty disclaimer enforcement."""

    def test_default_disclaimer_accepted(self) -> None:
        card = _card()
        assert card.disclaimer == DEFAULT_DISCLAIMER

    def test_custom_disclaimer_accepted(self) -> None:
        card = _card(disclaimer="Custom disclaimer.")
        assert card.disclaimer == "Custom disclaimer."

    def test_empty_disclaimer_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="disclaimer",
        ):
            _card(disclaimer="")

    def test_whitespace_only_disclaimer_rejected(
        self,
    ) -> None:
        with pytest.raises(
            ValueError, match="disclaimer",
        ):
            _card(disclaimer="   \t\n  ")


# ── HaiCard: text field validation ───────────────────────


class TestHaiCardTextValidation:
    """Non-empty string field enforcement."""

    def test_empty_run_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="run_id"):
            _card(run_id="")

    def test_empty_brief_title_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="brief_title",
        ):
            _card(brief_title="")

    def test_whitespace_brief_title_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="brief_title",
        ):
            _card(brief_title="   ")

    def test_empty_output_license_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="output_license",
        ):
            _card(output_license="")

    def test_empty_code_license_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="code_license",
        ):
            _card(code_license="")


# ── HaiCard: non-negative numerics ───────────────────────


class TestHaiCardNonNegative:
    """Numeric fields must be >= 0."""

    def test_negative_total_seals_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="total_seals",
        ):
            _card(total_seals=-1)

    def test_negative_input_tokens_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="total_input_tokens",
        ):
            _card(total_input_tokens=-1)

    def test_negative_output_tokens_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="total_output_tokens",
        ):
            _card(total_output_tokens=-1)

    def test_negative_cost_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="total_estimated_cost_usd",
        ):
            _card(total_estimated_cost_usd=-0.01)
