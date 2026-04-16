# tests/unit/test_inference.py

"""
E1 unit tests for types/inference.py — D-2 §9.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-S15  InferenceRecord construction, immutability, JSON round-trip.
          (D-2 §9, D-2 §16 invariants #2 and #6.)
"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, asdict

from slop_research_factory.types.inference import InferenceRecord


class TestInferenceRecord(unittest.TestCase):
    """E1-S15: construction, immutability, JSON round-trip."""

    # ── Helper ───────────────────────────────────────────

    @staticmethod
    def _make_record(**overrides: object) -> InferenceRecord:
        """Build a valid InferenceRecord with overridable defaults."""
        defaults: dict = {
            "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "step_index": 2,
            "role": "generator",
            "model": "deepseek/deepseek-r1",
            "timestamp_start": "2026-04-15T14:32:07.000Z",
            "timestamp_end": "2026-04-15T14:32:37.000Z",
            "duration_seconds": 30.0,
            "input_tokens": 1100,
            "output_tokens": 5200,
            "think_tokens": 12400,
            "prompt_hash": "abc123def456",
            "response_hash": "def456ghi789",
            "response_body_hash": "ghi789jkl012",
            "think_trace_hash": "jkl012mno345",
            "api_provider": "openrouter",
            "api_response_id": "resp-001",
        }
        defaults.update(overrides)
        return InferenceRecord(**defaults)

    # ── E1-S15: valid construction ───────────────────────

    def test_s15_required_fields_and_defaults(self) -> None:
        """Required fields populate; optional fields get defaults."""
        rec = self._make_record()
        self.assertEqual(
            rec.run_id,
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )
        self.assertEqual(rec.role, "generator")
        self.assertEqual(rec.model, "deepseek/deepseek-r1")
        # Defaulted fields
        self.assertEqual(rec.retries, 0)
        self.assertIsNone(rec.error)
        self.assertEqual(rec.sampling_params, {})

    def test_s15_explicit_defaults_preserved(self) -> None:
        """Explicit overrides for defaulted fields are kept."""
        rec = self._make_record(
            retries=3,
            error="Timeout after 30s",
            sampling_params={
                "temperature": 0.0, "top_p": 1.0,
            },
        )
        self.assertEqual(rec.retries, 3)
        self.assertEqual(rec.error, "Timeout after 30s")
        self.assertAlmostEqual(
            rec.sampling_params["temperature"], 0.0,
        )

    def test_s15_all_three_roles_accepted(self) -> None:
        """Each valid role constructs without error."""
        for role in ("generator", "verifier", "reviser"):
            with self.subTest(role=role):
                rec = self._make_record(role=role)
                self.assertEqual(rec.role, role)

    def test_s15_think_tokens_none_when_not_captured(self) -> None:
        """think_tokens and think_trace_hash may both be None."""
        rec = self._make_record(
            think_tokens=None,
            think_trace_hash=None,
        )
        self.assertIsNone(rec.think_tokens)
        self.assertIsNone(rec.think_trace_hash)

    def test_s15_zero_values_accepted(self) -> None:
        """Boundary: zero is valid for every numeric counter."""
        rec = self._make_record(
            step_index=0,
            duration_seconds=0.0,
            input_tokens=0,
            output_tokens=0,
            think_tokens=0,
            retries=0,
        )
        self.assertEqual(rec.step_index, 0)
        self.assertEqual(rec.duration_seconds, 0.0)
        self.assertEqual(rec.input_tokens, 0)
        self.assertEqual(rec.output_tokens, 0)
        self.assertEqual(rec.think_tokens, 0)

    def test_s15_api_response_id_none_accepted(self) -> None:
        """api_response_id may be None if the provider omits it."""
        rec = self._make_record(api_response_id=None)
        self.assertIsNone(rec.api_response_id)

    # ── E1-S15: rejection ────────────────────────────────

    def test_s15_invalid_role_rejected(self) -> None:
        """Unrecognised role raises ValueError."""
        with self.assertRaises(ValueError):
            self._make_record(role="summarizer")

    def test_s15_negative_step_index_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._make_record(step_index=-1)

    def test_s15_negative_duration_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._make_record(duration_seconds=-0.001)

    def test_s15_negative_input_tokens_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._make_record(input_tokens=-1)

    def test_s15_negative_output_tokens_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._make_record(output_tokens=-1)

    def test_s15_negative_think_tokens_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._make_record(think_tokens=-100)

    def test_s15_negative_retries_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._make_record(retries=-1)

    # ── E1-S15: immutability ─────────────────────────────

    def test_s15_frozen_rejects_attribute_reassignment(self) -> None:
        """Frozen dataclass prevents attribute reassignment."""
        rec = self._make_record()
        with self.assertRaises(FrozenInstanceError):
            rec.role = "verifier"  # type: ignore[misc]

    # ── E1-S15: JSON round-trip (D-2 §16 #2 & #6) ───────

    def test_s15_round_trip_through_json(self) -> None:
        """asdict → json.dumps → json.loads → InferenceRecord."""
        original = self._make_record(
            retries=2,
            error=None,
            sampling_params={"temperature": 0.7},
        )
        json_str = json.dumps(asdict(original))
        restored_data = json.loads(json_str)
        restored = InferenceRecord(**restored_data)
        self.assertEqual(asdict(original), asdict(restored))

    def test_s15_to_dict_matches_asdict(self) -> None:
        """to_dict() agrees with dataclasses.asdict."""
        rec = self._make_record()
        self.assertEqual(rec.to_dict(), asdict(rec))

    def test_s15_serialised_contains_only_plain_types(self) -> None:
        """D-2 §16 #6: serialised form has only JSON-native types."""
        rec = self._make_record()
        data = json.loads(json.dumps(asdict(rec)))
        self.assertIsInstance(data["role"], str)
        self.assertIsInstance(data["step_index"], int)
        self.assertIsInstance(data["duration_seconds"], float)

    def test_s15_none_fields_survive_json(self) -> None:
        """None values round-trip as JSON null → Python None."""
        rec = self._make_record(
            think_tokens=None,
            think_trace_hash=None,
            error=None,
            api_response_id=None,
        )
        data = json.loads(json.dumps(asdict(rec)))
        self.assertIsNone(data["think_tokens"])
        self.assertIsNone(data["think_trace_hash"])
        self.assertIsNone(data["error"])
        self.assertIsNone(data["api_response_id"])

    def test_s15_sampling_params_survives_round_trip(self) -> None:
        """Non-empty sampling_params dict survives JSON."""
        params = {
            "temperature": 0.0, "top_p": 1.0, "seed": 42,
        }
        rec = self._make_record(sampling_params=params)
        json_str = json.dumps(asdict(rec))
        restored = json.loads(json_str)
        self.assertEqual(restored["sampling_params"], params)

    def test_s15_default_sampling_params_not_shared(self) -> None:
        """Each instance gets its own empty dict (no aliasing)."""
        a = self._make_record()
        b = self._make_record()
        self.assertEqual(a.sampling_params, {})
        self.assertEqual(b.sampling_params, {})
        self.assertIsNot(a.sampling_params, b.sampling_params)
