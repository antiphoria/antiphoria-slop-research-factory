from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator

from slop_research_factory.types.enums import CitationCheckResult, Verdict

CritiqueCategory = Literal[
    "citation_error",
    "logical_gap",
    "mathematical_error",
    "rigor_deficit",
    "formatting",
    "scope_violation",
    "other",
]
CritiqueSeverity = Literal["critical", "major", "minor"]


class CitationEntry(BaseModel):
    citation_text: str
    doi: str | None = None
    arxiv_id: str | None = None
    claimed_authors: str | None = None
    claimed_year: int | None = None
    claimed_title: str | None = None
    specific_claim: str | None = None


class CitationCheckEntry(BaseModel):
    citation: CitationEntry
    result: CitationCheckResult
    checked_sources: list[str]
    crossref_match: dict[str, Any] | None = None
    semantic_scholar_match: dict[str, Any] | None = None
    tavily_response: str | None = None
    confidence: float
    notes: str | None = None


class CritiqueEntry(BaseModel):
    category: CritiqueCategory
    severity: CritiqueSeverity
    location: str | None = None
    description: str
    suggested_fix: str | None = None


class VerifierOutput(BaseModel):
    critique_summary: str
    critique_entries: list[CritiqueEntry]
    verdict: Verdict
    resolution_type: str
    verdict_confidence: float
    resolution: str
    confidence_logical_soundness: float
    confidence_mathematical_rigor: float
    confidence_citation_accuracy: float
    confidence_scope_compliance: float
    confidence_novelty_plausibility: float

    @model_validator(mode="after")
    def validate_critiques(self) -> VerifierOutput:
        """D-3 §4.5: FIXABLE/WRONG require non-empty critique_entries."""
        if self.verdict in (Verdict.FIXABLE, Verdict.WRONG) and not self.critique_entries:
            msg = f"verdict '{self.verdict.value}' requires non-empty critique_entries"
            raise ValueError(msg)
        return self
