# src/slop_research_factory/types/human_rescue.py

"""
Human rescue queue types — D-2 §12.

Two frozen dataclasses model the rescue flow:

  :class:`HumanRescueRequest`
      Created by the routing logic when any loop-limit cap
      is breached.  Captures a snapshot of pipeline state
      sufficient for a human reviewer to understand *why*
      the run escalated and *what* the current draft looks
      like.

  :class:`HumanRescueResolution`
      Created by the human gate node after a reviewer acts
      on a request.  Carries the chosen action and any
      action-specific payloads (limit overrides, guidance
      text).

Action-specific invariants on :class:`HumanRescueResolution`:

  ``INCREASE_LIMITS``
      At least one ``revised_*`` field must be set.

  ``PROVIDE_GUIDANCE``
      ``guidance`` must be non-empty.

  ``APPROVE_OUTPUT`` / ``REJECT_AND_ABORT`` /
  ``REVISE_AND_CONTINUE``
      No extra fields required.

Design notes:

- Both types are frozen — immutable once created.
- ``rescue_reason`` is a plain string matching the

  ``REASON_*`` constants from ``engine.routing``.
  No import dependency to avoid circular references.
- SHA-256 hashes: 64-char lowercase hexadecimal when set.
- Timestamps: timezone-aware (UTC expected).
- No serialization methods; the workspace manager handles

  persistence.

Spec references:
    D-0 §7.3   Rescue queue semantics.
    D-2 §12    Human rescue schema.
    D-5 §5.5   Human gate node contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from slop_research_factory.types.enums import (
    HumanRescueAction,
    NodeName,
    Verdict,
)

__all__ = [
    "HumanRescueRequest",
    "HumanRescueResolution",
]

# ── Constants ────────────────────────────────────────────

_SHA256_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")


# ── HumanRescueRequest (D-2 §12.1) ──────────────────────


@dataclass(frozen=True)
class HumanRescueRequest:
    """Pipeline state snapshot at point of rescue escalation.

    Created by the routing logic and written to the
    workspace ``rescue/`` directory.  A human reviewer
    reads this to decide how to proceed.

    Attributes:
        request_id:         Unique request identifier
                            (typically a UUID).
        run_id:             Run that triggered the rescue.
        created_at:         UTC timestamp of escalation
                            (timezone-aware).
        rescue_reason:      One of the ``REASON_*`` string
                            constants from
                            ``engine.routing``.
        node_name:          Node active when rescue was
                            triggered.
        step_index:         Zero-based step index at
                            escalation.
        cycle_count:        Completed generate → verify
                            (→ revise) cycles.
        rejection_count:    WRONG verdicts accumulated.
        revision_count:     FIXABLE verdicts accumulated.
        brief_title:        Human-readable brief title for
                            context.
        summary:            Auto-generated explanation of
                            the escalation.
        latest_verdict:     Verdict that triggered rescue
                            (``None`` if budget-only).
        verdict_confidence: Confidence of that verdict
                            (0.0–1.0 when set).
        latest_seal_hash:   SHA-256 of the most recent
                            seal (``None`` if no seals
                            yet).
    """

    # ── Required fields ──────────────────────────────────

    request_id: str
    run_id: str
    created_at: datetime
    rescue_reason: str
    node_name: NodeName
    step_index: int
    cycle_count: int
    rejection_count: int
    revision_count: int
    brief_title: str
    summary: str

    # ── Defaulted fields ─────────────────────────────────

    latest_verdict: Verdict | None = None
    verdict_confidence: float | None = None
    latest_seal_hash: str | None = None

    # ── Validation ───────────────────────────────────────

    def __post_init__(self) -> None:
        # Non-empty strings
        if not self.request_id:
            raise ValueError(
                "request_id must be non-empty"
            )
        if not self.run_id:
            raise ValueError(
                "run_id must be non-empty"
            )
        if not self.rescue_reason:
            raise ValueError(
                "rescue_reason must be non-empty"
            )
        if not self.brief_title.strip():
            raise ValueError(
                "brief_title must be non-empty"
            )
        if not self.summary.strip():
            raise ValueError(
                "summary must be non-empty"
            )

        # Timezone-aware timestamp
        if self.created_at.tzinfo is None:
            raise ValueError(
                "created_at must be timezone-aware (UTC)"
            )

        # Non-negative integers
        if self.step_index < 0:
            raise ValueError(
                f"step_index must be >= 0, "
                f"got {self.step_index}"
            )
        if self.cycle_count < 0:
            raise ValueError(
                f"cycle_count must be >= 0, "
                f"got {self.cycle_count}"
            )
        if self.rejection_count < 0:
            raise ValueError(
                f"rejection_count must be >= 0, "
                f"got {self.rejection_count}"
            )
        if self.revision_count < 0:
            raise ValueError(
                f"revision_count must be >= 0, "
                f"got {self.revision_count}"
            )

        # Confidence range
        if self.verdict_confidence is not None:
            if not (
                0.0 <= self.verdict_confidence <= 1.0
            ):
                raise ValueError(
                    f"verdict_confidence must be "
                    f"0.0–1.0, got "
                    f"{self.verdict_confidence}"
                )

        # SHA-256 hash format
        if (
            self.latest_seal_hash is not None
            and not _SHA256_RE.match(
                self.latest_seal_hash
            )
        ):
            raise ValueError(
                "latest_seal_hash must be 64-char "
                "lowercase hex or None, "
                f"got {self.latest_seal_hash!r}"
            )


# ── HumanRescueResolution (D-2 §12.2) ───────────────────


@dataclass(frozen=True)
class HumanRescueResolution:
    """Human reviewer's response to a rescue request.

    Created by the human gate node and consumed by the
    orchestrator to decide how to resume (or terminate)
    the run.

    Action-specific invariants:

    - ``INCREASE_LIMITS``: at least one ``revised_*``

      field must be non-``None``.
    - ``PROVIDE_GUIDANCE``: ``guidance`` must be

      non-empty.

    Attributes:
        request_id:               Links back to the
                                  :class:`HumanRescueRequest`.
        resolved_at:              UTC timestamp of
                                  resolution (tz-aware).
        resolver_id:              Identity of the human
                                  reviewer.
        action:                   Chosen resolution action.
        notes:                    Free-text reviewer notes.
        guidance:                 Guidance text for next
                                  cycle (required for
                                  ``PROVIDE_GUIDANCE``).
        revised_max_rejections:   New rejection cap
                                  (``INCREASE_LIMITS``).
        revised_max_revisions:    New revision cap.
        revised_max_total_cycles: New total cycle cap.
        revised_max_total_tokens: New token budget.
        revised_max_total_cost_usd: New cost budget.
    """

    # ── Required fields ──────────────────────────────────

    request_id: str
    resolved_at: datetime
    resolver_id: str
    action: HumanRescueAction

    # ── Defaulted fields ─────────────────────────────────

    notes: str = ""
    guidance: str = ""
    revised_max_rejections: int | None = None
    revised_max_revisions: int | None = None
    revised_max_total_cycles: int | None = None
    revised_max_total_tokens: int | None = None
    revised_max_total_cost_usd: float | None = None

    # ── Validation ───────────────────────────────────────

    def __post_init__(self) -> None:
        # Non-empty strings
        if not self.request_id:
            raise ValueError(
                "request_id must be non-empty"
            )
        if not self.resolver_id:
            raise ValueError(
                "resolver_id must be non-empty"
            )

        # Timezone-aware timestamp
        if self.resolved_at.tzinfo is None:
            raise ValueError(
                "resolved_at must be timezone-aware "
                "(UTC)"
            )

        # Non-negative limit overrides (when set)
        _validate_non_negative_optional(
            "revised_max_rejections",
            self.revised_max_rejections,
        )
        _validate_non_negative_optional(
            "revised_max_revisions",
            self.revised_max_revisions,
        )
        _validate_non_negative_optional(
            "revised_max_total_cycles",
            self.revised_max_total_cycles,
        )
        _validate_non_negative_optional(
            "revised_max_total_tokens",
            self.revised_max_total_tokens,
        )
        _validate_non_negative_optional_float(
            "revised_max_total_cost_usd",
            self.revised_max_total_cost_usd,
        )

        # Action-specific invariants
        if (
            self.action is HumanRescueAction.INCREASE_LIMITS
        ):
            if not self._has_any_revised_limit():
                raise ValueError(
                    "INCREASE_LIMITS requires at least "
                    "one revised_* field to be set"
                )

        if (
            self.action
            is HumanRescueAction.PROVIDE_GUIDANCE
        ):
            if not self.guidance.strip():
                raise ValueError(
                    "PROVIDE_GUIDANCE requires "
                    "non-empty guidance"
                )

    def _has_any_revised_limit(self) -> bool:
        """Return ``True`` if any ``revised_*`` field is set."""
        return any(
            v is not None
            for v in (
                self.revised_max_rejections,
                self.revised_max_revisions,
                self.revised_max_total_cycles,
                self.revised_max_total_tokens,
                self.revised_max_total_cost_usd,
            )
        )


# ── Validation helpers ───────────────────────────────────


def _validate_non_negative_optional(
    name: str,
    value: int | None,
) -> None:
    """Raise ``ValueError`` if *value* is set and < 0."""
    if value is not None and value < 0:
        raise ValueError(
            f"{name} must be >= 0, got {value}"
        )


def _validate_non_negative_optional_float(
    name: str,
    value: float | None,
) -> None:
    """Raise ``ValueError`` if *value* is set and < 0.0."""
    if value is not None and value < 0.0:
        raise ValueError(
            f"{name} must be >= 0.0, got {value}"
        )
