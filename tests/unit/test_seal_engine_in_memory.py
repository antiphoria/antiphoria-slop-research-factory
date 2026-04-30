# tests/unit/test_seal_engine_in_memory.py

"""
Unit tests for the in-memory seal engine after M1.1 (SDK-aligned contract).

Covers:

- ``hash_file`` streaming + edge cases.
- ``begin_chain`` writes a genesis seal with ``parent_hash=None`` and
  rejects double-init / non-empty chain dirs.
- ``seal`` chains to ``latest_hash`` from the engine's in-memory state,
  refuses to be called before genesis, and refuses ``StepType.GENESIS``.
- ``verify_chain`` reports OK on a clean chain and surfaces tamper /
  break diagnostics with the offending receipt's filename.
- ``InMemorySealEngine`` satisfies the runtime ``SealEngine`` Protocol.

No slop-cli; no network. Every fixture stays in ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from pathlib import Path

import pytest

from slop_research_factory.seal.engine import (
    GENESIS_PARENT_TAG,
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
from slop_research_factory.types.enums import NodeName, SealType, StepType
from slop_research_factory.types.hashing import is_valid_sha256_hex

# ── Helpers ──────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path: Path) -> InMemorySealEngine:
    return InMemorySealEngine.create(tmp_path, run_id="run-001")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _write_artefact(workspace: Path, rel: str, content: bytes) -> str:
    """Write ``content`` to ``workspace/rel`` and return ``rel``."""
    p = workspace / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return rel


# ── Construction ─────────────────────────────────────────


class TestConstruction:
    def test_create_initialises_chain_dir(self, tmp_path: Path) -> None:
        engine = InMemorySealEngine.create(tmp_path, run_id="r")
        assert engine.chain_dir == (tmp_path / "chain")
        assert engine.chain_dir.is_dir()

    def test_workspace_is_resolved(self, tmp_path: Path) -> None:
        engine = InMemorySealEngine.create(tmp_path, run_id="r")
        assert engine.workspace == tmp_path.resolve()

    def test_pre_genesis_state(self, tmp_path: Path) -> None:
        engine = InMemorySealEngine.create(tmp_path, run_id="r")
        assert engine.latest_hash is None
        assert engine.latest_step == -1
        assert engine.run_id == "r"

    def test_empty_run_id_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SealError):
            InMemorySealEngine.create(tmp_path, run_id="")
        with pytest.raises(SealError):
            InMemorySealEngine.create(tmp_path, run_id="   ")


# ── hash_file ────────────────────────────────────────────


class TestHashFile:
    @pytest.mark.asyncio
    async def test_known_value_small(self, engine: InMemorySealEngine, workspace: Path) -> None:
        f = workspace / "x.bin"
        f.write_bytes(b"hello")
        digest = await engine.hash_file(str(f))
        assert digest == hashlib.sha256(b"hello").hexdigest()

    @pytest.mark.asyncio
    async def test_relative_path_resolves_under_workspace(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        _write_artefact(workspace, "drafts/y.txt", b"y")
        digest = await engine.hash_file("drafts/y.txt")
        assert digest == hashlib.sha256(b"y").hexdigest()

    @pytest.mark.asyncio
    async def test_streaming_large_file_matches_oneshot(self, tmp_path: Path) -> None:
        engine = InMemorySealEngine.create(tmp_path, run_id="r", hash_chunk_size=8192)
        data = b"abcd" * (1 << 18)  # 1 MiB
        f = tmp_path / "big.bin"
        f.write_bytes(data)
        digest = await engine.hash_file(str(f))
        assert digest == hashlib.sha256(data).hexdigest()

    @pytest.mark.asyncio
    async def test_returns_lowercase_hex(self, engine: InMemorySealEngine, workspace: Path) -> None:
        f = workspace / "x.bin"
        f.write_bytes(b"\x00\x01\x02")
        digest = await engine.hash_file(str(f))
        assert is_valid_sha256_hex(digest)
        assert digest == digest.lower()

    @pytest.mark.asyncio
    async def test_missing_file_raises_seal_error(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        with pytest.raises(SealError):
            await engine.hash_file(str(workspace / "does-not-exist"))


# ── begin_chain ──────────────────────────────────────────


class TestBeginChain:
    @pytest.mark.asyncio
    async def test_genesis_has_no_parent(self, engine: InMemorySealEngine) -> None:
        receipt = await engine.begin_chain(research_brief={"title": "t"})
        assert isinstance(receipt, SealReceipt)
        assert receipt.parent_hash is None
        assert receipt.step_index == 0
        assert receipt.step_type is StepType.GENESIS
        assert is_valid_sha256_hex(receipt.content_hash)
        assert receipt.timestamp.tzinfo is UTC
        assert receipt.payload_path.is_file()
        assert receipt.receipt_path.is_file()

    @pytest.mark.asyncio
    async def test_engine_state_advances(self, engine: InMemorySealEngine) -> None:
        receipt = await engine.begin_chain()
        assert engine.latest_step == 0
        assert engine.latest_hash == receipt.content_hash

    @pytest.mark.asyncio
    async def test_double_init_rejected(self, engine: InMemorySealEngine) -> None:
        await engine.begin_chain()
        with pytest.raises(SealError, match="already initialised"):
            await engine.begin_chain()

    @pytest.mark.asyncio
    async def test_non_empty_chain_dir_rejected(self, tmp_path: Path) -> None:
        engine = InMemorySealEngine.create(tmp_path, run_id="r")
        (engine.chain_dir / "leftover.txt").write_text("debris")
        with pytest.raises(SealError, match="not empty"):
            await engine.begin_chain()

    @pytest.mark.asyncio
    async def test_research_brief_collision_rejected(self, engine: InMemorySealEngine) -> None:
        with pytest.raises(SealError, match="reserved"):
            await engine.begin_chain(
                research_brief={"a": 1},
                metadata={"research_brief": {"a": 2}},
            )

    @pytest.mark.asyncio
    async def test_research_brief_lands_in_payload(self, engine: InMemorySealEngine) -> None:
        receipt = await engine.begin_chain(research_brief={"thesis": "T"})
        payload = json.loads(receipt.payload_path.read_text("utf-8"))
        assert payload["metadata"]["research_brief"] == {"thesis": "T"}


# ── seal ────────────────────────────────────────────────


class TestSeal:
    @pytest.mark.asyncio
    async def test_seal_before_genesis_rejected(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        _write_artefact(workspace, "drafts/x.md", b"x")
        with pytest.raises(SealError, match="genesis"):
            await engine.seal(
                step_type=StepType.PRE_GENERATOR,
                content_file_paths=["drafts/x.md"],
                metadata={},
            )

    @pytest.mark.asyncio
    async def test_seal_genesis_step_type_rejected(self, engine: InMemorySealEngine) -> None:
        await engine.begin_chain()
        with pytest.raises(SealError, match="begin_chain"):
            await engine.seal(
                step_type=StepType.GENESIS,
                content_file_paths=[],
                metadata={},
            )

    @pytest.mark.asyncio
    async def test_first_post_genesis_links_to_genesis(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        genesis = await engine.begin_chain()
        _write_artefact(workspace, "drafts/p.md", b"p")
        receipt = await engine.seal(
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/p.md"],
            metadata={"prompt_version": "v0.1"},
        )
        assert receipt.step_index == 1
        assert receipt.parent_hash == genesis.content_hash
        assert receipt.step_type is StepType.PRE_GENERATOR

    @pytest.mark.asyncio
    async def test_chain_link_matches_compute_content_hash(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        await engine.begin_chain()
        _write_artefact(workspace, "drafts/p.md", b"x")
        receipt = await engine.seal(
            step_type=StepType.POST_GENERATOR,
            content_file_paths=["drafts/p.md"],
            metadata={},
        )
        canonical = canonical_json_bytes(json.loads(receipt.payload_path.read_text("utf-8")))
        assert receipt.content_hash == compute_content_hash(receipt.parent_hash, canonical)

    @pytest.mark.asyncio
    async def test_receipt_records_payload_digest_and_parent(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        genesis = await engine.begin_chain()
        _write_artefact(workspace, "drafts/p.md", b"p")
        receipt = await engine.seal(
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/p.md"],
            metadata={},
        )
        on_disk = json.loads(receipt.receipt_path.read_text("utf-8"))
        assert on_disk["parent_hash"] == genesis.content_hash
        assert on_disk["content_hash"] == receipt.content_hash
        assert on_disk["step_index"] == 1
        assert on_disk["step_type"] == StepType.PRE_GENERATOR.value
        assert on_disk["payload_path"].endswith(".payload.json")
        assert is_valid_sha256_hex(on_disk["payload_digest"])

    @pytest.mark.asyncio
    async def test_missing_content_file_raises(self, engine: InMemorySealEngine) -> None:
        await engine.begin_chain()
        with pytest.raises(SealError):
            await engine.seal(
                step_type=StepType.PRE_GENERATOR,
                content_file_paths=["drafts/missing.md"],
                metadata={},
            )

    @pytest.mark.asyncio
    async def test_node_name_and_seal_type_in_receipt(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        await engine.begin_chain()
        _write_artefact(workspace, "drafts/p.md", b"p")
        receipt = await engine.seal(
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/p.md"],
            metadata={},
        )
        on_disk = json.loads(receipt.receipt_path.read_text("utf-8"))
        assert on_disk["node_name"] == NodeName.GENERATOR.value
        assert on_disk["seal_type"] == SealType.PRE_SEAL.value


# ── verify_chain ───────────────────────────────────────


async def _build_three_seal_chain(
    engine: InMemorySealEngine, workspace: Path
) -> tuple[SealReceipt, SealReceipt, SealReceipt]:
    genesis = await engine.begin_chain(research_brief={"title": "t"})
    _write_artefact(workspace, "drafts/prompt.md", b"prompt")
    pre = await engine.seal(
        step_type=StepType.PRE_GENERATOR,
        content_file_paths=["drafts/prompt.md"],
        metadata={"prompt_version": "v0.1"},
    )
    _write_artefact(workspace, "drafts/output.md", b"output")
    post = await engine.seal(
        step_type=StepType.POST_GENERATOR,
        content_file_paths=["drafts/output.md"],
        metadata={"cycle": 1},
    )
    return genesis, pre, post


class TestVerifyChain:
    @pytest.mark.asyncio
    async def test_clean_chain_verifies(self, engine: InMemorySealEngine, workspace: Path) -> None:
        await _build_three_seal_chain(engine, workspace)
        report = await engine.verify_chain()
        assert isinstance(report, VerificationReport)
        assert report.chain_intact, report.summary()
        assert report.total_steps == 3
        assert report.first_error_index is None
        assert all(isinstance(s, StepVerification) and s.ok for s in report.steps)

    @pytest.mark.asyncio
    async def test_empty_chain_dir_returns_broken(self, engine: InMemorySealEngine) -> None:
        report = await engine.verify_chain()
        assert not report.chain_intact
        assert report.total_steps == 0

    @pytest.mark.asyncio
    async def test_tampered_payload_detected(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        _, pre, _ = await _build_three_seal_chain(engine, workspace)
        original = json.loads(pre.payload_path.read_text("utf-8"))
        original["metadata"] = {"injected": "garbage"}
        pre.payload_path.write_bytes(canonical_json_bytes(original) + b"\n")

        report = await engine.verify_chain()
        assert not report.chain_intact
        bad = report.steps[1]
        assert any("payload_digest mismatch" in e for e in bad.errors)

    @pytest.mark.asyncio
    async def test_tampered_receipt_detected(
        self, engine: InMemorySealEngine, workspace: Path
    ) -> None:
        await _build_three_seal_chain(engine, workspace)
        rp = engine.chain_dir / "000001_PRE_GENERATOR.receipt.json"
        receipt = json.loads(rp.read_text("utf-8"))
        receipt["parent_hash"] = "0" * 64
        rp.write_bytes(canonical_json_bytes(receipt) + b"\n")

        report = await engine.verify_chain()
        assert not report.chain_intact
        # Either content_hash mismatch or parent_hash break is reported.
        all_errors = [e for s in report.steps for e in s.errors]
        assert any(("content_hash mismatch" in e) or ("parent_hash break" in e) for e in all_errors)

    @pytest.mark.asyncio
    async def test_chain_break_detected(self, engine: InMemorySealEngine, workspace: Path) -> None:
        genesis, pre, _ = await _build_three_seal_chain(engine, workspace)
        pre.receipt_path.unlink()
        pre.payload_path.unlink()

        report = await engine.verify_chain()
        assert not report.chain_intact
        all_errors = [e for s in report.steps for e in s.errors]
        # Genesis is fine; the gap shows up as a parent-hash break at step 2.
        assert any("parent_hash break" in e for e in all_errors)
        assert report.steps[0].step_index == 0
        assert report.steps[1].step_index == 2  # post-generator filename position
        # Dropped step's hash isn't in chain anymore — but genesis hash must
        # still be present in the diagnostic stream for at least one step.
        assert any(genesis.content_hash[:10] in e for e in all_errors)


# ── Step-type mapping + Protocol conformance ───────────


class TestStepTypeMapping:
    def test_all_step_types_are_mapped(self) -> None:
        for step in StepType:
            node, seal = step_type_to_node_seal(step)
            assert isinstance(node, NodeName)
            assert isinstance(seal, SealType)


def test_compute_content_hash_uses_genesis_tag_for_none() -> None:
    payload = b'{"x":1}'
    expected = hashlib.sha256(GENESIS_PARENT_TAG.encode() + b"\n" + payload).hexdigest()
    assert compute_content_hash(None, payload) == expected


def test_compute_content_hash_rejects_bad_parent() -> None:
    with pytest.raises(SealError):
        compute_content_hash("notahash", b"x")


def test_in_memory_engine_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(
        InMemorySealEngine.create(tmp_path, run_id="r"),
        SealEngine,
    )
