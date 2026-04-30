"""Provenance seal layer (D-5).

Public API (M1.1, SDK-aligned):

- :class:`SealEngine` — frozen Protocol consumed by node implementations.
  Stateful: each engine owns one ``(workspace, run_id)`` pair.
- :class:`InMemorySealEngine` — pure-Python reference engine; sufficient
  for development, CI, and integration tests. Production deployments
  swap this for an SDK-backed adapter (M4) without changing call sites.
- :class:`SealReceipt` — slim handle returned by ``begin_chain`` /
  ``seal``. Mirror of ``antiphoria_sdk.SealReceipt``.
- :class:`StepVerification` / :class:`VerificationReport` — per-step and
  aggregate diagnostics from :meth:`SealEngine.verify_chain`. Mirror of
  the SDK's verification shapes.
- :class:`SealError` — single failure mode raised by all engines.
- :func:`seal_step` — canonical helper used by every node (D-5 §4–§5).

The engine swap point is the orchestrator's wire-up call only; nodes
must not import a concrete engine directly.
"""

from slop_research_factory.seal.engine import (
    GENESIS_PARENT_TAG,
    PAYLOAD_SCHEMA_VERSION,
    InMemorySealEngine,
    SealEngine,
    SealError,
    SealReceipt,
    StepVerification,
    VerificationReport,
    canonical_json_bytes,
    compute_content_hash,
    step_type_to_node_seal,
)
from slop_research_factory.seal.helpers import seal_step
from slop_research_factory.seal.registry import (
    METADATA_REGISTRY,
    MetadataSchema,
    MetadataSchemaError,
    MetadataStrictness,
    register_metadata_schema,
    set_metadata_strictness,
    validate_metadata,
)

__all__ = [
    "GENESIS_PARENT_TAG",
    "METADATA_REGISTRY",
    "PAYLOAD_SCHEMA_VERSION",
    "InMemorySealEngine",
    "MetadataSchema",
    "MetadataSchemaError",
    "MetadataStrictness",
    "SealEngine",
    "SealError",
    "SealReceipt",
    "StepVerification",
    "VerificationReport",
    "canonical_json_bytes",
    "compute_content_hash",
    "register_metadata_schema",
    "seal_step",
    "set_metadata_strictness",
    "step_type_to_node_seal",
    "validate_metadata",
]
