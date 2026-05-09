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
  own dataclasses from ``seal/engine.py``. This keeps the factory
  decoupled — SDK types never leak into node code.

* **Key management**: Environment-based: base64 variables (``*_KEY_B64``),
  or all four ``*_KEY_LOCATION`` paths (raw ML-DSA files; Ed25519 raw or PEM).
  Caller-provided signer/verifier instances are also supported via
  :func:`create_sdk_engine`.

Spec references:
    SDK Spec Sheet §5   Public API surface.
    SDK Spec Sheet §6   Signing & key management.
    SDK Spec Sheet §9   On-disk format.
    D-0 §5.2            Provenance chain requirements.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slop_research_factory.seal.engine import SealReceipt, StepVerification, VerificationReport
from slop_research_factory.types.enums import StepType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_PROVENANCE_SDK_INSTALL_HINT = (
    "antiphoria_sdk is required for provenance sealing. "
    "Install with: uv sync --extra provenance (or: pip install antiphoria-slop-provenance)."
)

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
    """Map an SDK ``GenesisReceipt`` or ``SealReceipt`` to :class:`SealReceipt`."""
    st_raw = sdk_receipt.step_type
    st = st_raw if isinstance(st_raw, StepType) else StepType(str(st_raw))

    content_hash = (
        _strip_hash_prefix(
            getattr(sdk_receipt, "entry_hash", None) or getattr(sdk_receipt, "content_hash", None),
        )
        or ""
    )
    parent_hash = _strip_hash_prefix(
        getattr(sdk_receipt, "previous_hash", None) or getattr(sdk_receipt, "parent_hash", None),
    )

    seal_id = str(getattr(sdk_receipt, "seal_id", "") or uuid.uuid4())

    ts = getattr(sdk_receipt, "timestamp", None)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    elif not isinstance(ts, datetime):
        ts = datetime.now(UTC)

    rp = getattr(sdk_receipt, "receipt_path", None) or getattr(sdk_receipt, "record_path", None)
    receipt_path = Path(rp) if rp else Path(".")
    pp = getattr(sdk_receipt, "payload_path", None)
    payload_path = Path(pp) if pp else receipt_path

    return SealReceipt(
        step_index=int(sdk_receipt.step_index),
        step_type=st,
        seal_id=seal_id,
        content_hash=content_hash,
        parent_hash=parent_hash,
        timestamp=ts,
        receipt_path=receipt_path,
        payload_path=payload_path,
    )


# ── Verification report mapping ──────────────────────────────────────


def _map_step_verification(sdk_step: Any) -> StepVerification:
    """Map an SDK ``StepVerification`` to factory type."""
    rp = getattr(sdk_step, "record_path", None) or getattr(sdk_step, "receipt_path", None)
    receipt_path = Path(rp) if rp else Path(".")
    payload_ok = getattr(
        sdk_step,
        "payload_valid",
        getattr(sdk_step, "content_hashes_valid", True),
    )
    receipt_ok = getattr(
        sdk_step,
        "receipt_valid",
        getattr(sdk_step, "signature_valid", True),
    )
    phm = getattr(sdk_step, "parent_hash_matches", getattr(sdk_step, "previous_hash_matches", True))
    errs = sdk_step.errors if getattr(sdk_step, "errors", None) else []
    return StepVerification(
        step_index=sdk_step.step_index,
        step_type=sdk_step.step_type,
        receipt_path=receipt_path,
        payload_valid=bool(payload_ok),
        receipt_valid=bool(receipt_ok),
        parent_hash_matches=bool(phm),
        canonical_form_valid=bool(getattr(sdk_step, "canonical_form_valid", True)),
        errors=tuple(str(e) for e in errs),
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

    @property
    def run_id(self) -> str:
        """Run identifier (mirrors underlying SDK engine)."""
        return self._engine.run_id

    # ── begin_chain ───────────────────────────────────────────────

    async def begin_chain(
        self,
        *,
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
            receipt.content_hash[:12],
        )
        return receipt

    # ── seal ──────────────────────────────────────────────────────

    async def seal(
        self,
        *,
        step_type: StepType,
        content_file_paths: list[str | Path],
        metadata: dict[str, Any],
    ) -> SealReceipt:
        """Seal a pipeline step.

        Args:
            step_type:          Pipeline step type enum value.
            content_file_paths: Relative paths to content files within workspace.
            metadata:           Step metadata dict.

        Returns:
            A :class:`SealReceipt` for the sealed record.
        """
        step_type_str = step_type.value

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
            receipt.content_hash[:12],
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


# ── SDK hybrid key loading (B64 env vs filesystem) ──────────────────

_KEY_LOCATION_VARS: tuple[str, ...] = (
    "ANTIPHORIA_MLDSA_PUBLIC_KEY_LOCATION",
    "ANTIPHORIA_MLDSA_PRIVATE_KEY_LOCATION",
    "ANTIPHORIA_ED25519_PUBLIC_KEY_LOCATION",
    "ANTIPHORIA_ED25519_PRIVATE_KEY_LOCATION",
)

_KEY_B64_VARS: tuple[str, ...] = (
    "ANTIPHORIA_MLDSA_PUBLIC_KEY_B64",
    "ANTIPHORIA_MLDSA_PRIVATE_KEY_B64",
    "ANTIPHORIA_ED25519_PUBLIC_KEY_B64",
    "ANTIPHORIA_ED25519_PRIVATE_KEY_B64",
)


def _all_b64_vars_non_empty() -> bool:
    return all(os.environ.get(n, "").strip() for n in _KEY_B64_VARS)


def _location_env_nonempty_count() -> int:
    return sum(1 for n in _KEY_LOCATION_VARS if os.environ.get(n, "").strip())


def _read_mldsa_key_file(path: Path) -> bytes:
    """Load raw ML-DSA key bytes (same bytes as base64-decoded env material)."""
    data = path.read_bytes()
    if data.lstrip().startswith(b"-----"):
        raise RuntimeError(
            f"ML-DSA key file {path} appears to be PEM; only raw binary is supported.",
        )
    return data


def _read_ed25519_key_file(path: Path, *, private: bool) -> bytes:
    """Load Ed25519 key bytes from raw file or PEM."""
    data = path.read_bytes()
    if not data.lstrip().startswith(b"-----"):
        return data
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise RuntimeError(
            "PEM-encoded Ed25519 key files require cryptography "
            "(install the provenance extra / antiphoria-slop-provenance).",
        ) from exc

    if private:
        key = serialization.load_pem_private_key(data, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError(f"Expected Ed25519 private key in {path}, got {type(key).__name__}.")
        return key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise RuntimeError(f"Expected Ed25519 public key in {path}, got {type(key).__name__}.")
    return key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _hybrid_keys_from_key_files(hybrid_keys_cls: Any) -> Any:
    paths = tuple(Path(os.environ[n].strip()).expanduser() for n in _KEY_LOCATION_VARS)
    for p in paths:
        if not p.is_file():
            raise RuntimeError(f"Key file does not exist or is not a file: {p}")
    mldsa_pub = _read_mldsa_key_file(paths[0])
    mldsa_priv = _read_mldsa_key_file(paths[1])
    ed_pub = _read_ed25519_key_file(paths[2], private=False)
    ed_priv = _read_ed25519_key_file(paths[3], private=True)
    return hybrid_keys_cls(
        mldsa_public=mldsa_pub,
        ed25519_public=ed_pub,
        mldsa_private=mldsa_priv,
        ed25519_private=ed_priv,
    )


def _resolve_sdk_hybrid_keys() -> Any:
    """Return ``HybridKeys`` from filesystem paths or base64 env (SDK loader)."""

    try:
        from antiphoria_sdk import HybridKeys, load_keys_from_env
    except ImportError as exc:
        raise RuntimeError(_PROVENANCE_SDK_INSTALL_HINT) from exc

    loc_n = _location_env_nonempty_count()
    if loc_n == len(_KEY_LOCATION_VARS):
        if _all_b64_vars_non_empty():
            raise RuntimeError(
                "Set either all four ANTIPHORIA_*_KEY_LOCATION paths or all four "
                "*_KEY_B64 variables, not both.",
            )
        return _hybrid_keys_from_key_files(HybridKeys)

    if loc_n != 0:
        raise RuntimeError(
            "Incomplete ANTIPHORIA_*_KEY_LOCATION: set all four path variables "
            "or omit them and use ANTIPHORIA_*_KEY_B64 instead.",
        )

    return load_keys_from_env(require_private=True)


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
        workspace:           Factory run directory (``workspace_root / run_id``),
                            same as ``antiphoria_sdk.SealEngine`` expects.
        run_id:              Unique run identifier.
        verifier:            Object satisfying SDK's ``Verifier`` protocol.
        file_lock_timeout_s: Timeout for cross-process file lock.
        resume:              If True, resume an existing chain (verifies integrity).

    Returns:
        Configured :class:`SDKSealEngine` adapter.

    Raises:
        RuntimeError: If ``antiphoria_sdk`` is not installed.
        ChainError:   If ``resume=True`` and the chain is broken.

    Note:
        *workspace* must be the factory **run directory**
        (``workspace_root / run_id``), matching ``antiphoria_sdk.SealEngine`` —
        chain and content paths live directly under that directory.
    """
    try:
        from antiphoria_sdk import SealEngine as _SDKEngine
    except ImportError as exc:
        raise RuntimeError(_PROVENANCE_SDK_INSTALL_HINT) from exc

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
    """Create an :class:`SDKSealEngine` with keys from env (B64 or key files).

    Key material is resolved in one of two mutually exclusive ways:

    * **Files:** all of ``ANTIPHORIA_MLDSA_PUBLIC_KEY_LOCATION``,
      ``ANTIPHORIA_MLDSA_PRIVATE_KEY_LOCATION``,
      ``ANTIPHORIA_ED25519_PUBLIC_KEY_LOCATION``,
      ``ANTIPHORIA_ED25519_PRIVATE_KEY_LOCATION`` point to readable files.
      ML-DSA files must be **raw** key bytes. Ed25519 may be raw or **PEM**
      (requires ``cryptography``, via the provenance package).

    * **Base64 env (default when paths unset):**

        * ``ANTIPHORIA_MLDSA_PUBLIC_KEY_B64``
        * ``ANTIPHORIA_MLDSA_PRIVATE_KEY_B64``
        * ``ANTIPHORIA_ED25519_PUBLIC_KEY_B64``
        * ``ANTIPHORIA_ED25519_PRIVATE_KEY_B64``

    Do not set both full path quads and full B64 quads.

    Args:
        workspace:           Run workspace directory (``workspace_root / run_id``), as used by
                            ``antiphoria_sdk.SealEngine``.
        run_id:              Unique run identifier.
        key_id:              Optional key epoch identifier (e.g. "2025-Q3").
        file_lock_timeout_s: Timeout for cross-process file lock.
        resume:              If True, resume an existing chain.

    Returns:
        Configured :class:`SDKSealEngine` adapter.

    Raises:
        RuntimeError: If ``antiphoria_sdk`` is not installed, env configuration
            is invalid, or key files are missing.
    """
    try:
        from antiphoria_sdk import HybridSigner, HybridVerifier
    except ImportError as exc:
        raise RuntimeError(_PROVENANCE_SDK_INSTALL_HINT) from exc

    keys = _resolve_sdk_hybrid_keys()
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
        workspace:          Run workspace directory (``workspace_root / run_id``).
                            Prefer a resolved absolute path so genesis hashing does not
                            pick up accidental ``workspace/…`` relative prefixes.
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

        logger.info(
            "[seal] InMemory engine selected (provenance disabled) — run %s",
            run_id[:8],
        )
        if resume:
            return InMemorySealEngine.resume(
                workspace=workspace,
                run_id=run_id,
            )
        return InMemorySealEngine.create(
            workspace=workspace,
            run_id=run_id,
        )

    # SDK adapter with env-based keys
    return create_sdk_engine_from_env(
        workspace=workspace,
        run_id=run_id,
        key_id=key_id,
        file_lock_timeout_s=file_lock_timeout_s,
        resume=resume,
    )
