# src/slop_research_factory/types/brief.py

"""
ResearchBrief — the sole human input that initiates a factory run.

Spec reference: D-2 §5.  Validation rules: D-2 §5, D-2 §16 invariant #5.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class ResearchBrief(BaseModel):
    """The human-authored research brief that initiates a factory run.

    This is the ONLY human intellectual contribution to the generation
    process.  Everything downstream is autonomous.  The brief is sealed
    as the first post-genesis artifact in the provenance chain.

    Spec: D-2 §5.
    """

    # ── Required ─────────────────────────────────────────────────

    thesis: str
    """Central claim, question, or hypothesis to investigate.

    Stripped of leading/trailing whitespace on input.
    Must be non-empty and at most 10 000 characters after stripping.
    """

    # ── Optional ─────────────────────────────────────────────────

    title_suggestion: str | None = None
    """Suggested title; the Generator may override."""

    outline: list[str] | None = None
    """Ordered section headings or structural directives.

    If *None*, the Generator determines structure autonomously.
    """

    key_references: list[str] | None = None
    """DOIs, arXiv IDs, or full citation strings the human considers
    relevant.  Each entry must be a non-empty string.
    """

    constraints: str | None = None
    """Free-form scope limits, methodological requirements, or
    stylistic directives.
    """

    target_venue: str | None = None
    """Intended publication venue, e.g. ``'JAIGP'``."""

    domain: str | None = None
    """Scientific domain, e.g. ``'algebraic topology'``."""

    # ── Validators ───────────────────────────────────────────────

    @field_validator("thesis")
    @classmethod
    def thesis_must_be_non_empty_and_bounded(cls, v: str) -> str:
        """Strip whitespace; reject empty or > 10 000 chars.

        Spec: D-2 §5, D-2 §16 invariant #5.
        """
        v = v.strip()
        if not v:
            raise ValueError("thesis must be non-empty")
        if len(v) > 10_000:
            raise ValueError(
                "thesis exceeds 10 000 character limit"
            )
        return v

    @field_validator("key_references")
    @classmethod
    def key_references_entries_must_be_non_empty(
        cls,
        v: list[str] | None,
    ) -> list[str] | None:
        """Reject empty or whitespace-only reference entries.

        Spec: D-2 §5 — "each be non-empty strings".
        """
        if v is not None:
            for idx, ref in enumerate(v):
                if not ref.strip():
                    raise ValueError(
                        f"key_references[{idx}] must be a "
                        f"non-empty string"
                    )
        return v

    # ── Pydantic v2 model configuration ──────────────────────────

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "thesis": (
                        "Investigate whether the pretzel knot "
                        "P(-3, 5, 13) has infinite order in "
                        "the smooth concordance group."
                    ),
                    "key_references": ["arXiv:2301.12345"],
                    "domain": "low-dimensional topology",
                    "constraints": (
                        "Use only classical invariants. "
                        "Do not invoke Heegaard Floer "
                        "homology."
                    ),
                    "target_venue": "JAIGP",
                }
            ],
        },
    }
