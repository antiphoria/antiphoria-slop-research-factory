# src/slop_research_factory/seal/registry.py

"""
Metadata schema registry — strict per-StepType payload validation.

The SDK keeps ``ChainRecord.metadata`` free-form (``dict[str, Any]``)
on purpose: it is content-addressed, signed, and re-verified bit-for-bit
across SDK releases. A new field on the SDK side would otherwise force
a synchronised version bump on every consumer.

The factory pays a different price: with ten step types and growing
heterogeneity (Generator, Verifier, Reviser, Tool calls, Manifest…),
loose metadata is how schema drift sneaks in over years of execution.
The registry below is the factory-side antidote — every metadata dict
is matched against a *required + allowed* spec keyed on
:class:`StepType` before it leaves :func:`seal_step` for the engine.

Strictness mode
~~~~~~~~~~~~~~~

The default is **STRICT**: unknown keys raise :class:`MetadataSchemaError`.
The ``ANTIPHORIA_METADATA_LENIENT=1`` env var (or
:func:`set_metadata_strictness`) downgrades unknown-key violations to
warnings. Use this only when iterating schemas locally; CI MUST run
strict.

"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from slop_research_factory.types.enums import StepType

__all__ = [
    "METADATA_REGISTRY",
    "METADATA_STRICTNESS_ENV",
    "MetadataSchema",
    "MetadataSchemaError",
    "MetadataStrictness",
    "current_strictness",
    "register_metadata_schema",
    "set_metadata_strictness",
    "validate_metadata",
]

logger = logging.getLogger(__name__)

METADATA_STRICTNESS_ENV = "ANTIPHORIA_METADATA_LENIENT"


class MetadataStrictness:
    """Strictness modes for :func:`validate_metadata`."""

    STRICT = "strict"
    LENIENT = "lenient"


_DEFAULT_STRICTNESS: str = MetadataStrictness.STRICT


def current_strictness() -> str:
    """Return the active strictness mode (env var honoured at call time)."""
    if os.environ.get(METADATA_STRICTNESS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return MetadataStrictness.LENIENT
    return _DEFAULT_STRICTNESS


def set_metadata_strictness(mode: str) -> None:
    """Override the default strictness mode for the current process."""
    global _DEFAULT_STRICTNESS
    if mode not in {MetadataStrictness.STRICT, MetadataStrictness.LENIENT}:
        raise ValueError(f"unknown strictness mode: {mode!r}")
    _DEFAULT_STRICTNESS = mode


# ── Errors ───────────────────────────────────────────────


class MetadataSchemaError(ValueError):
    """Raised when a metadata dict violates its registered schema.

    Subclass of :class:`ValueError` so legacy error handlers (e.g.
    in ``seal_step``) catch it without explicit re-typing.
    """


# ── Schema dataclass ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MetadataSchema:
    """Per-:class:`StepType` metadata contract.

    Attributes:
        required: Keys that MUST be present and non-``None``.
        allowed: Keys that MAY be present (in addition to ``required``).
        types: Optional per-key type constraint. Keys not listed are
            unchecked. ``None`` is always permissible for keys not in
            ``required``. The check uses :func:`isinstance`; pass a
            tuple to allow multiple types.
    """

    required: frozenset[str] = field(default_factory=frozenset)
    allowed: frozenset[str] = field(default_factory=frozenset)
    types: dict[str, tuple[type, ...]] = field(default_factory=dict)

    @property
    def all_keys(self) -> frozenset[str]:
        return self.required | self.allowed


# ── Registry ─────────────────────────────────────────────


METADATA_REGISTRY: dict[StepType, MetadataSchema] = {
    StepType.GENESIS: MetadataSchema(
        allowed=frozenset({"research_brief"}),
        types={"research_brief": (dict,)},
    ),
    StepType.PRE_GENERATOR: MetadataSchema(
        required=frozenset({"prompt_hash", "model_id", "cycle"}),
        allowed=frozenset({"prompt_version"}),
        types={
            "prompt_hash": (str,),
            "model_id": (str,),
            "cycle": (int,),
            "prompt_version": (str,),
        },
    ),
    StepType.POST_GENERATOR: MetadataSchema(
        required=frozenset(
            {
                "model_id",
                "input_tokens",
                "output_tokens",
                "cycle",
                "draft_hash",
                "raw_response_hash",
            },
        ),
        allowed=frozenset(
            {
                "think_hash",
                "api_response_id",
                "prompt_version",
                "is_no_output",
                "token_counts_think",
            },
        ),
        types={
            "model_id": (str,),
            "input_tokens": (int,),
            "output_tokens": (int,),
            "cycle": (int,),
            "draft_hash": (str,),
            "raw_response_hash": (str,),
            "think_hash": (str, type(None)),
            "api_response_id": (str, type(None)),
            "prompt_version": (str,),
            "is_no_output": (bool,),
            "token_counts_think": (str, int),
        },
    ),
    StepType.PRE_VERIFIER: MetadataSchema(
        required=frozenset(
            {"prompt_hash", "model_id", "cycle", "num_citations_checked"},
        ),
        allowed=frozenset(
            {
                "draft_hash",
                "tool_call_steps",
                "prompt_version",
                "draft_version",
            },
        ),
        types={
            "prompt_hash": (str,),
            "model_id": (str,),
            "cycle": (int,),
            "num_citations_checked": (int,),
            "draft_hash": (str,),
            "tool_call_steps": (list,),
            "prompt_version": (str,),
            "draft_version": (int,),
        },
    ),
    StepType.POST_VERIFIER: MetadataSchema(
        required=frozenset(
            {
                "raw_critique_hash",
                "critique_hash",
                "raw_verdict",
                "verdict",
                "confidence",
                "model_id",
                "cycle",
                "input_tokens",
                "output_tokens",
            },
        ),
        allowed=frozenset(
            {
                "resolution_type",
                "api_response_id",
                "prompt_version",
                "token_counts_think",
            },
        ),
        types={
            "raw_critique_hash": (str,),
            "critique_hash": (str,),
            "raw_verdict": (str,),
            "verdict": (str,),
            "confidence": (float, int),
            "model_id": (str,),
            "cycle": (int,),
            "input_tokens": (int,),
            "output_tokens": (int,),
            "resolution_type": (str, type(None)),
            "api_response_id": (str, type(None)),
            "prompt_version": (str,),
            "token_counts_think": (str, int),
        },
    ),
    StepType.PRE_REVISER: MetadataSchema(
        required=frozenset(
            {"prompt_hash", "critique_hash", "model_id", "cycle", "mode"},
        ),
        allowed=frozenset({"prompt_version", "verdict"}),
        types={
            "prompt_hash": (str,),
            "critique_hash": (str,),
            "model_id": (str,),
            "cycle": (int,),
            "mode": (str,),
            "prompt_version": (str,),
            "verdict": (str,),
        },
    ),
    StepType.POST_REVISER: MetadataSchema(
        required=frozenset(
            {
                "model_id",
                "input_tokens",
                "output_tokens",
                "cycle",
                "mode",
                "draft_hash",
                "raw_response_hash",
                "critique_hash",
            },
        ),
        allowed=frozenset(
            {
                "think_hash",
                "api_response_id",
                "prompt_version",
                "is_no_output",
                "token_counts_think",
            },
        ),
        types={
            "model_id": (str,),
            "input_tokens": (int,),
            "output_tokens": (int,),
            "cycle": (int,),
            "mode": (str,),
            "draft_hash": (str,),
            "raw_response_hash": (str,),
            "critique_hash": (str,),
            "think_hash": (str, type(None)),
            "api_response_id": (str, type(None)),
            "prompt_version": (str,),
            "is_no_output": (bool,),
            "token_counts_think": (str, int),
        },
    ),
    StepType.TOOL_CALL: MetadataSchema(
        required=frozenset({"tool_name", "query", "response_hash"}),
        allowed=frozenset(
            {"parent_step", "elapsed_seconds", "result_status", "cycle"},
        ),
        types={
            "tool_name": (str,),
            "query": (str,),
            "response_hash": (str,),
            "parent_step": (int, type(None)),
            "elapsed_seconds": (float, int),
            "result_status": (str,),
            "cycle": (int,),
        },
    ),
    StepType.HUMAN_GATE: MetadataSchema(
        required=frozenset({"request_id", "rescue_reason", "node_name"}),
        allowed=frozenset(
            {
                "resolver_id",
                "action",
                "notes",
                "cycle_count",
                "rejection_count",
                "revision_count",
            },
        ),
        types={
            "request_id": (str,),
            "rescue_reason": (str,),
            "node_name": (str,),
            "resolver_id": (str,),
            "action": (str,),
            "notes": (str,),
            "cycle_count": (int,),
            "rejection_count": (int,),
            "revision_count": (int,),
        },
    ),
    StepType.MANIFEST: MetadataSchema(
        required=frozenset({"total_steps", "final_verdict", "manifest_hash"}),
        allowed=frozenset(
            {"hai_card_hash", "report_hash", "model_topology"},
        ),
        types={
            "total_steps": (int,),
            "final_verdict": (str,),
            "manifest_hash": (str,),
            "hai_card_hash": (str,),
            "report_hash": (str,),
            "model_topology": (dict,),
        },
    ),
}


# ── Registration helper ─────────────────────────────────


def register_metadata_schema(
    step_type: StepType,
    schema: MetadataSchema,
    *,
    overwrite: bool = False,
) -> None:
    """Register a schema for *step_type* at runtime.

    Use this when downstream code introduces additional StepTypes (for
    example, plugin nodes). Set *overwrite* to ``True`` to replace an
    existing entry; otherwise a duplicate registration raises.
    """
    if not overwrite and step_type in METADATA_REGISTRY:
        raise ValueError(
            f"metadata schema already registered for {step_type.value!r}",
        )
    METADATA_REGISTRY[step_type] = schema


# ── Validator ───────────────────────────────────────────


def validate_metadata(
    step_type: StepType,
    metadata: dict[str, Any],
    *,
    strictness: str | None = None,
) -> None:
    """Validate *metadata* against the registered schema for *step_type*.

    Args:
        step_type: The seal's :class:`StepType`.
        metadata: The (already-normalised) metadata dict that
            :func:`seal_step` is about to hand to the engine.
        strictness: Override the active strictness mode. ``None``
            consults :func:`current_strictness`.

    Raises:
        MetadataSchemaError: When required keys are missing, types
            mismatch, or unknown keys are present and the strictness
            mode is :data:`MetadataStrictness.STRICT`.
    """
    schema = METADATA_REGISTRY.get(step_type)
    if schema is None:
        # Unknown step types are always strict — the registry is the
        # source of truth for the allowed StepType vocabulary.
        raise MetadataSchemaError(
            f"no metadata schema registered for {step_type.value!r}",
        )

    mode = strictness or current_strictness()

    missing = sorted(k for k in schema.required if metadata.get(k) is None)
    if missing:
        raise MetadataSchemaError(
            f"{step_type.value}: missing required metadata keys: {missing}",
        )

    type_errors: list[str] = []
    for key, value in metadata.items():
        constraint = schema.types.get(key)
        if constraint is None or value is None:
            continue
        if not isinstance(value, constraint):
            type_errors.append(
                f"{key}: expected {constraint}, got {type(value).__name__}",
            )
    if type_errors:
        raise MetadataSchemaError(
            f"{step_type.value}: metadata type violation(s): " + "; ".join(type_errors),
        )

    unknown = sorted(set(metadata) - schema.all_keys)
    if not unknown:
        return

    if mode == MetadataStrictness.STRICT:
        raise MetadataSchemaError(
            f"{step_type.value}: unknown metadata keys: {unknown}. "
            f"Known keys: {sorted(schema.all_keys)}. "
            f"Set {METADATA_STRICTNESS_ENV}=1 to downgrade to a warning.",
        )

    logger.warning(
        "%s: unknown metadata keys (lenient mode): %s",
        step_type.value,
        unknown,
    )
