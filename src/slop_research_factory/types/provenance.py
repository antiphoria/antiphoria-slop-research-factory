# src/slop_research_factory/types/provenance.py

"""
Provenance types.1–7.3.

Three layers, bottom-up:

  :class:`ProvenanceMetadata`
      Content-specific key-value pairs embedded in each
      seal (model identifiers, artifact hashes, token
      counts). .3.

  :class:`SealRecord`
      One ``slop-seal`` invocation: structural fields
      (hash, parent, timestamp, node, step) plus a
      :class:`ProvenanceMetadata` payload. .1.

  :class:`ProvenanceChain`
      Append-only ordered sequence of :class:`SealRecord`
      instances forming a Merkle-like hash chain.
      Enforces parent-hash linkage on every
      :meth:`~ProvenanceChain.append`. .2.

Design notes:

- ``SealRecord`` and ``ProvenanceMetadata`` are frozen

  dataclasses — immutable once created.
- ``ProvenanceChain`` is a mutable container (append-only).
- All SHA-256 hashes are validated as 64-character lowercase

  hexadecimal on construction.
- Timestamps must be timezone-aware (UTC expected).
- No serialization methods; the workspace manager (Step 2)

  handles persistence.

"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from slop_research_factory.types.enums import NodeName, SealType
from slop_research_factory.types.hashing import SHA256_LOWERCASE_RE

__all__ = [
    "ProvenanceChain",
    "ProvenanceChainError",
    "ProvenanceMetadata",
    "SealRecord",
]

# ── Constants ────────────────────────────────────────────

# ProvenanceMetadata fields validated as SHA-256 when set.

_METADATA_HASH_FIELDS: tuple[str, ...] = (
    "prompt_hash",
    "response_hash",
    "config_hash",
    "brief_hash",
    "output_hash",
    "think_block_hash",
    "critique_hash",
)


# ── Errors ───────────────────────────────────────────────


class ProvenanceChainError(Exception):
    """Raised when a chain integrity invariant is violated.

    Possible causes:

    - First seal has a non-``None`` parent hash.
    - Appended seal's ``parent_hash`` does not match the

      previous seal's ``content_hash``.
    """


# ── ProvenanceMetadata ───────────────────────


@dataclass(frozen=True)
class ProvenanceMetadata:
    """Content-specific key-values embedded in a seal.

    All hash fields, when not ``None``, must be 64-character
    lowercase hexadecimal strings (SHA-256 digests). Token
    counts and ``critique_step`` must be non-negative.

    PRE seals typically populate:
        ``config_hash``, ``prompt_hash``, ``brief_hash``,
        and for Reviser: ``critique_hash``, ``critique_step``.

    POST seals typically populate:
        ``response_hash``, ``output_hash``,
        ``think_block_hash``, ``model_id``,
        ``input_tokens``, ``output_tokens``.

    Attributes:
        model_id: LLM model identifier
                          (e.g. ``"claude-sonnet-4-20250514"``).
        input_tokens: Tokens consumed by the prompt.
        output_tokens: Tokens in the LLM response.
        prompt_hash: SHA-256 of the rendered prompt.
        response_hash: SHA-256 of the raw LLM response.
        config_hash: SHA-256 of the config snapshot.
        brief_hash: SHA-256 of the research brief.
        output_hash: SHA-256 of the parsed output file.
        think_block_hash: SHA-256 of the ``<think>`` block
                          (if present).
        critique_hash: SHA-256 of the Verifier critique
                          (Reviser PRE seals only).
        critique_step: Step index of the critique that
                          triggered revision.
        extra: Arbitrary additional key-value
                          pairs as an immutable tuple of
                          ``(key, value)`` pairs.
    """

    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_hash: str | None = None
    response_hash: str | None = None
    config_hash: str | None = None
    brief_hash: str | None = None
    output_hash: str | None = None
    think_block_hash: str | None = None
    critique_hash: str | None = None
    critique_step: int | None = None
    extra: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in _METADATA_HASH_FIELDS:
            value = getattr(self, name)
            if value is not None and not SHA256_LOWERCASE_RE.match(value):
                raise ValueError(f"{name} must be 64-char lowercase hex or None, got {value!r}")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError(f"input_tokens must be >= 0, got {self.input_tokens}")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError(f"output_tokens must be >= 0, got {self.output_tokens}")
        if self.critique_step is not None and self.critique_step < 0:
            raise ValueError(f"critique_step must be >= 0, got {self.critique_step}")


# ── SealRecord ───────────────────────────────


@dataclass(frozen=True)
class SealRecord:
    """One ``slop-seal`` invocation result.

    Structural fields identify *where* and *when* the seal
    was created. The :attr:`metadata` payload captures
    *what* was sealed.

    Validation (``__post_init__``):

    - ``content_hash``: 64-char lowercase hex (required).
    - ``parent_hash``: 64-char lowercase hex or ``None``.
    - ``timestamp``: must be timezone-aware (UTC expected).
    - ``step_index``: must be ``>= 0``.
    - ``seal_id``: must be non-empty.

    Attributes:
        seal_id: Unique identifier for this seal
                          (typically a UUID or sequential ID).
        content_hash: SHA-256 hex of the sealed content.
        parent_hash: ``content_hash`` of the previous
                          seal in the chain; ``None`` for
                          the first seal.
        timestamp: UTC datetime of seal creation.
        node_name: Pipeline node that produced this
                          seal.
        seal_type: ``PRE`` or ``POST``.
        step_index: Zero-based step index in the run.
        metadata: Content-specific key-value payload.
        raw_seal_output: Raw stdout from ``slop-seal`` CLI
                          invocation (for debugging).
    """

    seal_id: str
    content_hash: str
    parent_hash: str | None
    timestamp: datetime
    node_name: NodeName
    seal_type: SealType
    step_index: int
    metadata: ProvenanceMetadata
    raw_seal_output: str = ""

    def __post_init__(self) -> None:
        if not self.seal_id:
            raise ValueError("seal_id must be non-empty")
        if not SHA256_LOWERCASE_RE.match(self.content_hash):
            raise ValueError(
                f"content_hash must be 64-char lowercase hex, got {self.content_hash!r}"
            )
        if self.parent_hash is not None and not SHA256_LOWERCASE_RE.match(self.parent_hash):
            raise ValueError(
                f"parent_hash must be 64-char lowercase hex or None, got {self.parent_hash!r}"
            )
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        if self.step_index < 0:
            raise ValueError(f"step_index must be >= 0, got {self.step_index}")


# ── ProvenanceChain ──────────────────────────


class ProvenanceChain:
    """Append-only ordered chain of seal records.

    Invariants enforced on :meth:`append`:

    1. The first seal must have ``parent_hash is None``.
    2. Each subsequent seal's ``parent_hash`` must equal

       the previous seal's ``content_hash``.
    3. Seals are never deleted or reordered.

    The chain is conceptually a Merkle-like linked list
    where each node commits to its predecessor's hash.
    """

    def __init__(self) -> None:
        self._seals: list[SealRecord] = []

    # ── Sequence interface ───────────────────────────────

    def __len__(self) -> int:
        return len(self._seals)

    def __getitem__(self, index: int) -> SealRecord:
        return self._seals[index]

    def __iter__(self) -> Iterator[SealRecord]:
        return iter(self._seals)

    def __bool__(self) -> bool:
        return bool(self._seals)

    def __repr__(self) -> str:
        return f"ProvenanceChain(len={len(self._seals)})"

    # ── Properties ───────────────────────────────────────

    @property
    def seals(self) -> tuple[SealRecord, ...]:
        """Immutable snapshot of all seals in chain order."""
        return tuple(self._seals)

    @property
    def latest(self) -> SealRecord | None:
        """Most recently appended seal, or ``None``."""
        if self._seals:
            return self._seals[-1]
        return None

    @property
    def latest_hash(self) -> str | None:
        """``content_hash`` of the latest seal, or ``None``."""
        if self._seals:
            return self._seals[-1].content_hash
        return None

    # ── Mutation ─────────────────────────────────────────

    def append(self, seal: SealRecord) -> None:
        """Append *seal*, enforcing parent-hash linkage.

        Args:
            seal: The seal record to append.

        Raises:
            ProvenanceChainError: If ``parent_hash`` does
                not match the chain's expected value.
        """
        if self._seals:
            expected = self._seals[-1].content_hash
            if seal.parent_hash != expected:
                raise ProvenanceChainError(
                    f"Chain break: parent_hash="
                    f"{seal.parent_hash!r} does not "
                    f"match expected {expected!r}"
                )
        elif seal.parent_hash is not None:
            raise ProvenanceChainError(
                f"First seal must have parent_hash=None, got {seal.parent_hash!r}"
            )
        self._seals.append(seal)

    # ── Verification ─────────────────────────────────────

    def verify_integrity(
        self,
    ) -> tuple[bool, int | None]:
        """Verify full chain parent-hash linkage.

        Returns ``(ok, first_bad_index)`` where *first_bad_index* is
        ``None`` when *ok* is ``True`` (including the empty chain).
        Does **not** re-compute content hashes from files; that is the
        seal engine's job.
        """
        if not self._seals:
            return (True, None)
        if self._seals[0].parent_hash is not None:
            return (False, 0)
        for i in range(1, len(self._seals)):
            expected = self._seals[i - 1].content_hash
            if self._seals[i].parent_hash != expected:
                return (False, i)
        return (True, None)
