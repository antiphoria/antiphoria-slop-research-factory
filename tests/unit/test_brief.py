# tests/unit/test_brief.py

"""
E1 unit tests for types/brief.py — D-2 §5.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-S04  ResearchBrief valid construction.
  E1-S05  ResearchBrief thesis rejection (D-2 §16 invariant #5).
  E1-S06  ResearchBrief JSON round-trip and key_references validation.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from slop_research_factory.types.brief import ResearchBrief


class TestResearchBrief(unittest.TestCase):
    """E1-S04 through E1-S06: construction and validation."""

    # ── E1-S04: valid construction ───────────────────────────────

    def test_s04_minimal_brief_accepts_thesis_only(self) -> None:
        """Minimal valid brief: only *thesis* is required."""
        brief = ResearchBrief(thesis="Prove the Riemann hypothesis.")

        self.assertEqual(
            brief.thesis, "Prove the Riemann hypothesis."
        )
        self.assertIsNone(brief.title_suggestion)
        self.assertIsNone(brief.outline)
        self.assertIsNone(brief.key_references)
        self.assertIsNone(brief.constraints)
        self.assertIsNone(brief.target_venue)
        self.assertIsNone(brief.domain)

    def test_s04_thesis_is_stripped_on_input(self) -> None:
        """Leading/trailing whitespace is removed from thesis."""
        brief = ResearchBrief(thesis="  spaced thesis  ")
        self.assertEqual(brief.thesis, "spaced thesis")

    def test_s04_full_construction_accepted(self) -> None:
        """All optional fields can be populated simultaneously."""
        brief = ResearchBrief(
            thesis="Central claim.",
            title_suggestion="A Title",
            outline=["Intro", "Body", "Conclusion"],
            key_references=["arXiv:2301.12345"],
            constraints="Elementary techniques only.",
            target_venue="JAIGP",
            domain="number theory",
        )
        self.assertEqual(brief.title_suggestion, "A Title")
        self.assertEqual(
            len(brief.outline), 3,  # type: ignore[arg-type]
        )
        self.assertEqual(brief.domain, "number theory")

    # ── E1-S05: thesis rejection (D-2 §16 invariant #5) ─────────

    def test_s05_empty_thesis_rejected(self) -> None:
        """Empty string raises ValidationError."""
        with self.assertRaises(ValidationError):
            ResearchBrief(thesis="")

    def test_s05_whitespace_only_thesis_rejected(self) -> None:
        """Whitespace-only string rejected after strip."""
        with self.assertRaises(ValidationError):
            ResearchBrief(thesis="   \t\n  ")

    def test_s05_overlength_thesis_rejected(self) -> None:
        """Thesis exceeding 10 000 characters is rejected."""
        with self.assertRaises(ValidationError):
            ResearchBrief(thesis="x" * 10_001)

    def test_s05_boundary_10000_chars_accepted(self) -> None:
        """Exactly 10 000 characters is the allowed maximum."""
        brief = ResearchBrief(thesis="x" * 10_000)
        self.assertEqual(len(brief.thesis), 10_000)

    # ── E1-S06: JSON round-trip + key_references validation ──────

    def test_s06_full_brief_round_trips_through_json(self) -> None:
        """All fields → model_dump_json → model_validate_json."""
        brief = ResearchBrief(
            thesis="Investigate concordance orders.",
            title_suggestion="On concordance orders",
            outline=["Introduction", "Methods", "Results"],
            key_references=[
                "arXiv:2301.12345",
                "doi:10.1234/example",
            ],
            constraints="Use only classical invariants.",
            target_venue="JAIGP",
            domain="low-dimensional topology",
        )
        json_str = brief.model_dump_json()
        restored = ResearchBrief.model_validate_json(json_str)
        self.assertEqual(brief, restored)

    def test_s06_model_dump_produces_plain_dict(self) -> None:
        """model_dump() returns a JSON-serialisable dict.

        D-2 §6 stores the brief as ``dict`` in FactoryState.
        """
        brief = ResearchBrief(
            thesis="A thesis.",
            key_references=["ref-1"],
        )
        data = brief.model_dump()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["thesis"], "A thesis.")
        self.assertEqual(data["key_references"], ["ref-1"])

    def test_s06_key_references_rejects_empty_entry(self) -> None:
        """Empty string inside key_references is rejected."""
        with self.assertRaises(ValidationError):
            ResearchBrief(
                thesis="Valid thesis.",
                key_references=["arXiv:2301.12345", ""],
            )

    def test_s06_key_references_rejects_whitespace_entry(
        self,
    ) -> None:
        """Whitespace-only entry inside key_references is rejected."""
        with self.assertRaises(ValidationError):
            ResearchBrief(
                thesis="Valid thesis.",
                key_references=["  "],
            )

    def test_s06_key_references_none_is_valid(self) -> None:
        """Omitting key_references entirely is valid (None default)."""
        brief = ResearchBrief(thesis="Thesis.")
        self.assertIsNone(brief.key_references)

    def test_s06_key_references_empty_list_is_valid(self) -> None:
        """An empty list (no references) passes validation."""
        brief = ResearchBrief(
            thesis="Thesis.",
            key_references=[],
        )
        self.assertEqual(brief.key_references, [])
