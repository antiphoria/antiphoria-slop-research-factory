# src/slop_research_factory/types/inference.py

"""
InferenceRecord — metadata for a single LLM API call.

Spec reference: . One record per Generator, Verifier,
or Reviser invocation, written to disk as::

    drafts/cycle_{NN}_{role}_record.json

Sealed as part of the POST-seal step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from slop_research_factory.types.hashing import is_valid_sha256_hex

__all__ = ["InferenceRecord"]

# ── Module-level constants ────────────────────────────────────

# Allowed values for ``InferenceRecord.role``.
_VALID_ROLES: frozenset[str] = frozenset(
    {
        "generator",
        "verifier",
        "reviser",
    }
)


@dataclass(frozen=True)
class InferenceRecord:
    """Captures the full metadata of a single LLM API call.

    Frozen: instances are immutable after construction.
    Serialise via :func:`dataclasses.asdict` or :meth:`to_dict`.

    """

    # ── Identity ──────────────────────────────────────────

    run_id: str
    """Unique run identifier (UUID4)."""

    step_index: int
    """Monotonic step counter at POST-seal time; >= 0."""

    role: str
    """One of ``"generator"``, ``"verifier"``, ``"reviser"``."""

    model: str
    """Model identifier string as passed to LiteLLM."""

    # ── Timing ────────────────────────────────────────────

    timestamp_start: str
    """ISO 8601 UTC — API call initiated."""

    timestamp_end: str
    """ISO 8601 UTC — API call completed."""

    duration_seconds: float
    """Wall-clock seconds for this inference call; >= 0."""

    # ── Token accounting ──────────────────────────────────

    input_tokens: int
    """Prompt token count; >= 0."""

    output_tokens: int
    """Completion token count (excludes think tokens); >= 0."""

    think_tokens: int | None
    """Reasoning-trace token count, or *None* when
    ``capture_think_tokens`` is disabled or the model does
    not emit think tokens."""

    # ── Content hashes ────────────────────────────────────

    prompt_hash: str
    """SHA-256 of the exact prompt sent to the API."""

    response_hash: str
    """SHA-256 of the complete API response
    (think + output as received)."""

    response_body_hash: str
    """SHA-256 of the final output only (think stripped)."""

    think_trace_hash: str | None
    """SHA-256 of think tokens only, or *None*."""

    # ── API metadata ──────────────────────────────────────

    api_provider: str
    """Provider identifier, e.g.
    ``"openrouter"``, ``"google"``, ``"ollama"``."""

    api_response_id: str | None
    """Provider response ID, if available.
    For future provider-side signing."""

    # ── Error handling (with defaults) ────────────────────

    retries: int = 0
    """LiteLLM retries before success; 0 = first try OK."""

    error: str | None = None
    """Error message if the call ultimately failed."""

    sampling_params: dict[str, Any] = field(default_factory=dict)
    """Sampling hyper-parameters, e.g.
    ``{"temperature": 0.0, "top_p": 1.0}``."""

    # ── Post-init validation ──────────────────────────────

    def __post_init__(self) -> None:
        """Validate critical invariants at construction time.

        Raises:
            ValueError: Invalid *role* or negative numeric field.
        """
        if self.role not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}, got {self.role!r}")
        if self.step_index < 0:
            raise ValueError(f"step_index must be >= 0, got {self.step_index}")
        if self.duration_seconds < 0.0:
            raise ValueError(f"duration_seconds must be >= 0.0, got {self.duration_seconds}")
        if self.input_tokens < 0:
            raise ValueError(f"input_tokens must be >= 0, got {self.input_tokens}")
        if self.output_tokens < 0:
            raise ValueError(f"output_tokens must be >= 0, got {self.output_tokens}")
        if self.think_tokens is not None and self.think_tokens < 0:
            raise ValueError(f"think_tokens must be >= 0 or None, got {self.think_tokens}")
        if self.retries < 0:
            raise ValueError(f"retries must be >= 0, got {self.retries}")
        for label, h in (
            ("prompt_hash", self.prompt_hash),
            ("response_hash", self.response_hash),
            ("response_body_hash", self.response_body_hash),
        ):
            if not is_valid_sha256_hex(h):
                raise ValueError(f"{label} must be 64-char lowercase hex SHA-256, got {h!r}")
        if self.think_trace_hash is not None and not is_valid_sha256_hex(
            self.think_trace_hash,
        ):
            raise ValueError(
                "think_trace_hash must be 64-char lowercase hex or None, "
                f"got {self.think_trace_hash!r}"
            )

    # ── Convenience ───────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable ``dict``.

        Thin wrapper over :func:`dataclasses.asdict`.
        Suitable for writing to
        ``drafts/cycle_{NN}_{role}_record.json``.
        """
        return asdict(self)
