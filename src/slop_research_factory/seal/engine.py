# src/slop_research_factory/seal/engine.py

"""
Seal engine Protocol + in-memory reference implementation (D-5 §3).

M1.1 contract alignment with antiphoria_sdk
-------------------------------------------
The :class:`SealEngine` Protocol is intentionally shaped to match the
public contract of ``antiphoria_sdk.SealEngine`` (see
``glascannon-ai-draft/how_to.md``). The factory's M4 wire-up will swap
:class:`InMemorySealEngine` for a thin adapter around the real SDK; nodes
and helpers see no API change.

Differences vs. the SDK that we keep deliberately:

* ``step_type`` is a factory :class:`StepType` enum (the SDK accepts a
  string). The M4 adapter converts at the boundary; in-tree code stays
  type-safe.
* ``content_hash``/``parent_hash`` are bare 64-char lowercase hex on the
  factory side. The SDK uses an ``sha256:<hex>`` prefix. The M4 adapter
  prefixes/strips when bridging. Treat ``state.latest_hash`` as an
  engine-defined opaque token: callers compare and forward, never parse.
* The factory writes **two** files per step (``…payload.json`` +
  ``…receipt.json``) because the helper layer commits to a richer
  payload than the SDK's single ``ChainRecord``. Engine swap is still
  transparent because both layouts roundtrip via ``verify_chain``.

Receipt + payload layout
~~~~~~~~~~~~~~~~~~~~~~~~

For every seal operation the engine writes two files under
``{workspace}/chain/``:

``{step_index:06d}_{step_type}.payload.json``
    Canonical JSON payload — the *content* of the seal. This is what the
    chain commits to.

``{step_index:06d}_{step_type}.receipt.json``
    Receipt — engine-authored summary: ``content_hash``, ``parent_hash``,
    ``payload_digest``, ``timestamp``, plus structural fields
    (step_index, step_type, seal_id) for fast indexing during
    :meth:`SealEngine.verify_chain`.

The chain is the totally ordered sequence of receipts, sorted by
``step_index``. Genesis is the receipt with ``parent_hash is None``.

Hash construction (collision-resistant)::

    payload_digest = sha256(canonical_payload_bytes)
    parent_part    = parent_hash if parent_hash is not None else "GENESIS"
    content_hash   = sha256(parent_part || "\\n" || canonical_payload_bytes)

Spec references:
    D-0 §5    Provenance engine integration.
    D-1 §10   Seal classification and sealing of raw bytes.
    D-2 §7    SealRecord / ProvenanceChain types.
    D-5 §3    Seal engine interface.
    D-5 §10   Crash recovery (chain re-verification).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from slop_research_factory.types.enums import NodeName, SealType, StepType
from slop_research_factory.types.hashing import is_valid_sha256_hex

__all__ = [
    "GENESIS_PARENT_TAG",
    "PAYLOAD_SCHEMA_VERSION",
    "InMemorySealEngine",
    "SealEngine",
    "SealError",
    "SealReceipt",
    "StepVerification",
    "VerificationReport",
    "canonical_json_bytes",
    "compute_content_hash",
    "step_type_to_node_seal",
]

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────

PAYLOAD_SCHEMA_VERSION: str = "0.1"
"""Bumped only via D-2 §15 schema-version contract."""

GENESIS_PARENT_TAG: str = "GENESIS"
"""Sentinel string mixed into ``content_hash`` when ``parent_hash`` is None."""

_PAYLOAD_SUFFIX: str = ".payload.json"
_RECEIPT_SUFFIX: str = ".receipt.json"
_CHAIN_DIR_NAME: str = "chain"

# Reserved metadata key for genesis records (mirrors SDK's
# ``begin_chain(research_brief=...)`` ergonomics).
_RESEARCH_BRIEF_KEY: str = "research_brief"

# ``{NNNNNN}_{STEP_TYPE}.{payload|receipt}.json``
_RECORD_FILENAME_RE = re.compile(r"^(?P<step>\d{6})_(?P<type>[A-Z][A-Z0-9_]{0,63})\.receipt\.json$")


# ── Errors ───────────────────────────────────────────────


class SealError(Exception):
    """Raised on any seal-engine failure (D-5 §3.2).

    Wraps lower-level IO / hash / parse errors so callers (notably
    :func:`slop_research_factory.seal.helpers.seal_step`) see a single
    failure mode that maps to ``RunStatus.FAILED`` per D-5 §13.
    """


# ── Step-type → (node, seal-type) mapping ───────────────


_STEP_TYPE_MAP: dict[StepType, tuple[NodeName, SealType]] = {
    StepType.GENESIS: (NodeName.BRIEF, SealType.GENESIS),
    StepType.PRE_GENERATOR: (NodeName.GENERATOR, SealType.PRE_SEAL),
    StepType.POST_GENERATOR: (NodeName.GENERATOR, SealType.POST_SEAL),
    StepType.PRE_VERIFIER: (NodeName.VERIFICATION, SealType.PRE_SEAL),
    StepType.POST_VERIFIER: (NodeName.VERIFICATION, SealType.POST_SEAL),
    StepType.PRE_REVISER: (NodeName.REVISER, SealType.PRE_SEAL),
    StepType.POST_REVISER: (NodeName.REVISER, SealType.POST_SEAL),
    StepType.TOOL_CALL: (NodeName.VERIFICATION, SealType.TOOL_CALL),
    StepType.HUMAN_GATE: (NodeName.HUMAN_RESCUE, SealType.HUMAN_GATE),
    StepType.MANIFEST: (NodeName.END, SealType.MANIFEST),
}


def step_type_to_node_seal(step_type: StepType) -> tuple[NodeName, SealType]:
    """Return the canonical ``(NodeName, SealType)`` pair for *step_type*.

    The mapping is exhaustive over :class:`StepType`; an unknown value
    raises ``KeyError`` rather than silently degrading.
    """
    return _STEP_TYPE_MAP[step_type]


# ── Canonical JSON / hashing helpers ────────────────────


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize *obj* to canonical UTF-8 JSON bytes.

    Sorted keys, no extraneous whitespace, ``\\n`` line endings —
    the byte string that ``content_hash`` commits to. Stable across
    platforms and Python versions for the JSON-representable subset
    we use (no NaN/Inf, no tuples).
    """
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_content_hash(parent_hash: str | None, payload_bytes: bytes) -> str:
    """Return the chain-linking content hash.

    ``content_hash = sha256(parent_part || "\\n" || payload_bytes)``
    where ``parent_part`` is ``parent_hash`` for non-genesis seals or
    :data:`GENESIS_PARENT_TAG` for the chain root.
    """
    parent_part = parent_hash if parent_hash is not None else GENESIS_PARENT_TAG
    if parent_hash is not None and not is_valid_sha256_hex(parent_hash):
        raise SealError(f"parent_hash must be 64-char lowercase hex or None, got {parent_hash!r}")
    h = hashlib.sha256()
    h.update(parent_part.encode("utf-8"))
    h.update(b"\n")
    h.update(payload_bytes)
    return h.hexdigest()


# ── Atomic write ────────────────────────────────────────


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomic ``temp + fsync + replace`` write (POSIX-atomic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_seal_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ── Receipt + verification dataclasses (SDK-shaped) ─────


@dataclass(frozen=True, slots=True)
class SealReceipt:
    """Slim handle returned by :meth:`SealEngine.seal` / ``begin_chain``.

    Mirrors the SDK's ``SealReceipt`` / ``GenesisReceipt`` shape. The
    factory's richer per-seal manifest record (
    :class:`~slop_research_factory.types.provenance.SealRecord`) is built
    by the helper layer on demand and is *not* engine-owned.

    Fields:
        step_index: Monotonically increasing step number; ``0`` for
            genesis.
        step_type: :class:`StepType` of the sealed step.
        seal_id: Stable UUID identifying this seal across the chain.
        content_hash: 64-char lowercase hex. The token written to
            ``state.latest_hash``; opaque to non-engine callers.
        parent_hash: ``content_hash`` of the previous step or ``None``
            for genesis.
        timestamp: UTC ``datetime`` (timezone-aware).
        receipt_path: Absolute path to the persisted ``.receipt.json``.
        payload_path: Absolute path to the persisted ``.payload.json``.
    """

    step_index: int
    step_type: StepType
    seal_id: str
    content_hash: str
    parent_hash: str | None
    timestamp: datetime
    receipt_path: Path
    payload_path: Path


@dataclass(frozen=True, slots=True)
class StepVerification:
    """Per-step diagnostic produced by :meth:`SealEngine.verify_chain`.

    Mirrors the SDK's ``StepVerification`` shape. ``ok`` is the AND of
    the four boolean fields plus an empty ``errors`` tuple.
    """

    step_index: int
    step_type: str
    receipt_path: Path
    payload_valid: bool
    receipt_valid: bool
    parent_hash_matches: bool
    canonical_form_valid: bool
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.payload_valid
            and self.receipt_valid
            and self.parent_hash_matches
            and self.canonical_form_valid
            and not self.errors
        )


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Aggregate verification result. Mirrors SDK's ``VerificationReport``.

    ``chain_intact`` is True iff every :class:`StepVerification` is
    ``ok``. ``first_error_index`` points to the first failing step or
    is ``None`` on a clean chain.
    """

    run_id: str
    chain_intact: bool
    total_steps: int
    steps: tuple[StepVerification, ...]
    first_error_index: int | None = None

    def summary(self) -> str:
        if self.chain_intact:
            return f"Chain intact: {self.total_steps} step(s) verified for run {self.run_id}."
        return (
            f"Chain BROKEN for run {self.run_id}: "
            f"first error at step {self.first_error_index} of {self.total_steps}."
        )

    # Back-compat tuple unpack: ``ok, errors = report``.
    def as_tuple(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for step in self.steps:
            errors.extend(f"{step.receipt_path.name}: {e}" for e in step.errors)
        return self.chain_intact, errors


# ── SealEngine Protocol ─────────────────────────────────


@runtime_checkable
class SealEngine(Protocol):
    """Frozen contract for any concrete seal engine.

    Stateful: each engine owns one (``workspace``, ``run_id``) pair.
    Mirror of ``antiphoria_sdk.SealEngine`` so the M4 swap is a one-line
    change at orchestrator wire-up.
    """

    @property
    def workspace(self) -> Path: ...

    @property
    def run_id(self) -> str: ...

    @property
    def chain_dir(self) -> Path: ...

    @property
    def latest_hash(self) -> str | None:
        """Most recent step's ``content_hash``, or ``None`` before genesis."""
        ...

    @property
    def latest_step(self) -> int:
        """Last sealed step index, or ``-1`` before genesis."""
        ...

    async def hash_file(self, path: str | Path) -> str:
        """Return lowercase SHA-256 hex of the file at *path*.

        *path* may be absolute or relative to ``workspace``.
        """
        ...

    async def begin_chain(
        self,
        *,
        research_brief: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SealReceipt:
        """Write the GENESIS record. Must be called exactly once.

        ``research_brief`` is stored at the reserved
        ``metadata.research_brief`` key. Passing ``research_brief`` *and*
        ``metadata={"research_brief": ...}`` is rejected.

        Raises:
            SealError: If genesis is already sealed or the chain
                directory is non-empty.
        """
        ...

    async def seal(
        self,
        *,
        step_type: StepType,
        content_file_paths: list[str | Path],
        metadata: dict[str, Any],
    ) -> SealReceipt:
        """Hash content files, build canonical payload, sign + persist.

        *content_file_paths* are workspace-relative POSIX paths or
        absolute paths under ``workspace``. Each is SHA-256'd and
        recorded in the payload's ``content_files`` array (sorted by
        relative path for byte-stable output).

        Raises:
            SealError: On any IO / hash failure or on attempts to seal
                before :meth:`begin_chain`.
        """
        ...

    async def verify_chain(self) -> VerificationReport:
        """Re-verify the chain on disk, ignoring in-memory state."""
        ...


# ── In-memory reference implementation ──────────────────


class InMemorySealEngine:
    """Pure-Python reference seal engine.

    Owns ``(workspace, run_id)``. Suitable for development, CI, and
    integration tests. Honours the same canonical hashing rules a future
    SDK-backed adapter would; chains produced here are byte-for-byte
    verifiable by any impl that follows :func:`canonical_json_bytes` and
    :func:`compute_content_hash`.

    Thread-safety: not thread-safe. Phase 1 runs are single-threaded
    per D-0 §7.
    """

    def __init__(
        self,
        *,
        workspace: Path | str,
        run_id: str,
        hash_chunk_size: int = 1 << 20,
    ) -> None:
        if not run_id or not run_id.strip():
            raise SealError("InMemorySealEngine: run_id must be non-empty")
        self._workspace = Path(workspace).resolve()
        self._run_id = run_id
        self._chain_dir = self._workspace / _CHAIN_DIR_NAME
        self._chunk = max(int(hash_chunk_size), 4096)
        self._latest_hash: str | None = None
        self._latest_step: int = -1

    # ── classmethod constructors ────────────────────────

    @classmethod
    def create(
        cls,
        workspace: Path | str,
        run_id: str,
        *,
        hash_chunk_size: int = 1 << 20,
    ) -> InMemorySealEngine:
        """Create a fresh engine and ensure ``workspace/chain/`` exists.

        Mirrors the SDK's ``SealEngine.create`` ergonomics so tests and
        the future M4 adapter share a single construction signature.
        """
        ws = Path(workspace).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        (ws / _CHAIN_DIR_NAME).mkdir(exist_ok=True)
        return cls(workspace=ws, run_id=run_id, hash_chunk_size=hash_chunk_size)

    @classmethod
    def resume(
        cls,
        workspace: Path | str,
        run_id: str,
        *,
        hash_chunk_size: int = 1 << 20,
    ) -> InMemorySealEngine:
        """Reopen an existing workspace; verifies the full chain first.

        Raises:
            SealError: If the chain on disk is invalid.
        """
        engine = cls.create(workspace, run_id, hash_chunk_size=hash_chunk_size)
        report = engine._verify_chain_sync()
        if not report.chain_intact:
            raise SealError(
                f"Cannot resume: chain at {workspace} is invalid. "
                f"First error at step {report.first_error_index}."
            )
        if report.total_steps == 0:
            return engine
        last_idx, last_receipt = engine._receipt_files()[-1]
        receipt = json.loads(last_receipt.read_text(encoding="utf-8"))
        engine._latest_step = last_idx
        engine._latest_hash = str(receipt["content_hash"])
        return engine

    # ── properties ──────────────────────────────────────

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def chain_dir(self) -> Path:
        return self._chain_dir

    @property
    def latest_hash(self) -> str | None:
        return self._latest_hash

    @property
    def latest_step(self) -> int:
        return self._latest_step

    # ── hashing ─────────────────────────────────────────

    async def hash_file(self, path: str | Path) -> str:
        """Stream-hash *path* with SHA-256.

        Absolute paths are read as-is; relative paths resolve under
        ``workspace``.
        """
        try:
            abs_path = self._abs(path)
            h = hashlib.sha256()
            with open(abs_path, "rb") as fh:
                while True:
                    chunk = fh.read(self._chunk)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except OSError as exc:
            raise SealError(f"hash_file failed for {path!r}: {exc}") from exc

    # ── begin_chain ─────────────────────────────────────

    async def begin_chain(
        self,
        *,
        research_brief: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SealReceipt:
        if self._latest_hash is not None or self._latest_step != -1:
            raise SealError("begin_chain: chain already initialised")
        if any(self._chain_dir.iterdir()):
            raise SealError(
                f"begin_chain refused: {self._chain_dir} is not empty",
            )

        genesis_meta: dict[str, Any] = dict(metadata) if metadata else {}
        if research_brief is not None:
            if _RESEARCH_BRIEF_KEY in genesis_meta:
                raise SealError(
                    f"begin_chain: {_RESEARCH_BRIEF_KEY!r} reserved at GENESIS; "
                    "do not pass it in metadata when also using research_brief",
                )
            genesis_meta[_RESEARCH_BRIEF_KEY] = research_brief

        return await self._write_step(
            step_type=StepType.GENESIS,
            step_index=0,
            content_files=[],
            metadata=genesis_meta,
            parent_hash=None,
        )

    # ── seal ────────────────────────────────────────────

    async def seal(
        self,
        *,
        step_type: StepType,
        content_file_paths: list[str | Path],
        metadata: dict[str, Any],
    ) -> SealReceipt:
        if step_type is StepType.GENESIS:
            raise SealError("seal: use begin_chain() for GENESIS records")
        if self._latest_hash is None:
            raise SealError("seal: no genesis record found; call begin_chain() first")

        content_files = await self._hash_content_files(content_file_paths)
        next_step = self._latest_step + 1
        return await self._write_step(
            step_type=step_type,
            step_index=next_step,
            content_files=content_files,
            metadata=dict(metadata),
            parent_hash=self._latest_hash,
        )

    # ── verify ──────────────────────────────────────────

    async def verify_chain(self) -> VerificationReport:
        return self._verify_chain_sync()

    # ── internals ───────────────────────────────────────

    def _abs(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return self._workspace / p

    async def _hash_content_files(
        self,
        relative_paths: list[str | Path],
    ) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for raw in relative_paths:
            rel_norm = str(raw).replace("\\", "/")
            digest = await self.hash_file(rel_norm)
            if not is_valid_sha256_hex(digest):
                raise SealError(
                    f"engine produced non-sha256 digest for {rel_norm!r}: {digest!r}",
                )
            out.append({"path": rel_norm, "sha256": digest})
        out.sort(key=lambda d: d["path"])
        return out

    async def _write_step(
        self,
        *,
        step_type: StepType,
        step_index: int,
        content_files: list[dict[str, str]],
        metadata: dict[str, Any],
        parent_hash: str | None,
    ) -> SealReceipt:
        seal_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC)

        payload_obj: dict[str, Any] = {
            "_schema_version": PAYLOAD_SCHEMA_VERSION,
            "seal_id": seal_id,
            "step_index": step_index,
            "step_type": step_type.value,
            "run_id": self._run_id,
            "timestamp": timestamp.isoformat(),
            "metadata": metadata,
            "content_files": content_files,
        }
        canonical = canonical_json_bytes(payload_obj)
        payload_digest = hashlib.sha256(canonical).hexdigest()
        content_hash = compute_content_hash(parent_hash, canonical)

        node_name, seal_type = step_type_to_node_seal(step_type)
        base_name = f"{step_index:06d}_{step_type.value}"
        payload_path = self._chain_dir / f"{base_name}{_PAYLOAD_SUFFIX}"
        receipt_path = self._chain_dir / f"{base_name}{_RECEIPT_SUFFIX}"

        if payload_path.exists() or receipt_path.exists():
            raise SealError(
                f"refusing to overwrite existing chain files at step {step_index}",
            )

        receipt_dict: dict[str, Any] = {
            "_schema_version": PAYLOAD_SCHEMA_VERSION,
            "seal_id": seal_id,
            "step_index": step_index,
            "step_type": step_type.value,
            "node_name": node_name.value,
            "seal_type": seal_type.value,
            "run_id": self._run_id,
            "timestamp": timestamp.isoformat(),
            "parent_hash": parent_hash,
            "content_hash": content_hash,
            "payload_path": payload_path.name,
            "payload_digest": payload_digest,
        }

        try:
            _atomic_write_bytes(payload_path, canonical + b"\n")
            _atomic_write_bytes(
                receipt_path,
                canonical_json_bytes(receipt_dict) + b"\n",
            )
        except OSError as exc:
            raise SealError(f"failed to persist step {step_index}: {exc}") from exc

        self._latest_hash = content_hash
        self._latest_step = step_index

        logger.debug(
            "seal: %s step=%d hash=%s parent=%s",
            step_type.value,
            step_index,
            content_hash[:12],
            (parent_hash or "GENESIS")[:12],
        )

        return SealReceipt(
            step_index=step_index,
            step_type=step_type,
            seal_id=seal_id,
            content_hash=content_hash,
            parent_hash=parent_hash,
            timestamp=timestamp,
            receipt_path=receipt_path,
            payload_path=payload_path,
        )

    def _receipt_files(self) -> list[tuple[int, Path]]:
        out: list[tuple[int, Path]] = []
        if not self._chain_dir.is_dir():
            return out
        for p in self._chain_dir.iterdir():
            m = _RECORD_FILENAME_RE.match(p.name)
            if not m:
                continue
            out.append((int(m.group("step")), p))
        out.sort(key=lambda t: t[0])
        return out

    def _verify_chain_sync(self) -> VerificationReport:
        steps: list[StepVerification] = []
        run_id_seen: str | None = None
        chain_intact = True
        first_error: int | None = None
        expected_prev: str | None = None

        if not self._chain_dir.is_dir():
            return VerificationReport(
                run_id=self._run_id,
                chain_intact=False,
                total_steps=0,
                steps=(),
                first_error_index=None,
            )

        receipts = self._receipt_files()
        for ordinal, (idx, receipt_path) in enumerate(receipts):
            errors: list[str] = []
            payload_valid = False
            receipt_valid = False
            parent_hash_matches = False
            canonical_form_valid = False
            parsed_step_type = ""

            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt_valid = True
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"receipt unreadable: {exc}")
                receipt = None

            payload_full: Path | None = None
            if receipt is not None:
                parsed_step_type = str(receipt.get("step_type", ""))
                payload_rel = receipt.get("payload_path")
                stored_content = receipt.get("content_hash")
                stored_digest = receipt.get("payload_digest")
                stored_run = receipt.get("run_id")

                if not isinstance(payload_rel, str):
                    errors.append("missing payload_path")
                elif not isinstance(stored_content, str) or not is_valid_sha256_hex(stored_content):
                    errors.append("malformed content_hash")
                elif not isinstance(stored_digest, str) or not is_valid_sha256_hex(stored_digest):
                    errors.append("malformed payload_digest")
                else:
                    payload_full = (self._chain_dir / payload_rel).resolve()

                if isinstance(stored_run, str):
                    if run_id_seen is None:
                        run_id_seen = stored_run
                    elif stored_run != run_id_seen:
                        errors.append(
                            f"run_id mismatch inside chain: "
                            f"saw {run_id_seen!r} then {stored_run!r}",
                        )

                if int(receipt.get("step_index", -1)) != idx:
                    errors.append(
                        f"step_index mismatch: filename={idx}, receipt={receipt.get('step_index')}",
                    )

            if payload_full is not None and payload_full.is_file():
                try:
                    payload_bytes = payload_full.read_bytes()
                    payload_obj = json.loads(payload_bytes.decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"payload unreadable: {exc}")
                    payload_obj = None
                else:
                    canon = canonical_json_bytes(payload_obj)
                    canonical_form_valid = canon + b"\n" == payload_bytes or canon == payload_bytes
                    if not canonical_form_valid:
                        errors.append(
                            "payload not in canonical form (tampered or non-canonical writer)",
                        )

                    actual_digest = hashlib.sha256(canon).hexdigest()
                    payload_valid = actual_digest == receipt["payload_digest"]
                    if not payload_valid:
                        errors.append(
                            "payload_digest mismatch (tampered payload)",
                        )

                    actual_content = compute_content_hash(receipt.get("parent_hash"), canon)
                    if actual_content != receipt["content_hash"]:
                        errors.append(
                            "content_hash mismatch (tampered receipt)",
                        )
            elif receipt is not None and payload_full is not None:
                errors.append(f"payload not found at {payload_full.name}")

            if receipt is not None:
                if ordinal == 0:
                    parent_hash_matches = receipt.get("parent_hash") is None
                    if not parent_hash_matches:
                        errors.append("genesis must have parent_hash=null")
                    if parsed_step_type != StepType.GENESIS.value:
                        errors.append(
                            f"first record must be GENESIS, got {parsed_step_type!r}",
                        )
                else:
                    parent_hash_matches = receipt.get("parent_hash") == expected_prev
                    if not parent_hash_matches:
                        errors.append(
                            f"parent_hash break "
                            f"(expected {expected_prev!r}, got {receipt.get('parent_hash')!r})",
                        )
                    if parsed_step_type == StepType.GENESIS.value:
                        errors.append(
                            f"GENESIS only allowed at step 0, saw at step {idx}",
                        )

                expected_prev = receipt.get("content_hash")

            step_ok = (
                receipt_valid
                and payload_valid
                and parent_hash_matches
                and canonical_form_valid
                and not errors
            )
            if not step_ok:
                chain_intact = False
                if first_error is None:
                    first_error = ordinal

            steps.append(
                StepVerification(
                    step_index=idx,
                    step_type=parsed_step_type,
                    receipt_path=receipt_path,
                    payload_valid=payload_valid,
                    receipt_valid=receipt_valid,
                    parent_hash_matches=parent_hash_matches,
                    canonical_form_valid=canonical_form_valid,
                    errors=tuple(errors),
                ),
            )

        if not receipts:
            return VerificationReport(
                run_id=run_id_seen or self._run_id,
                chain_intact=False,
                total_steps=0,
                steps=(),
                first_error_index=None,
            )

        return VerificationReport(
            run_id=run_id_seen or self._run_id,
            chain_intact=chain_intact,
            total_steps=len(steps),
            steps=tuple(steps),
            first_error_index=first_error,
        )
