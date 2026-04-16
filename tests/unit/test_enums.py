# tests/unit/test_enums.py

"""
E1 unit tests for types/enums.py — D-8 §3.1.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-S09  All enums serialise to string values via json.dumps(asdict(x)).
  E1-S14  ConfidenceTier.from_score canonical mappings.
  E1-S19  RunStatus illegal transitions raise IllegalTransitionError.
  E1-S20  ConfidenceTier boundary: confidence == 1.0 -> HIGH.
  E1-S21  ConfidenceTier boundary: confidence == 0.0 -> VERY_LOW.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pytest

from slop_research_factory.types.enums import (
    CheckpointBackend,
    CitationCheckResult,
    ConfidenceTier,
    IllegalTransitionError,
    RunStatus,
    StepType,
    Verdict,
    validate_status_transition,
)


# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class _EnumBag:
    """Throwaway dataclass carrying one member of every project enum."""

    verdict: Verdict
    step_type: StepType
    run_status: RunStatus
    citation_result: CitationCheckResult
    confidence_tier: ConfidenceTier
    checkpoint_backend: CheckpointBackend


def _make_bag() -> _EnumBag:
    return _EnumBag(
        verdict=Verdict.CORRECT,
        step_type=StepType.GENESIS,
        run_status=RunStatus.INITIALIZING,
        citation_result=CitationCheckResult.VERIFIED,
        confidence_tier=ConfidenceTier.HIGH,
        checkpoint_backend=CheckpointBackend.SQLITE,
    )


# ── E1-S09  Enum serialisation ──────────────────────────────────────


class TestEnumSerialization:
    """E1-S09: enums serialise to strings; no enum objects in output."""

    def test_json_dumps_succeeds_without_custom_encoder(self) -> None:
        """json.dumps(asdict(bag)) must not raise TypeError."""
        bag = _make_bag()
        serialized = json.dumps(asdict(bag))
        assert isinstance(serialized, str)

    def test_json_roundtrip_values_are_plain_strings(self) -> None:
        """After loads(dumps(...)), every value is a plain str."""
        bag = _make_bag()
        loaded = json.loads(json.dumps(asdict(bag)))
        for key, value in loaded.items():
            assert isinstance(value, str), (
                f"Field '{key}' is {type(value).__name__}"
            )
            assert value == getattr(bag, key).value

    @pytest.mark.parametrize(
        "enum_cls",
        [
            Verdict,
            StepType,
            RunStatus,
            CitationCheckResult,
            ConfidenceTier,
            CheckpointBackend,
        ],
        ids=[
            "Verdict",
            "StepType",
            "RunStatus",
            "CitationCheckResult",
            "ConfidenceTier",
            "CheckpointBackend",
        ],
    )
    def test_every_member_json_serializable(
        self,
        enum_cls: type,
    ) -> None:
        """Each member round-trips through json.dumps to its .value."""
        for member in enum_cls:
            raw = json.dumps(member)
            assert json.loads(raw) == member.value


# ── E1-S14  ConfidenceTier mapping ──────────────────────────────────


class TestConfidenceTierMapping:
    """E1-S14: from_score maps 0.85->HIGH, 0.65->MEDIUM, etc."""

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.85, ConfidenceTier.HIGH),
            (0.65, ConfidenceTier.MEDIUM),
            (0.35, ConfidenceTier.LOW),
            (0.15, ConfidenceTier.VERY_LOW),
        ],
        ids=["0.85-HIGH", "0.65-MEDIUM", "0.35-LOW", "0.15-VERY_LOW"],
    )
    def test_canonical_mappings(
        self,
        score: float,
        expected: ConfidenceTier,
    ) -> None:
        assert ConfidenceTier.from_score(score) is expected

    # Supplementary boundary checks — exercises the exact
    # >= thresholds defined in D-2 §3.5.

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.8, ConfidenceTier.HIGH),
            (0.5, ConfidenceTier.MEDIUM),
            (0.2, ConfidenceTier.LOW),
            (0.79999, ConfidenceTier.MEDIUM),
            (0.49999, ConfidenceTier.LOW),
            (0.19999, ConfidenceTier.VERY_LOW),
        ],
        ids=[
            "0.8-HIGH",
            "0.5-MEDIUM",
            "0.2-LOW",
            "just-below-0.8",
            "just-below-0.5",
            "just-below-0.2",
        ],
    )
    def test_exact_boundaries(
        self,
        score: float,
        expected: ConfidenceTier,
    ) -> None:
        assert ConfidenceTier.from_score(score) is expected

    def test_out_of_range_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="confidence must be"):
            ConfidenceTier.from_score(-0.1)
        with pytest.raises(ValueError, match="confidence must be"):
            ConfidenceTier.from_score(1.1)


# ── E1-S19  RunStatus transitions ───────────────────────────────────


class TestRunStatusTransitions:
    """E1-S19: illegal transitions raise IllegalTransitionError."""

    # ── illegal transitions (representative sample) ──────────────

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            # Terminal states — no outbound edges.
            (RunStatus.COMPLETED, RunStatus.GENERATING),
            (RunStatus.COMPLETED, RunStatus.INITIALIZING),
            (RunStatus.FAILED, RunStatus.GENERATING),
            (RunStatus.FAILED, RunStatus.COMPLETED),
            (RunStatus.NO_OUTPUT, RunStatus.GENERATING),
            (RunStatus.NO_OUTPUT, RunStatus.COMPLETED),
            # Non-terminal illegal transitions.
            (RunStatus.INITIALIZING, RunStatus.VERIFYING),
            (RunStatus.INITIALIZING, RunStatus.REVISING),
            (RunStatus.GENERATING, RunStatus.REVISING),
            (RunStatus.VERIFYING, RunStatus.NO_OUTPUT),
            (RunStatus.FINALIZING, RunStatus.GENERATING),
            (RunStatus.AWAITING_HUMAN, RunStatus.FAILED),
        ],
    )
    def test_illegal_transition_raises(
        self,
        source: RunStatus,
        target: RunStatus,
    ) -> None:
        with pytest.raises(IllegalTransitionError):
            validate_status_transition(source, target)

    # ── legal transitions (complete D-2 §3.3 table) ─────────────

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            # INITIALIZING
            (RunStatus.INITIALIZING, RunStatus.GENERATING),
            (RunStatus.INITIALIZING, RunStatus.FAILED),
            (RunStatus.INITIALIZING, RunStatus.NO_OUTPUT),
            # GENERATING
            (RunStatus.GENERATING, RunStatus.VERIFYING),
            (RunStatus.GENERATING, RunStatus.FAILED),
            (RunStatus.GENERATING, RunStatus.NO_OUTPUT),
            # VERIFYING
            (RunStatus.VERIFYING, RunStatus.REVISING),
            (RunStatus.VERIFYING, RunStatus.AWAITING_HUMAN),
            (RunStatus.VERIFYING, RunStatus.FINALIZING),
            (RunStatus.VERIFYING, RunStatus.FAILED),
            # REVISING
            (RunStatus.REVISING, RunStatus.VERIFYING),
            (RunStatus.REVISING, RunStatus.FAILED),
            (RunStatus.REVISING, RunStatus.NO_OUTPUT),
            # AWAITING_HUMAN
            (RunStatus.AWAITING_HUMAN, RunStatus.GENERATING),
            (RunStatus.AWAITING_HUMAN, RunStatus.REVISING),
            (RunStatus.AWAITING_HUMAN, RunStatus.FINALIZING),
            (RunStatus.AWAITING_HUMAN, RunStatus.NO_OUTPUT),
            # FINALIZING
            (RunStatus.FINALIZING, RunStatus.COMPLETED),
            (RunStatus.FINALIZING, RunStatus.FAILED),
        ],
    )
    def test_legal_transition_succeeds(
        self,
        source: RunStatus,
        target: RunStatus,
    ) -> None:
        """Must not raise — covers all 19 legal edges."""
        validate_status_transition(source, target)

    def test_self_transition_illegal_for_every_status(self) -> None:
        """Diagonal of D-2 §3.3 table is all dashes."""
        for status in RunStatus:
            with pytest.raises(IllegalTransitionError):
                validate_status_transition(status, status)

    def test_terminal_states_have_no_outbound_edges(self) -> None:
        """COMPLETED, FAILED, NO_OUTPUT are sinks (supplementary)."""
        terminals = [
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.NO_OUTPUT,
        ]
        for terminal in terminals:
            for target in RunStatus:
                if target is terminal:
                    continue
                with pytest.raises(IllegalTransitionError):
                    validate_status_transition(terminal, target)

    def test_is_terminal_property(self) -> None:
        """Supplementary: RunStatus.is_terminal matches the three sinks."""
        expected_terminals = {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.NO_OUTPUT,
        }
        for status in RunStatus:
            assert status.is_terminal == (
                status in expected_terminals
            ), (
                f"{status.value}.is_terminal should be "
                f"{status in expected_terminals}"
            )


# ── E1-S20  ConfidenceTier upper boundary ────────────────────────────


class TestConfidenceTierUpperBound:
    """E1-S20: confidence == 1.0 maps to HIGH."""

    def test_one_maps_to_high(self) -> None:
        assert ConfidenceTier.from_score(1.0) is ConfidenceTier.HIGH


# ── E1-S21  ConfidenceTier lower boundary ────────────────────────────


class TestConfidenceTierLowerBound:
    """E1-S21: confidence == 0.0 maps to VERY_LOW."""

    def test_zero_maps_to_very_low(self) -> None:
        assert ConfidenceTier.from_score(0.0) is ConfidenceTier.VERY_LOW
