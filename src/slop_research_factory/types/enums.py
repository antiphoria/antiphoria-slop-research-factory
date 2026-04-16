# src/slop_research_factory/types/enums.py

"""
Enumeration types for the antiphoria slop-research-factory.

Specification references
~~~~~~~~~~~~~~~~~~~~~~~~
  D-0 §7.3  Human rescue semantics
  D-1 §9    Security guarantee
  D-1 §10   SealedStepReceipt / seal classification
  D-2 §3.1  Verdict
  D-2 §3.2  StepType
  D-2 §3.3  RunStatus  (incl. legal-transition table)
  D-2 §3.4  CitationCheckResult
  D-2 §3.5  ConfidenceTier
  D-2 §4    CheckpointBackend
  D-2 §10   HAI Card schema / HumanReviewStatus
  D-2 §12   Human rescue schema / HumanRescueAction
  D-5 §5.5  Human gate node contract
  D-7 §7.4  Human review governance

All enums inherit from ``(str, Enum)`` so every member serialises
to its ``.value`` string in ``json.dumps`` without a custom encoder
(design principle D-2 §2: "JSON-serializable everywhere").
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "CheckpointBackend",
    "CitationCheckResult",
    "ConfidenceTier",
    "HumanRescueAction",
    "HumanReviewStatus",
    "IllegalTransitionError",
    "NodeName",
    "RunStatus",
    "SealType",
    "StepType",
    "Verdict",
    "validate_status_transition",
]


# ── D-2 §3.1  Verdict ───────────────────────────────────────────────


class Verdict(str, Enum):
    """Verifier verdict (D-2 §3.1).

    Modeled on Aletheia's Verification-and-Extraction prompt
    (Feng et al., 2026a, Appendix A).  Three values, no more.
    """

    CORRECT = "CORRECT"
    """Draft is sound; publishable after cosmetic changes."""

    FIXABLE = "FIXABLE"
    """Core approach is sound; identifiable errors can be repaired."""

    WRONG = "WRONG"
    """Draft is fundamentally flawed; needs full rewrite."""


# ── D-2 §3.2  StepType ──────────────────────────────────────────────


class StepType(str, Enum):
    """Seal-chain step classification (D-2 §3.2).

    Per D-1 §10: auditors must distinguish node types structurally.
    """

    GENESIS = "GENESIS"
    PRE_GENERATOR = "PRE_GENERATOR"
    POST_GENERATOR = "POST_GENERATOR"
    PRE_VERIFIER = "PRE_VERIFIER"
    POST_VERIFIER = "POST_VERIFIER"
    PRE_REVISER = "PRE_REVISER"
    POST_REVISER = "POST_REVISER"
    TOOL_CALL = "TOOL_CALL"
    HUMAN_GATE = "HUMAN_GATE"
    MANIFEST = "MANIFEST"


# ── D-2 §3.3  RunStatus ─────────────────────────────────────────────


class RunStatus(str, Enum):
    """Run lifecycle status (D-2 §3.3).

    Forward-only state machine.  Illegal transitions MUST raise
    ``IllegalTransitionError`` rather than silently mutate state.
    """

    INITIALIZING = "INITIALIZING"
    GENERATING = "GENERATING"
    VERIFYING = "VERIFYING"
    REVISING = "REVISING"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_OUTPUT = "NO_OUTPUT"

    @property
    def is_terminal(self) -> bool:
        """``True`` for COMPLETED, FAILED, NO_OUTPUT (no outbound edges)."""
        return len(_LEGAL_TRANSITIONS.get(self, frozenset())) == 0


class IllegalTransitionError(Exception):
    """Raised when a ``RunStatus`` transition violates D-2 §3.3."""


# Legal-transition table ── D-2 §3.3

# Key: source status.  Value: frozenset of allowed target statuses.

# Any pair not listed here is illegal and must raise.

_LEGAL_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.INITIALIZING: frozenset({
        RunStatus.GENERATING,
        RunStatus.FAILED,
        RunStatus.NO_OUTPUT,
    }),
    RunStatus.GENERATING: frozenset({
        RunStatus.VERIFYING,
        RunStatus.FAILED,
        RunStatus.NO_OUTPUT,
    }),
    RunStatus.VERIFYING: frozenset({
        RunStatus.REVISING,
        RunStatus.AWAITING_HUMAN,
        RunStatus.FINALIZING,
        RunStatus.FAILED,
    }),
    RunStatus.REVISING: frozenset({
        RunStatus.VERIFYING,
        RunStatus.FAILED,
        RunStatus.NO_OUTPUT,
    }),
    RunStatus.AWAITING_HUMAN: frozenset({
        RunStatus.GENERATING,
        RunStatus.REVISING,
        RunStatus.FINALIZING,
        RunStatus.NO_OUTPUT,
    }),
    RunStatus.FINALIZING: frozenset({
        RunStatus.COMPLETED,
        RunStatus.FAILED,
    }),
    # Terminal states — zero outbound transitions.
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.NO_OUTPUT: frozenset(),
}


def validate_status_transition(
    current: RunStatus,
    target: RunStatus,
) -> None:
    """Raise if *current -> target* is not in the legal-transition table.

    Per D-2 §3.3: "Any transition not listed above is illegal and
    MUST raise an orchestrator error rather than mutating the state
    silently."
    """
    allowed = _LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransitionError(
            f"Illegal status transition: "
            f"{current.value} -> {target.value}"
        )


# ── D-2 §3.4  CitationCheckResult ───────────────────────────────────


class CitationCheckResult(str, Enum):
    """Citation verification outcome (D-2 §3.4)."""

    VERIFIED = "VERIFIED"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    CLAIM_UNSUPPORTED = "CLAIM_UNSUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


# ── D-2 §3.5  ConfidenceTier ────────────────────────────────────────


class ConfidenceTier(str, Enum):
    """Human-readable confidence bucketing (D-2 §3.5).

    Boundary semantics (explicit per spec)::

        HIGH      confidence >= 0.8
        MEDIUM    0.5 <= confidence < 0.8
        LOW       0.2 <= confidence < 0.5
        VERY_LOW  confidence < 0.2

    ``1.0`` maps to HIGH.  ``0.0`` maps to VERY_LOW.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"

    @classmethod
    def from_score(cls, confidence: float) -> ConfidenceTier:
        """Map a ``[0.0, 1.0]`` float to its tier.

        Raises:
            ValueError: If *confidence* is outside [0.0, 1.0].
        """
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0.0, 1.0], "
                f"got {confidence}"
            )
        if confidence >= 0.8:
            return cls.HIGH
        if confidence >= 0.5:
            return cls.MEDIUM
        if confidence >= 0.2:
            return cls.LOW
        return cls.VERY_LOW


# ── D-2 §4  CheckpointBackend ───────────────────────────────────────


class CheckpointBackend(str, Enum):
    """Checkpoint persistence backend (D-2 §4).

    SQLITE   — JSON + local files (Phase 1 default).
    POSTGRES — Database-backed (Phase 2).
    """

    SQLITE = "SQLITE"
    POSTGRES = "POSTGRES"


# ── NodeName ─────────────────────────────────────────────────────────


class NodeName(str, Enum):
    """Pipeline node identifiers.

    Used by :class:`~slop_research_factory.types.hai_card.ModelUsageRecord`
    and :class:`~slop_research_factory.types.human_rescue.HumanRescueRequest`
    to label which node produced a given record.

    Values derived from the routing table in ``engine.routing``
    (D-0 §4, D-5 §5).
    """

    GENERATOR = "GENERATOR"
    """Draft generation node."""

    VERIFICATION = "VERIFICATION"
    """Verification node (T1–T3)."""

    BRIEF = "BRIEF"
    """Brief ingestion / validation node."""

    HUMAN_RESCUE = "HUMAN_RESCUE"
    """Human rescue gate node."""

    ERROR = "ERROR"
    """Error handling terminal node."""

    END = "END"
    """Normal completion terminal node."""


# ── D-1 §10 / D-0 §5  SealType ──────────────────────────────────────


class SealType(str, Enum):
    """Provenance seal operation category (D-1 §10, D-0 §5.1–§5.2).

    Classifies chain entries at the **provenance layer** (Layer 4).
    Coarser than :class:`StepType`, which tracks per-node
    orchestration detail.  Every position in the chain structure
    defined in D-0 §5.2 maps to exactly one ``SealType``.

    ============  =======================================
    Value         Chain role
    ============  =======================================
    GENESIS       Chain root (step_index=0)
    PRE_SEAL      Intent seal before node inference
    POST_SEAL     Outcome seal after node inference
    TOOL_CALL     External tool invocation seal
    HUMAN_GATE    Human review decision seal
    MANIFEST      Terminal compiled-manifest seal
    ============  =======================================
    """

    GENESIS = "GENESIS"
    """Chain root created by ``begin_chain`` (D-0 §5.1)."""

    PRE_SEAL = "PRE_SEAL"
    """Intent seal before any node inference (D-1 §10)."""

    POST_SEAL = "POST_SEAL"
    """Outcome seal after any node inference (D-1 §10)."""

    TOOL_CALL = "TOOL_CALL"
    """External tool invocation seal (D-1 §10, D-2 §11)."""

    HUMAN_GATE = "HUMAN_GATE"
    """Human review decision seal (D-1 §10, D-2 §12)."""

    MANIFEST = "MANIFEST"
    """Terminal compiled-manifest seal (D-0 §5.2)."""


# ── D-2 §12  HumanRescueAction ──────────────────────────────────────


class HumanRescueAction(str, Enum):
    """Resolution action for a human rescue request (D-2 §12).

    Governs how the orchestrator resumes (or terminates)
    after a human has reviewed the rescue queue item.
    """

    APPROVE_OUTPUT = "APPROVE_OUTPUT"
    """Accept the current draft as-is and finalize."""

    REVISE_AND_CONTINUE = "REVISE_AND_CONTINUE"
    """Human has edited the draft externally; resume pipeline."""

    REJECT_AND_ABORT = "REJECT_AND_ABORT"
    """Abandon the run entirely."""

    INCREASE_LIMITS = "INCREASE_LIMITS"
    """Bump one or more caps and retry the cycle."""

    PROVIDE_GUIDANCE = "PROVIDE_GUIDANCE"
    """Supply guidance text for the next generation cycle."""


# ── D-2 §10 / D-7 §7.4  HumanReviewStatus ──────────────────────────


class HumanReviewStatus(str, Enum):
    """HAI Card review state (D-2 §10, D-7 §7.4).

    ``UNREVIEWED`` is the only valid factory default.
    ``REVIEWED`` must be set explicitly by a human with
    reviewer identity and timestamp.  System code must
    **never** auto-set ``REVIEWED``.
    """

    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    CONTESTED = "CONTESTED"
