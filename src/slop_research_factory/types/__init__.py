# src/slop_research_factory/types/__init__.py

"""
Public type re-exports for ``slop_research_factory.types``.

Every consumer should import from this package, not from
individual submodules, unless a submodule-specific import
is needed to avoid circular references.
"""

# ── enums ────────────────────────────────────────────────

# ── brief ────────────────────────────────────────────────
from slop_research_factory.types.brief import ResearchBrief
from slop_research_factory.types.enums import (
    CheckpointBackend,
    CitationCheckResult,
    ConfidenceTier,
    HumanRescueAction,
    HumanReviewStatus,
    IllegalTransitionError,
    NodeName,
    RescueReason,
    RunStatus,
    SealType,
    StepType,
    Verdict,
    validate_status_transition,
)

# ── hai card ─────────────────────────────────────────────
from slop_research_factory.types.hai_card import (
    DEFAULT_DISCLAIMER,
    SECURITY_GUARANTEE,
    HaiCard,
    ModelUsageRecord,
    ProcessSummary,
    VerificationSummary,
)

# ── human rescue ─────────────────────────────────────────
from slop_research_factory.types.human_rescue import (
    HumanRescueRequest,
    HumanRescueResolution,
)

# ── inference ────────────────────────────────────────────
from slop_research_factory.types.inference import InferenceRecord

# ── provenance ───────────────────────────────────────────
from slop_research_factory.types.provenance import (
    ProvenanceChain,
    ProvenanceChainError,
    ProvenanceMetadata,
    SealRecord,
)

# ── state ────────────────────────────────────────────────
from slop_research_factory.types.state import (
    AppendOnlyList,
    FactoryState,
)

# ── tool types ───────────────────────────────────────────
from slop_research_factory.types.tool_types import (
    CrossrefQuery,
    CrossrefResult,
    SemanticScholarQuery,
    SemanticScholarResult,
    TavilyQuery,
    TavilyResult,
)

# ── verifier output ──────────────────────────────────────
from slop_research_factory.types.verifier_output import (
    CitationCheckEntry,
    CitationEntry,
    CritiqueEntry,
    VerifierOutput,
)

__all__ = [
    # enums
    "CheckpointBackend",
    "CitationCheckResult",
    "ConfidenceTier",
    "HumanRescueAction",
    "HumanReviewStatus",
    "IllegalTransitionError",
    "NodeName",
    "RescueReason",
    "RunStatus",
    "SealType",
    "StepType",
    "Verdict",
    "validate_status_transition",
    # brief
    "ResearchBrief",
    # inference
    "InferenceRecord",
    # verifier output
    "CitationCheckEntry",
    "CitationEntry",
    "CritiqueEntry",
    "VerifierOutput",
    # hai card
    "DEFAULT_DISCLAIMER",
    "HaiCard",
    "ModelUsageRecord",
    "ProcessSummary",
    "SECURITY_GUARANTEE",
    "VerificationSummary",
    # human rescue
    "HumanRescueRequest",
    "HumanRescueResolution",
    # provenance
    "ProvenanceChain",
    "ProvenanceChainError",
    "ProvenanceMetadata",
    "SealRecord",
    # state
    "AppendOnlyList",
    "FactoryState",
    # tool types
    "CrossrefQuery",
    "CrossrefResult",
    "SemanticScholarQuery",
    "SemanticScholarResult",
    "TavilyQuery",
    "TavilyResult",
]
