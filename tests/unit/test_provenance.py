# tests/unit/test_provenance.py

"""
Unit tests for types/provenance.py.

Covers:
  - ProvenanceMetadata: construction, validation,

    immutability.
  - SealRecord: construction, validation, immutability.
  - ProvenanceChain: append, integrity enforcement,

    sequence interface, verify_integrity.

Spec references:
    D-2 §7.1   SealRecord schema.
    D-2 §7.2   ProvenanceChain schema.
    D-2 §7.3   ProvenanceMetadata schema.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from slop_research_factory.types.enums import (
    NodeName,
    SealType,
)
from slop_research_factory.types.provenance import (
    ProvenanceChain,
    ProvenanceChainError,
    ProvenanceMetadata,
    SealRecord,
)

# ── Test constants ───────────────────────────────────────

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64

TS_1 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
TS_2 = datetime(2025, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
TS_3 = datetime(2025, 1, 1, 0, 2, 0, tzinfo=timezone.utc)
TS_NAIVE = datetime(2025, 1, 1, 0, 0, 0)


# ── Helpers ──────────────────────────────────────────────


def _seal(
    *,
    seal_id: str = "seal-001",
    content_hash: str = HASH_A,
    parent_hash: str | None = None,
    timestamp: datetime = TS_1,
    node_name: NodeName = NodeName.GENERATOR,
    seal_type: SealType = SealType.POST_SEAL,
    step_index: int = 0,
    metadata: ProvenanceMetadata | None = None,
    raw_seal_output: str = "",
) -> SealRecord:
    """Build a SealRecord with sensible defaults."""
    return SealRecord(
        seal_id=seal_id,
        content_hash=content_hash,
        parent_hash=parent_hash,
        timestamp=timestamp,
        node_name=node_name,
        seal_type=seal_type,
        step_index=step_index,
        metadata=metadata or ProvenanceMetadata(),
        raw_seal_output=raw_seal_output,
    )


# ── ProvenanceMetadata ───────────────────────────────────


class TestProvenanceMetadataConstruction:
    """Creation with defaults and full fields."""

    def test_create_empty(self) -> None:
        """All defaults (None / empty tuple) → no error."""
        m = ProvenanceMetadata()
        assert m.model_id is None
        assert m.input_tokens is None
        assert m.output_tokens is None
        assert m.prompt_hash is None
        assert m.extra == ()

    def test_create_with_all_fields(self) -> None:
        """Full construction with every field populated."""
        m = ProvenanceMetadata(
            model_id="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=2000,
            prompt_hash=HASH_A,
            response_hash=HASH_B,
            config_hash=HASH_C,
            brief_hash=HASH_D,
            output_hash=HASH_A,
            think_block_hash=HASH_B,
            critique_hash=HASH_C,
            critique_step=2,
            extra=(("key1", "v1"), ("key2", "v2")),
        )
        assert m.model_id == "claude-sonnet-4-20250514"
        assert m.input_tokens == 1000
        assert m.output_tokens == 2000
        assert m.critique_step == 2
        assert len(m.extra) == 2

    def test_extra_accessible_as_dict(self) -> None:
        """Extra tuples can be converted to dict."""
        extras = (("source", "crossref"), ("doi", "10.1234"))
        m = ProvenanceMetadata(extra=extras)
        assert dict(m.extra)["source"] == "crossref"

    def test_zero_tokens_accepted(self) -> None:
        """Zero is a valid token count."""
        m = ProvenanceMetadata(
            input_tokens=0, output_tokens=0,
        )
        assert m.input_tokens == 0
        assert m.output_tokens == 0


class TestProvenanceMetadataFrozen:
    """Immutability enforcement."""

    def test_cannot_reassign_model_id(self) -> None:
        m = ProvenanceMetadata()
        with pytest.raises(AttributeError):
            m.model_id = "test"  # type: ignore[misc]

    def test_cannot_reassign_prompt_hash(self) -> None:
        m = ProvenanceMetadata(prompt_hash=HASH_A)
        with pytest.raises(AttributeError):
            m.prompt_hash = HASH_B  # type: ignore[misc]


class TestProvenanceMetadataValidation:
    """Hash format and numeric range validation."""

    def test_invalid_prompt_hash(self) -> None:
        with pytest.raises(ValueError, match="prompt_hash"):
            ProvenanceMetadata(prompt_hash="not-a-hash")

    def test_invalid_response_hash(self) -> None:
        with pytest.raises(
            ValueError, match="response_hash",
        ):
            ProvenanceMetadata(response_hash="XYZ")

    def test_invalid_config_hash(self) -> None:
        with pytest.raises(ValueError, match="config_hash"):
            ProvenanceMetadata(config_hash="short")

    def test_uppercase_hex_rejected(self) -> None:
        """Uppercase hex is not accepted."""
        with pytest.raises(ValueError, match="config_hash"):
            ProvenanceMetadata(config_hash="A" * 64)

    def test_short_hash_rejected(self) -> None:
        """63-char hex string → ValueError."""
        with pytest.raises(ValueError, match="brief_hash"):
            ProvenanceMetadata(brief_hash="a" * 63)

    def test_long_hash_rejected(self) -> None:
        """65-char hex string → ValueError."""
        with pytest.raises(
            ValueError, match="output_hash",
        ):
            ProvenanceMetadata(output_hash="b" * 65)

    def test_negative_input_tokens(self) -> None:
        with pytest.raises(
            ValueError, match="input_tokens",
        ):
            ProvenanceMetadata(input_tokens=-1)

    def test_negative_output_tokens(self) -> None:
        with pytest.raises(
            ValueError, match="output_tokens",
        ):
            ProvenanceMetadata(output_tokens=-1)

    def test_negative_critique_step(self) -> None:
        with pytest.raises(
            ValueError, match="critique_step",
        ):
            ProvenanceMetadata(critique_step=-1)


# ── SealRecord ───────────────────────────────────────────


class TestSealRecordConstruction:
    """Valid construction paths."""

    def test_create_first_seal(self) -> None:
        """First seal: parent_hash=None."""
        s = _seal()
        assert s.seal_id == "seal-001"
        assert s.content_hash == HASH_A
        assert s.parent_hash is None
        assert s.node_name is NodeName.GENERATOR
        assert s.seal_type is SealType.POST
        assert s.step_index == 0

    def test_create_chained_seal(self) -> None:
        """Chained seal: parent_hash set."""
        s = _seal(
            parent_hash=HASH_B, content_hash=HASH_C,
        )
        assert s.parent_hash == HASH_B
        assert s.content_hash == HASH_C

    def test_raw_seal_output_default_empty(self) -> None:
        assert _seal().raw_seal_output == ""

    def test_raw_seal_output_stored(self) -> None:
        s = _seal(raw_seal_output='{"ok": true}')
        assert s.raw_seal_output == '{"ok": true}'

    def test_metadata_accessible(self) -> None:
        meta = ProvenanceMetadata(model_id="test-model")
        s = _seal(metadata=meta)
        assert s.metadata.model_id == "test-model"


class TestSealRecordFrozen:
    """Immutability enforcement."""

    def test_cannot_reassign_content_hash(self) -> None:
        s = _seal()
        with pytest.raises(AttributeError):
            s.content_hash = HASH_B  # type: ignore[misc]

    def test_cannot_reassign_seal_id(self) -> None:
        s = _seal()
        with pytest.raises(AttributeError):
            s.seal_id = "other"  # type: ignore[misc]


class TestSealRecordValidation:
    """Hash, timestamp, and field validation."""

    def test_invalid_content_hash(self) -> None:
        with pytest.raises(
            ValueError, match="content_hash",
        ):
            _seal(content_hash="not-valid")

    def test_uppercase_content_hash(self) -> None:
        with pytest.raises(
            ValueError, match="content_hash",
        ):
            _seal(content_hash="A" * 64)

    def test_short_content_hash(self) -> None:
        with pytest.raises(
            ValueError, match="content_hash",
        ):
            _seal(content_hash="a" * 63)

    def test_long_content_hash(self) -> None:
        with pytest.raises(
            ValueError, match="content_hash",
        ):
            _seal(content_hash="a" * 65)

    def test_invalid_parent_hash(self) -> None:
        with pytest.raises(
            ValueError, match="parent_hash",
        ):
            _seal(parent_hash="bad-hash")

    def test_none_parent_hash_accepted(self) -> None:
        s = _seal(parent_hash=None)
        assert s.parent_hash is None

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            _seal(timestamp=TS_NAIVE)

    def test_negative_step_index(self) -> None:
        with pytest.raises(ValueError, match="step_index"):
            _seal(step_index=-1)

    def test_zero_step_index_accepted(self) -> None:
        assert _seal(step_index=0).step_index == 0

    def test_empty_seal_id(self) -> None:
        with pytest.raises(ValueError, match="seal_id"):
            _seal(seal_id="")


# ── ProvenanceChain: empty ───────────────────────────────


class TestProvenanceChainEmpty:
    """Empty chain baseline properties."""

    def test_len_zero(self) -> None:
        assert len(ProvenanceChain()) == 0

    def test_latest_none(self) -> None:
        assert ProvenanceChain().latest is None

    def test_latest_hash_none(self) -> None:
        assert ProvenanceChain().latest_hash is None

    def test_bool_false(self) -> None:
        assert not ProvenanceChain()

    def test_seals_empty_tuple(self) -> None:
        assert ProvenanceChain().seals == ()

    def test_verify_integrity_empty(self) -> None:
        assert ProvenanceChain().verify_integrity() is True

    def test_repr_shows_zero(self) -> None:
        assert "len=0" in repr(ProvenanceChain())


# ── ProvenanceChain: append ──────────────────────────────


class TestProvenanceChainAppend:
    """Append behaviour and chain-break enforcement."""

    def test_append_first_seal(self) -> None:
        chain = ProvenanceChain()
        seal = _seal(
            content_hash=HASH_A, parent_hash=None,
        )
        chain.append(seal)
        assert len(chain) == 1
        assert chain.latest is seal

    def test_first_seal_non_none_parent_rejected(
        self,
    ) -> None:
        chain = ProvenanceChain()
        seal = _seal(parent_hash=HASH_B)
        with pytest.raises(
            ProvenanceChainError, match="None",
        ):
            chain.append(seal)

    def test_append_second_seal_correct_parent(
        self,
    ) -> None:
        chain = ProvenanceChain()
        s1 = _seal(
            seal_id="s1",
            content_hash=HASH_A,
            parent_hash=None,
        )
        s2 = _seal(
            seal_id="s2",
            content_hash=HASH_B,
            parent_hash=HASH_A,
            timestamp=TS_2,
            step_index=1,
        )
        chain.append(s1)
        chain.append(s2)
        assert len(chain) == 2
        assert chain.latest is s2

    def test_second_seal_wrong_parent_rejected(
        self,
    ) -> None:
        chain = ProvenanceChain()
        s1 = _seal(
            content_hash=HASH_A, parent_hash=None,
        )
        chain.append(s1)

        bad = _seal(
            seal_id="s2",
            content_hash=HASH_C,
            parent_hash=HASH_D,
            timestamp=TS_2,
        )
        with pytest.raises(
            ProvenanceChainError, match="Chain break",
        ):
            chain.append(bad)

    def test_chain_not_mutated_on_rejected_append(
        self,
    ) -> None:
        """Failed append leaves chain state unchanged."""
        chain = ProvenanceChain()
        s1 = _seal(
            content_hash=HASH_A, parent_hash=None,
        )
        chain.append(s1)

        bad = _seal(
            seal_id="bad",
            content_hash=HASH_C,
            parent_hash=HASH_D,
            timestamp=TS_2,
        )
        with pytest.raises(ProvenanceChainError):
            chain.append(bad)
        assert len(chain) == 1
        assert chain.latest is s1

    def test_three_seal_chain(self) -> None:
        chain = ProvenanceChain()
        s1 = _seal(
            seal_id="s1",
            content_hash=HASH_A,
            parent_hash=None,
            step_index=0,
        )
        s2 = _seal(
            seal_id="s2",
            content_hash=HASH_B,
            parent_hash=HASH_A,
            timestamp=TS_2,
            step_index=1,
        )
        s3 = _seal(
            seal_id="s3",
            content_hash=HASH_C,
            parent_hash=HASH_B,
            timestamp=TS_3,
            step_index=2,
        )
        chain.append(s1)
        chain.append(s2)
        chain.append(s3)
        assert len(chain) == 3
        assert chain.latest is s3
        assert chain.latest_hash == HASH_C


# ── ProvenanceChain: properties & sequence interface ─────


class TestProvenanceChainProperties:
    """seals, latest_hash, getitem, iter, repr."""

    def _two_seal_chain(self) -> ProvenanceChain:
        chain = ProvenanceChain()
        chain.append(_seal(
            seal_id="s1",
            content_hash=HASH_A,
            parent_hash=None,
        ))
        chain.append(_seal(
            seal_id="s2",
            content_hash=HASH_B,
            parent_hash=HASH_A,
            timestamp=TS_2,
            step_index=1,
        ))
        return chain

    def test_seals_returns_tuple(self) -> None:
        result = self._two_seal_chain().seals
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_seals_is_snapshot(self) -> None:
        """Tuple unaffected by later appends."""
        chain = self._two_seal_chain()
        snapshot = chain.seals
        chain.append(_seal(
            seal_id="s3",
            content_hash=HASH_C,
            parent_hash=HASH_B,
            timestamp=TS_3,
            step_index=2,
        ))
        assert len(snapshot) == 2
        assert len(chain.seals) == 3

    def test_latest_hash(self) -> None:
        assert self._two_seal_chain().latest_hash == HASH_B

    def test_getitem_positive(self) -> None:
        chain = self._two_seal_chain()
        assert chain[0].seal_id == "s1"
        assert chain[1].seal_id == "s2"

    def test_getitem_negative(self) -> None:
        assert self._two_seal_chain()[-1].seal_id == "s2"

    def test_getitem_out_of_range(self) -> None:
        with pytest.raises(IndexError):
            _ = self._two_seal_chain()[99]

    def test_iter_order(self) -> None:
        ids = [s.seal_id for s in self._two_seal_chain()]
        assert ids == ["s1", "s2"]

    def test_bool_true(self) -> None:
        assert bool(self._two_seal_chain()) is True

    def test_repr_includes_length(self) -> None:
        assert "len=2" in repr(self._two_seal_chain())


# ── ProvenanceChain: verify_integrity ────────────────────


class TestProvenanceChainIntegrity:
    """verify_integrity on valid and broken chains."""

    def test_valid_chain(self) -> None:
        chain = ProvenanceChain()
        chain.append(_seal(
            seal_id="s1",
            content_hash=HASH_A,
            parent_hash=None,
        ))
        chain.append(_seal(
            seal_id="s2",
            content_hash=HASH_B,
            parent_hash=HASH_A,
            timestamp=TS_2,
            step_index=1,
        ))
        assert chain.verify_integrity() is True

    def test_single_seal_valid(self) -> None:
        chain = ProvenanceChain()
        chain.append(_seal(
            content_hash=HASH_A, parent_hash=None,
        ))
        assert chain.verify_integrity() is True

    def test_broken_link_detected(self) -> None:
        """Inject broken seal bypassing append guard."""
        chain = ProvenanceChain()
        chain.append(_seal(
            seal_id="s1",
            content_hash=HASH_A,
            parent_hash=None,
        ))
        # Direct injection to bypass integrity check
        broken = _seal(
            seal_id="broken",
            content_hash=HASH_C,
            parent_hash=HASH_D,
            timestamp=TS_2,
            step_index=1,
        )
        chain._seals.append(broken)
        assert chain.verify_integrity() is False

    def test_broken_first_seal_detected(self) -> None:
        """First seal with non-None parent (injected)."""
        chain = ProvenanceChain()
        bad_first = _seal(
            content_hash=HASH_A, parent_hash=HASH_B,
        )
        chain._seals.append(bad_first)
        assert chain.verify_integrity() is False
