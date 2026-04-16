# tests/unit/test_verifier_output.py

"""
E1 unit tests for types/verifier_output.py — D-2 §8.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-S07  VerifierOutput round-trip (D-2 §16 invariant 3).
  E1-S08  VerifierOutput JSON Schema (D-2 §16 invariant 4).
  E1-S16  Invalid verdict string rejected (D-2 §16 invariant 11).
  E1-S17  CORRECT + empty critique_entries valid.
  E1-S18  Non-CORRECT + empty critique rejected (D-3 §4.5).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from slop_research_factory.types.enums import Verdict
from slop_research_factory.types.verifier_output import (
    VerifierOutput,
)


# ── Helper ──────────────────────────────────────────────────────────


def _make_verifier_output_data(
    **overrides: Any,
) -> dict[str, Any]:
    """Return a dict of valid VerifierOutput fields.

    Defaults to a CORRECT verdict with empty critique_entries,
    which is the simplest valid state.  Pass keyword arguments
    to override any field.
    """
    base: dict[str, Any] = {
        "critique_summary": "No issues found.",
        "critique_entries": [],
        "verdict": "CORRECT",
        "resolution_type": "explanation",
        "verdict_confidence": 0.9,
        "resolution": "The draft meets publication standards.",
        "confidence_logical_soundness": 0.6,
        "confidence_mathematical_rigor": 0.5,
        "confidence_citation_accuracy": 0.9,
        "confidence_scope_compliance": 0.8,
        "confidence_novelty_plausibility": 0.3,
    }
    base.update(overrides)
    return base


# ── E1-S07 ──────────────────────────────────────────────────────────


class TestE1S07VerifierOutputRoundTrip:
    """VerifierOutput round-trips through Pydantic JSON
    serialization: model_dump_json → model_validate_json.

    D-2 §16 Invariant 3.
    """

    def test_correct_verdict_round_trips(self) -> None:
        data = _make_verifier_output_data()
        original = VerifierOutput(**data)
        json_str = original.model_dump_json()
        restored = VerifierOutput.model_validate_json(json_str)
        assert original == restored

    def test_fixable_verdict_with_critique_round_trips(
        self,
    ) -> None:
        data = _make_verifier_output_data(
            verdict="FIXABLE",
            critique_entries=[
                {
                    "category": "logical_gap",
                    "severity": "major",
                    "description": "Step 2 is unjustified.",
                },
            ],
            resolution_type="remediation_plan",
        )
        original = VerifierOutput(**data)
        json_str = original.model_dump_json()
        restored = VerifierOutput.model_validate_json(json_str)
        assert original == restored

    def test_wrong_verdict_with_critique_round_trips(
        self,
    ) -> None:
        data = _make_verifier_output_data(
            verdict="WRONG",
            critique_entries=[
                {
                    "category": "mathematical_error",
                    "severity": "critical",
                    "description": "Fatal flaw in the proof.",
                },
            ],
            resolution_type="explanation",
        )
        original = VerifierOutput(**data)
        json_str = original.model_dump_json()
        restored = VerifierOutput.model_validate_json(json_str)
        assert original == restored


# ── E1-S08 ──────────────────────────────────────────────────────────


class TestE1S08VerifierOutputJsonSchema:
    """VerifierOutput.model_json_schema() produces a valid
    JSON Schema containing all expected fields.

    D-2 §16 Invariant 4.
    """

    EXPECTED_FIELDS: frozenset[str] = frozenset({
        "critique_summary",
        "critique_entries",
        "verdict",
        "resolution_type",
        "verdict_confidence",
        "resolution",
        "confidence_logical_soundness",
        "confidence_mathematical_rigor",
        "confidence_citation_accuracy",
        "confidence_scope_compliance",
        "confidence_novelty_plausibility",
    })

    def test_schema_is_object_type(self) -> None:
        schema = VerifierOutput.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema

    def test_schema_contains_all_fields(self) -> None:
        schema = VerifierOutput.model_json_schema()
        actual = set(schema["properties"].keys())
        missing = self.EXPECTED_FIELDS - actual
        assert not missing, (
            f"Missing fields in JSON Schema: {missing}"
        )

    def test_all_fields_are_required(self) -> None:
        """Every VerifierOutput field lacks a default, so all
        must appear in the schema ``required`` list."""
        schema = VerifierOutput.model_json_schema()
        required = set(schema.get("required", []))
        not_required = self.EXPECTED_FIELDS - required
        assert not not_required, (
            f"Fields not marked required: {not_required}"
        )


# ── E1-S16 ──────────────────────────────────────────────────────────


class TestE1S16VerifierOutputRejectsInvalidVerdict:
    """VerifierOutput with invalid verdict raises ValidationError.

    D-2 §16 Invariant 11.
    """

    def test_invalid_verdict_string(self) -> None:
        data = _make_verifier_output_data(verdict="MAYBE")
        with pytest.raises(ValidationError):
            VerifierOutput(**data)

    def test_empty_verdict_string(self) -> None:
        data = _make_verifier_output_data(verdict="")
        with pytest.raises(ValidationError):
            VerifierOutput(**data)

    def test_numeric_verdict(self) -> None:
        data = _make_verifier_output_data(verdict=42)
        with pytest.raises(ValidationError):
            VerifierOutput(**data)


# ── E1-S17 ──────────────────────────────────────────────────────────


class TestE1S17CorrectEmptyCritiqueValid:
    """VerifierOutput with verdict='CORRECT' and empty
    critique_entries is valid."""

    def test_correct_empty_critique_accepted(self) -> None:
        data = _make_verifier_output_data(
            verdict="CORRECT",
            critique_entries=[],
        )
        output = VerifierOutput(**data)
        assert output.verdict == Verdict.CORRECT
        assert output.critique_entries == []

    def test_correct_with_minor_critique_also_valid(
        self,
    ) -> None:
        """CORRECT + minor cosmetic critique is legal."""
        data = _make_verifier_output_data(
            verdict="CORRECT",
            critique_entries=[
                {
                    "category": "formatting",
                    "severity": "minor",
                    "description": "Typo in abstract.",
                },
            ],
        )
        output = VerifierOutput(**data)
        assert output.verdict == Verdict.CORRECT
        assert len(output.critique_entries) == 1


# ── E1-S18 ──────────────────────────────────────────────────────────


class TestE1S18NonCorrectEmptyCritiqueRejected:
    """VerifierOutput with non-CORRECT verdict and empty
    critique_entries is rejected by model validator.

    D-3 §4.5 post-Instructor semantic validation.
    """

    def test_fixable_empty_critique_rejected(self) -> None:
        data = _make_verifier_output_data(
            verdict="FIXABLE",
            critique_entries=[],
        )
        with pytest.raises(
            ValidationError,
            match="critique_entries is empty",
        ):
            VerifierOutput(**data)

    def test_wrong_empty_critique_rejected(self) -> None:
        data = _make_verifier_output_data(
            verdict="WRONG",
            critique_entries=[],
        )
        with pytest.raises(
            ValidationError,
            match="critique_entries is empty",
        ):
            VerifierOutput(**data)

    def test_fixable_with_critique_accepted(self) -> None:
        """Confirm FIXABLE succeeds when critiques are present."""
        data = _make_verifier_output_data(
            verdict="FIXABLE",
            resolution_type="remediation_plan",
            critique_entries=[
                {
                    "category": "rigor_deficit",
                    "severity": "major",
                    "description": "Proof sketch needs detail.",
                },
            ],
        )
        output = VerifierOutput(**data)
        assert output.verdict == Verdict.FIXABLE
        assert len(output.critique_entries) == 1
