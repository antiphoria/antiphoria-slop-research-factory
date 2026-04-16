# src/slop_research_factory/types/verifier_output.py

"""
Verifier output types — Pydantic models for LLM-coerced structured output.

These types are produced by the Verifier node via the Instructor library
(D-3 §4.5).  The Generator and Reviser produce free-form Markdown text;
only the Verifier requires Pydantic output schemas.

Reference
---------
D-2 §8   — Schema definitions (CitationEntry, CitationCheckEntry,
            CritiqueEntry, VerifierOutput).
D-3 §4.5 — Instructor integration and semantic post-validation.
D-4 §5   — Verifier execution sequence consuming these types.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, field_validator, model_validator

from slop_research_factory.types.enums import (
    CitationCheckResult,
    Verdict,
)

__all__ = [
    "CitationCheckEntry",
    "CitationEntry",
    "CritiqueEntry",
    "VALID_CRITIQUE_CATEGORIES",
    "VALID_CRITIQUE_SEVERITIES",
    "VALID_RESOLUTION_TYPES",
    "VerifierOutput",
]

# ── Value-set constants (D-2 §8.3) ─────────────────────────────────────

VALID_CRITIQUE_CATEGORIES: frozenset[str] = frozenset({
    "citation_error",
    "logical_gap",
    "mathematical_error",
    "rigor_deficit",
    "formatting",
    "scope_violation",
    "other",
})
"""Closed set of allowed values for :pyattr:`CritiqueEntry.category`."""

VALID_CRITIQUE_SEVERITIES: frozenset[str] = frozenset({
    "critical",
    "major",
    "minor",
})
"""Closed set of allowed values for :pyattr:`CritiqueEntry.severity`."""

VALID_RESOLUTION_TYPES: frozenset[str] = frozenset({
    "explanation",
    "corrected_version",
    "remediation_plan",
})
"""Closed set of allowed values for
:pyattr:`VerifierOutput.resolution_type`."""


# ── §8.1  CitationEntry ────────────────────────────────────────────────


class CitationEntry(BaseModel):
    """A single citation found in the generated draft.

    Reference: D-2 §8.1.
    """

    citation_text: str
    """The citation as it appears in the draft text."""

    doi: str | None = None
    """Extracted DOI, if present."""

    arxiv_id: str | None = None
    """Extracted arXiv identifier, if present."""

    claimed_authors: str | None = None
    """Author string as claimed in the draft."""

    claimed_year: int | None = None
    """Publication year as claimed in the draft."""

    claimed_title: str | None = None
    """Paper title as claimed in the draft."""

    specific_claim: str | None = None
    """Specific result or theorem number attributed to this reference.

    Per Aletheia's standard: "Citations should include precise
    statement numbers."
    """


# ── §8.2  CitationCheckEntry ───────────────────────────────────────────


class CitationCheckEntry(BaseModel):
    """Result of checking a single citation against external sources.

    One instance is produced per citation during the Verifier's
    tool-grounded citation checking phase (D-4 §5, Phase 3).

    Reference: D-2 §8.2.
    """

    citation: CitationEntry

    result: CitationCheckResult

    checked_sources: list[str]
    """Which APIs were consulted.

    Example: ``["crossref", "semantic_scholar"]``.
    """

    crossref_match: dict[str, Any] | None = None
    """Raw metadata returned by Crossref, if queried.

    Stored for audit trail (D-1 §6, Attack 3 mitigation).
    """

    semantic_scholar_match: dict[str, Any] | None = None
    """Raw metadata from Semantic Scholar, if queried."""

    tavily_response: str | None = None
    """Raw Tavily search response, if used for claim checking.

    Sealed as a TOOL_CALL step.
    """

    confidence: float
    """0.0–1.0.  Deterministic checks yield 1.0 or 0.0;
    LLM-assessed claim relevance is probabilistic."""

    notes: str | None = None
    """Free-form explanation from the Verifier."""

    # ── validators ──────────────────────────────────────────────────

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return v


# ── §8.3  CritiqueEntry ───────────────────────────────────────────────


class CritiqueEntry(BaseModel):
    """A single specific observation from the Verifier's critique.

    ``category`` and ``severity`` are validated against their documented
    value sets.  Malformed LLM outputs are schema errors, not tolerated
    strings (D-2 §8.3 validation requirement).

    Reference: D-2 §8.3.
    """

    category: str
    """One of the values in :data:`VALID_CRITIQUE_CATEGORIES`."""

    severity: str
    """One of ``"critical"``, ``"major"``, ``"minor"``."""

    location: str | None = None
    """Where in the draft this issue occurs.

    Example: ``"Step 3 of the proof, paragraph 2"``.
    """

    description: str
    """Detailed explanation of the flaw."""

    suggested_fix: str | None = None
    """Specific remediation suggestion, if the issue is fixable."""

    # ── validators ──────────────────────────────────────────────────

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        if v not in VALID_CRITIQUE_CATEGORIES:
            msg = (
                f"category must be one of "
                f"{sorted(VALID_CRITIQUE_CATEGORIES)}, "
                f"got {v!r}"
            )
            raise ValueError(msg)
        return v

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        if v not in VALID_CRITIQUE_SEVERITIES:
            msg = (
                f"severity must be one of "
                f"{sorted(VALID_CRITIQUE_SEVERITIES)}, "
                f"got {v!r}"
            )
            raise ValueError(msg)
        return v


# ── §8.4  VerifierOutput ──────────────────────────────────────────────


class VerifierOutput(BaseModel):
    """Complete structured output of the Verifier node.

    Modeled on Aletheia's Verification-and-Extraction prompt
    (Feng et al., 2026a, Appendix A).  The Verifier must produce
    the critique BEFORE the verdict, forcing it to commit to
    specific observations before making a judgment call.

    The model validator enforces the semantic invariant from
    D-3 §4.5: FIXABLE and WRONG verdicts require at least one
    critique entry.

    Reference: D-2 §8.4.
    """

    # --- §1. Critique ───────────────────────────────────────────────

    critique_summary: str
    """Concise summary of the Verifier's analysis."""

    critique_entries: list[CritiqueEntry]
    """Itemised list of specific observations.

    May be empty ONLY when the verdict is ``CORRECT``.
    """

    # --- §2. Verdict ────────────────────────────────────────────────

    verdict: Verdict
    """Exactly one of CORRECT, FIXABLE, or WRONG."""

    resolution_type: str
    """One of ``"explanation"`` | ``"corrected_version"``
    | ``"remediation_plan"``."""

    verdict_confidence: float
    """0.0–1.0.  Primary routing signal.

    If ``verdict == CORRECT`` but this value is below
    ``config.verifier_confidence_threshold``, the orchestrator
    demotes the verdict to FIXABLE (D-2 §8.4 demotion rule).
    """

    # --- §3. Resolution ────────────────────────────────────────────

    resolution: str
    """Per Aletheia's prompt structure: the Verifier's detailed
    resolution text (why correct / fatal flaw / remediation plan).
    """

    # --- Dimensional confidence scores ──────────────────────────────

    confidence_logical_soundness: float
    """0.0–1.0.  Argumentation validity confidence."""

    confidence_mathematical_rigor: float
    """0.0–1.0.  Mathematical correctness confidence."""

    confidence_citation_accuracy: float
    """0.0–1.0.  Citation existence and relevance confidence.

    NOTE: This is the Verifier's *pre-tool-check* estimate.
    Tool-grounded CitationCheckEntry results may override it
    during confidence composition (D-4 §3.1).
    """

    confidence_scope_compliance: float
    """0.0–1.0.  Brief addressal and constraint compliance."""

    confidence_novelty_plausibility: float
    """0.0–1.0.  Per D-0 §6.1 this dimension is LOW-RELIABILITY.

    Architecturally capped at 0.5 (D-4 §3.4).
    """

    # ── Field validators ────────────────────────────────────────────

    @field_validator("resolution_type")
    @classmethod
    def _validate_resolution_type(cls, v: str) -> str:
        if v not in VALID_RESOLUTION_TYPES:
            msg = (
                f"resolution_type must be one of "
                f"{sorted(VALID_RESOLUTION_TYPES)}, "
                f"got {v!r}"
            )
            raise ValueError(msg)
        return v

    @field_validator(
        "verdict_confidence",
        "confidence_logical_soundness",
        "confidence_mathematical_rigor",
        "confidence_citation_accuracy",
        "confidence_scope_compliance",
        "confidence_novelty_plausibility",
    )
    @classmethod
    def _confidence_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = "confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return v

    # ── Model-level semantic validator ──────────────────────────────

    @model_validator(mode="after")
    def _critique_required_for_non_correct(self) -> Self:
        """FIXABLE / WRONG verdicts must include ≥ 1 critique entry.

        Per D-3 §4.5 post-Instructor semantic validation: if the
        verdict is FIXABLE or WRONG but ``critique_entries`` is
        empty, the output is semantically invalid.
        """
        if self.verdict in {Verdict.FIXABLE, Verdict.WRONG}:
            if len(self.critique_entries) == 0:
                msg = (
                    f"verdict is {self.verdict.value} but "
                    f"critique_entries is empty — FIXABLE and "
                    f"WRONG verdicts require at least one "
                    f"critique entry"
                )
                raise ValueError(msg)
        return self

    # ── Pydantic model configuration ───────────────────────────────

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "critique_summary": (
                        "The proof is largely sound but "
                        "Step 3 relies on an unstated "
                        "finiteness assumption."
                    ),
                    "critique_entries": [
                        {
                            "category": "logical_gap",
                            "severity": "major",
                            "location": (
                                "Step 3, second paragraph"
                            ),
                            "description": (
                                "The claim that the compactly "
                                "supported Euler "
                                "characteristic is "
                                "multiplicative requires "
                                "finiteness assumptions on M "
                                "that are not verified."
                            ),
                            "suggested_fix": (
                                "Add a lemma verifying that "
                                "M has finite-type rational "
                                "cohomology, or restrict to "
                                "the compact case."
                            ),
                        }
                    ],
                    "verdict": "FIXABLE",
                    "verdict_confidence": 0.85,
                    "resolution_type": "remediation_plan",
                    "resolution": (
                        "The core approach via Smith theory "
                        "is sound.  A corrected version "
                        "should address the finiteness gap."
                    ),
                    "confidence_logical_soundness": 0.6,
                    "confidence_mathematical_rigor": 0.5,
                    "confidence_citation_accuracy": 0.9,
                    "confidence_scope_compliance": 0.95,
                    "confidence_novelty_plausibility": 0.3,
                }
            ]
        }
    }
