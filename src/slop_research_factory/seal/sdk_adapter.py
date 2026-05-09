# seal/sdk_adapter.py
# src/slop_research_factory/seal/sdk_adapter.py

"""
Bridge adapter: wraps ``antiphoria_sdk.SealEngine`` behind the factory's
``SealEngine`` protocol.

This module is the **sole integration point** between the factory and
the provenance SDK. All hash-prefix normalization, type mapping, and
import guarding lives here.

Design decisions:

* **Lazy import**: ``antiphoria_sdk`` is imported at construction time,
  not module load time. This allows the rest of the factory to function
  without the SDK installed (``enable_provenance = false``).

* **Hash prefix stripping**: The SDK returns hashes as ``"sha256:<hex>"``
  while the factory stores bare hex strings. All outbound hashes are
  stripped; no inbound translation is needed because the SDK accepts
  raw file paths (it hashes internally).

* **Type mapping**: SDK receipt/report types are mapped to the factory's
  own dataclasses from ``types/provenance.py``. This keeps the factory
  decoupled — SDK types never leak into node code.

* **Key management**: Delegated entirely to the SDK's ``load_keys_from_env``
  or caller-provided signer/verifier instances. The adapter does not
  handle key generation or rotation.

Spec references:
    SDK Spec Sheet §5   Public API surface.
    SDK Spec Sheet §6   Signing & key management.
    SDK Spec Sheet §9   On-disk format.
    D-0 §5.2            Provenance chain requirements.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slop_research_factory.types.enums import StepType
from slop_research_factory.types.provenance import (
    SealReceipt,
    StepVerification,
    VerificationReport,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

__all__ = [
    "SDKSealEngine",
    "create_sdk_engine",
    "create_sdk_engine_from_env",
]


# ── Hash normalization ───────────────────────────────────────────────

_SHA256_PREFIX = "sha256:"


def _strip_hash_prefix(h: str | None) -> str | None:
    """Strip ``"sha256:"`` prefix from SDK hash strings.

    Factory convention: bare hex (64 chars).
    SDK convention: ``"sha256:<64 hex chars>"``.
    """
    if h is None:
        return None
    if h.startswith(_SHA256_PREFIX):
        return h[len(_SHA256_PREFIX) :]
    return h


def _add_hash_prefix(h: str | None) -> str | None:
    """Add ``"sha256:"`` prefix for SDK consumption (if needed)."""
    if h is None:
        return None
    if h.startswith(_SHA256_PREFIX):
        return h
    return f"{_SHA256_PREFIX}{h}"


# ── Receipt mapping ──────────────────────────────────────────────────


def _map_receipt(sdk_receipt: Any) -> SealReceipt:
    """Map an SDK ``GenesisReceipt`` or ``SealReceipt`` to factory type."""
    return SealReceipt(
        step_index=sdk_receipt.step_index,
        step_type=sdk_receipt.step_type,
        entry_hash=_strip_hash_prefix(sdk_receipt.entry_hash) or "",
        previous_hash=_strip_hash_prefix(sdk_receipt.previous_hash),
        record_path=Path(sdk_receipt.record_path) if sdk_receipt.record_path else None,
        timestamp=sdk_receipt.timestamp,
    )


# ── Verification report mapping ──────────────────────────────────────


def _map_step_verification(sdk_step: Any) -> StepVerification:
    """Map an SDK ``StepVerification`` to factory type."""
    return StepVerification(
        step_index=sdk_step.step_index,
        step_type=sdk_step.step_type,
        record_path=Path(sdk_step.record_path) if sdk_step.record_path else None,
        signature_valid=sdk_step.signature_valid,
        content_hashes_valid=sdk_step.content_hashes_valid,
        previous_hash_matches=sdk_step.previous_hash_matches,
        canonical_form_valid=sdk_step.canonical_form_valid,
        errors=list(sdk_step.errors) if sdk_step.errors else [],
    )


def _map_verification_report(sdk_report: Any) -> VerificationReport:
    """Map an SDK ``VerificationReport`` to factory type."""
    return VerificationReport(
        run_id=sdk_report.run_id,
        chain_intact=sdk_report.chain_intact,
        total_steps=sdk_report.total_steps,
        steps=tuple(_map_step_verification(s) for s in sdk_report.steps),
        first_error_index=sdk_report.first_error_index,
    )


# ── Adapter class ────────────────────────────────────────────────────


class SDKSealEngine:
    """Adapter wrapping ``antiphoria_sdk.SealEngine`` to satisfy the
    factory's :class:`~slop_research_factory.seal.engine.SealEngine`
    protocol.

    All public methods match the factory protocol signature exactly.
    """

    __slots__ = ("_engine", "_workspace")

    def __init__(self, sdk_engine: Any, workspace: Path) -> None:
        """Wrap an already-constructed SDK engine.

        Args:
            sdk_engine: An instance of ``antiphoria_sdk.SealEngine``.
            workspace:  The workspace root (for path resolution context).
        """
        self._engine = sdk_engine
        self._workspace = workspace

    # ── Properties ────────────────────────────────────────────────

    @property
    def latest_hash(self) -> str | None:
        """Hash of the most recent chain record (bare hex, no prefix)."""
        return _strip_hash_prefix(self._engine.latest_hash)

    @property
    def latest_step(self) -> int:
        """Index of the most recent chain record (-1 before genesis)."""
        return self._engine.latest_step

    @property
    def workspace(self) -> Path:
        """Resolved workspace directory."""
        return self._workspace

    @property
    def chain_dir(self) -> Path:
        """Chain directory path."""
        return self._engine.chain_dir

    # ── begin_chain ───────────────────────────────────────────────

    async def begin_chain(
        self,
        research_brief: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SealReceipt:
        """Initialize the provenance chain with a GENESIS seal.

        Args:
            research_brief: Research brief dict stored in genesis metadata.
            metadata:       Additional metadata for the genesis record.

        Returns:
            A :class:`SealReceipt` for the genesis record.
        """
        sdk_receipt = await self._engine.begin_chain(
            research_brief=research_brief,
            metadata=metadata,
        )
        receipt = _map_receipt(sdk_receipt)

        logger.debug(
            "[sdk-adapter] GENESIS sealed (hash=%s…)",
            receipt.entry_hash[:12],
        )
        return receipt

    # ── seal ──────────────────────────────────────────────────────

    async def seal(
        self,
        step_type: StepType | str,
        content_file_paths: list[str | Path],
        metadata: dict[str, Any],
    ) -> SealReceipt:
        """Seal a pipeline step.

        Args:
            step_type:          Step type enum or SCREAMING_SNAKE string.
            content_file_paths: Relative paths to content files within workspace.
            metadata:           Step metadata dict.

        Returns:
            A :class:`SealReceipt` for the sealed record.
        """
        # Normalize step type to string
        step_type_str = step_type.value if isinstance(step_type, StepType) else str(step_type)

        # Normalize paths to strings
        path_strs = [str(p) for p in content_file_paths]

        sdk_receipt = await self._engine.seal(
            step_type=step_type_str,
            content_file_paths=path_strs,
            metadata=metadata,
        )
        receipt = _map_receipt(sdk_receipt)

        logger.debug(
            "[sdk-adapter] %s sealed (step=%d, hash=%s…)",
            step_type_str,
            receipt.step_index,
            receipt.entry_hash[:12],
        )
        return receipt

    # ── verify_chain ──────────────────────────────────────────────

    async def verify_chain(self) -> VerificationReport:
        """Verify the entire chain's cryptographic integrity.

        Returns:
            A :class:`VerificationReport` with per-step detail.
        """
        sdk_report = await self._engine.verify_chain()
        report = _map_verification_report(sdk_report)

        logger.debug(
            "[sdk-adapter] Chain verified: intact=%s, steps=%d",
            report.chain_intact,
            report.total_steps,
        )
        return report

    # ── hash_file ─────────────────────────────────────────────────

    async def hash_file(self, path: str | Path) -> str:
        """Hash a file using the SDK's hasher.

        Args:
            path: Path to the file (absolute or relative to workspace).

        Returns:
            Bare SHA-256 hex string (64 chars, no prefix).
        """
        sdk_hash = await self._engine.hash_file(str(path))
        bare = _strip_hash_prefix(sdk_hash)
        if bare is None:
            raise ValueError(f"SDK returned None hash for {path}")
        return bare


# ── Factory functions ────────────────────────────────────────────────


def create_sdk_engine(
    *,
    workspace: Path,
    run_id: str,
    signer: Any,
    verifier: Any,
    file_lock_timeout_s: float = 30.0,
    resume: bool = False,
) -> SDKSealEngine:
    """Create an :class:`SDKSealEngine` wrapping a fresh or resumed SDK engine.

    Args:
        workspace:           Workspace directory path.
        run_id:              Unique run identifier.
        signer:              Object satisfying SDK's ``Signer`` protocol.
        verifier:            Object satisfying SDK's ``Verifier`` protocol.
        file_lock_timeout_s: Timeout for cross-process file lock.
        resume:              If True, resume an existing chain (verifies integrity).

    Returns:
        Configured :class:`SDKSealEngine` adapter.

    Raises:
        RuntimeError: If ``antiphoria_sdk`` is not installed.
        ChainError:   If ``resume=True`` and the chain is broken.
    """
    try:
        from antiphoria_sdk import SealEngine as _SDKEngine
    except ImportError as exc:
        raise RuntimeError(
            "antiphoria_sdk is required for provenance sealing. "
            "Install with: pip install antiphoria-slop-provenance"
        ) from exc

    workspace = Path(workspace).resolve()

    if resume:
        sdk_engine = _SDKEngine.resume(
            workspace=workspace,
            run_id=run_id,
            signer=signer,
            verifier=verifier,
        )
        logger.info(
            "[sdk-adapter] Resumed chain for run %s (step=%d)",
            run_id[:8],
            sdk_engine.latest_step,
        )
    else:
        sdk_engine = _SDKEngine.create(
            workspace=workspace,
            run_id=run_id,
            signer=signer,
            verifier=verifier,
            file_lock_timeout_s=file_lock_timeout_s,
        )
        logger.info(
            "[sdk-adapter] Created fresh chain for run %s",
            run_id[:8],
        )

    return SDKSealEngine(sdk_engine, workspace)


def create_sdk_engine_from_env(
    *,
    workspace: Path,
    run_id: str,
    key_id: str | None = None,
    file_lock_timeout_s: float = 30.0,
    resume: bool = False,
) -> SDKSealEngine:
    """Create an :class:`SDKSealEngine` with keys loaded from environment variables.

    This is the recommended production entry point. Keys are read from:

    * ``ANTIPHORIA_MLDSA_PUBLIC_KEY_B64``
    * ``ANTIPHORIA_MLDSA_PRIVATE_KEY_B64``
    * ``ANTIPHORIA_ED25519_PUBLIC_KEY_B64``
    * ``ANTIPHORIA_ED25519_PRIVATE_KEY_B64``

    Args:
        workspace:           Workspace directory path.
        run_id:              Unique run identifier.
        key_id:              Optional key epoch identifier (e.g. "2025-Q3").
        file_lock_timeout_s: Timeout for cross-process file lock.
        resume:              If True, resume an existing chain.

    Returns:
        Configured :class:`SDKSealEngine` adapter.

    Raises:
        RuntimeError: If ``antiphoria_sdk`` is not installed or env vars missing.
    """
    try:
        from antiphoria_sdk import (
            HybridSigner,
            HybridVerifier,
            load_keys_from_env,
        )
    except ImportError as exc:
        raise RuntimeError(
            "antiphoria_sdk is required for provenance sealing. "
            "Install with: pip install antiphoria-slop-provenance"
        ) from exc

    keys = load_keys_from_env(require_private=True)
    signer = HybridSigner(keys, key_id=key_id)
    verifier = HybridVerifier({keys.fingerprint: keys.public_only()})

    return create_sdk_engine(
        workspace=workspace,
        run_id=run_id,
        signer=signer,
        verifier=verifier,
        file_lock_timeout_s=file_lock_timeout_s,
        resume=resume,
    )


# ── Engine selector (Phase 4.8) ──────────────────────────────────────


def create_seal_engine(
    *,
    workspace: Path,
    run_id: str,
    enable_provenance: bool,
    key_id: str | None = None,
    file_lock_timeout_s: float = 30.0,
    resume: bool = False,
) -> Any:
    """Factory function: select InMemory or SDK engine based on config.

    This is the **single call site** the orchestrator uses to construct
    the seal engine. All downstream code is engine-agnostic.

    Args:
        workspace:          Workspace directory path.
        run_id:             Unique run identifier.
        enable_provenance:  If True, use SDK adapter; if False, use InMemory.
        key_id:             Key epoch for SDK signer (ignored if InMemory).
        file_lock_timeout_s: Lock timeout (ignored if InMemory).
        resume:             If True, resume existing chain.

    Returns:
        An object satisfying the factory's ``SealEngine`` protocol.
    """
    if not enable_provenance:
        from slop_research_factory.seal.engine import InMemorySealEngine

        engine = InMemorySealEngine(
            workspace=workspace,
            run_id=run_id,
        )
        if resume:
            engine.load_from_disk()
        logger.info(
            "[seal] InMemory engine selected (provenance disabled) — run %s",
            run_id[:8],
        )
        return engine

    # SDK adapter with env-based keys
    return create_sdk_engine_from_env(
        workspace=workspace,
        run_id=run_id,
        key_id=key_id,
        file_lock_timeout_s=file_lock_timeout_s,
        resume=resume,
    )
