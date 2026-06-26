# src/slop_research_factory/seal/helpers.py

"""
``seal_step`` — thin glue between node code and the seal engine.

After M1.1 the engine owns chain bookkeeping (``chain_dir``,
``parent_hash``, payload composition, atomic writes). This helper:

1. Normalises free-form node metadata (``model`` → ``model_id``,
   ``token_counts.{input,output}`` → ``input_tokens`` /
   ``output_tokens`` etc.) so payloads stay schema-stable across the
   factory's heterogeneous nodes.
2. Calls :meth:`SealEngine.seal` with ``(step_type, content_file_paths,
   metadata)``.
3. Mutates ``state.step_index`` and ``state.latest_hash`` from the
   returned :class:`SealReceipt`.
4. Returns ``(state, SealReceipt)``.

Any IO / hash / engine failure is wrapped in :class:`SealError`. State
is left untouched on failure.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from slop_research_factory.seal.engine import (
    SealEngine,
    SealError,
    SealReceipt,
)
from slop_research_factory.seal.registry import (
    MetadataSchemaError,
    validate_metadata,
)

if TYPE_CHECKING:
    from slop_research_factory.types.enums import StepType
    from slop_research_factory.types.state import FactoryState

__all__ = ["seal_step"]

logger = logging.getLogger(__name__)


# ── Public API ──────────────────────────────────────────


async def seal_step(
    *,
    seal_engine: SealEngine,
    state: FactoryState,
    step_type: StepType,
    content_file_paths: list[str],
    metadata: dict[str, Any],
) -> tuple[FactoryState, SealReceipt]:
    """Append one PRE- or POST-seal step; update ``state`` with the new hash.

    Args:
        seal_engine: Engine instance scoped to the run's
            ``(workspace, run_id)``. Must have had
            :meth:`SealEngine.begin_chain` called exactly once before
            the first non-genesis seal.
        state: ``FactoryState`` (or compatible duck).
            ``step_index`` and ``latest_hash`` are overwritten from the
            engine-returned receipt on success only.
        step_type: One of :class:`StepType`. Drives both the
            chain filenames and the ``(NodeName, SealType)`` derivation
            inside the engine.
        content_file_paths: Workspace-relative POSIX paths for the
            artefacts this seal commits to. The engine SHA-256s each
            file; digests land in the canonical payload's
            ``content_files`` array.
        metadata: Free-form metadata dict. Generator-style
            keys (``model``, ``token_counts``) are normalised to
            payload-stable names; ``None`` values are dropped.

    Returns:
        Tuple of ``(mutated FactoryState, SealReceipt)``.

    Raises:
        SealError: On any IO, hash, or engine failure. ``state`` is
            left untouched in that case.
    """
    if not isinstance(seal_engine, SealEngine):  # pragma: no cover - defensive
        raise SealError(
            f"seal_step: engine does not satisfy SealEngine protocol "
            f"({type(seal_engine).__name__})",
        )

    payload_metadata = _normalize_metadata(metadata)

    try:
        validate_metadata(step_type, payload_metadata)
    except MetadataSchemaError as exc:
        raise SealError(f"seal_step: metadata schema violation: {exc}") from exc

    receipt = await seal_engine.seal(
        step_type=step_type,
        content_file_paths=list(content_file_paths),
        metadata=payload_metadata,
    )

    if not isinstance(receipt, SealReceipt):  # pragma: no cover - defensive
        raise SealError(
            f"seal_step: engine returned non-SealReceipt ({type(receipt).__name__})",
        )

    state.step_index = receipt.step_index
    state.latest_hash = receipt.content_hash

    logger.debug(
        "seal_step: %s step=%d hash=%s parent=%s",
        step_type.value,
        receipt.step_index,
        receipt.content_hash[:12],
        (receipt.parent_hash or "GENESIS")[:12],
    )

    return state, receipt


# ── Internal helpers ────────────────────────────────────


def _normalize_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce free-form node metadata into payload-friendly shape.

    - ``model`` → ``model_id``.
    - ``token_counts.input`` / ``.output`` → ``input_tokens`` /
      ``output_tokens`` (top-level).
    - ``token_counts.<other>`` flattens as ``token_counts_<other>``,
      stringified.
    - ``None`` values dropped.
    - Unknown keys pass through verbatim.
    """
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if key == "model":
            out["model_id"] = str(value)
            continue
        if key == "token_counts" and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if sub_value is None:
                    continue
                mapped = _TOKEN_KEY_MAP.get(str(sub_key))
                if mapped is not None:
                    out[mapped] = int(sub_value)
                else:
                    out[f"token_counts_{sub_key}"] = str(sub_value)
            continue
        out[key] = value
    return out


_TOKEN_KEY_MAP: dict[str, str] = {
    "input": "input_tokens",
    "output": "output_tokens",
}
