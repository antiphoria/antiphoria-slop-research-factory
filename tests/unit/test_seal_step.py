# tests/unit/test_seal_step.py

"""
Unit tests for :func:`seal_step` after M1.1.

The helper is now a thin glue: it normalises metadata, calls
:meth:`SealEngine.seal`, and copies ``step_index`` / ``latest_hash``
from the returned :class:`SealReceipt` into the caller's state.

Covers:

- Returns ``(state, SealReceipt)``; mutates state from the receipt.
- Successive calls chain correctly via the engine's internal state.
- Engine failures propagate as :class:`SealError` and leave state
  untouched.
- The persisted payload is canonical UTF-8 JSON (sorted keys, single
  trailing newline) and metadata normalisation lands on the wire
  (``model`` → ``model_id``, ``token_counts`` flattening).
- The receipt file's ``parent_hash`` matches the engine's genesis
  hash for the first non-genesis seal.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from slop_research_factory.seal.engine import (
    InMemorySealEngine,
    SealError,
    SealReceipt,
    canonical_json_bytes,
)
from slop_research_factory.seal.helpers import seal_step
from slop_research_factory.types.enums import StepType
from slop_research_factory.types.hashing import is_valid_sha256_hex

# ── Stub state ──────────────────────────────────────────


@dataclass
class _StubState:
    """Minimal duck-typed state: only the fields seal_step touches."""

    step_index: int = 0
    latest_hash: str = ""
    messages: list = field(default_factory=list)


# ── Valid metadata helpers ─────────────────────────────
#
# Strict metadata schema registry now enforces required
# keys for every StepType. Tests that don't otherwise care about the
# wire metadata pull a minimal valid dict from these helpers.

_FAKE_HASH = "0" * 64


def _pre_gen_meta(**overrides: Any) -> dict[str, Any]:
    base = {
        "prompt_hash": _FAKE_HASH,
        "model": "deepseek/deepseek-r1",
        "cycle": 1,
    }
    base.update(overrides)
    return base


def _post_gen_meta(**overrides: Any) -> dict[str, Any]:
    base = {
        "model": "deepseek/deepseek-r1",
        "token_counts": {"input": 1, "output": 1},
        "cycle": 1,
        "draft_hash": _FAKE_HASH,
        "raw_response_hash": _FAKE_HASH,
    }
    base.update(overrides)
    return base


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
async def engine(tmp_path: Path) -> InMemorySealEngine:
    """Engine with genesis already sealed — mirrors orchestrator wire-up."""
    eng = InMemorySealEngine.create(tmp_path, run_id="run-test")
    await eng.begin_chain(research_brief={"title": "test"})
    return eng


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _write_artefact(workspace: Path, rel: str, content: bytes) -> str:
    abs_path = workspace / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return rel


# ── Tests ───────────────────────────────────────────────


class TestSealStepBasics:
    @pytest.mark.asyncio
    async def test_returns_state_and_seal_receipt(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        state = _StubState()
        rel = _write_artefact(workspace, "drafts/cycle_01_generator_prompt.md", b"hi")
        new_state, receipt = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=[rel],
            metadata=_pre_gen_meta(),
        )
        assert new_state is state
        assert isinstance(receipt, SealReceipt)
        assert receipt.step_type is StepType.PRE_GENERATOR

    @pytest.mark.asyncio
    async def test_state_step_index_reflects_engine(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        state = _StubState(step_index=999)  # value is overwritten from receipt
        _write_artefact(workspace, "drafts/x.md", b"x")
        await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/x.md"],
            metadata=_pre_gen_meta(),
        )
        # Genesis = 0, first seal_step = 1.
        assert state.step_index == 1
        assert state.step_index == engine.latest_step

    @pytest.mark.asyncio
    async def test_latest_hash_replaced_with_content_hash(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        state = _StubState()
        _write_artefact(workspace, "drafts/x.md", b"x")
        _, receipt = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/x.md"],
            metadata=_pre_gen_meta(),
        )
        assert state.latest_hash == receipt.content_hash
        assert is_valid_sha256_hex(state.latest_hash)


class TestSealStepChaining:
    @pytest.mark.asyncio
    async def test_pre_then_post_link(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        state = _StubState()
        _write_artefact(workspace, "drafts/prompt.md", b"prompt")
        _, pre = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/prompt.md"],
            metadata=_pre_gen_meta(prompt_version="v0.1"),
        )
        _write_artefact(workspace, "drafts/output.md", b"output")
        _, post = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.POST_GENERATOR,
            content_file_paths=["drafts/output.md"],
            metadata=_post_gen_meta(),
        )
        assert post.parent_hash == pre.content_hash
        # Chain so far: genesis (0), pre (1), post (2).
        assert state.step_index == 2

    @pytest.mark.asyncio
    async def test_first_seal_chains_to_genesis(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        genesis_hash = engine.latest_hash
        assert genesis_hash is not None
        state = _StubState()
        _write_artefact(workspace, "drafts/p.md", b"p")
        _, receipt = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/p.md"],
            metadata=_pre_gen_meta(),
        )
        assert receipt.parent_hash == genesis_hash


class TestSealStepFailures:
    @pytest.mark.asyncio
    async def test_missing_content_file_raises(
        self,
        engine: InMemorySealEngine,
    ) -> None:
        state = _StubState(step_index=7, latest_hash="b" * 64)
        prior_step = state.step_index
        prior_hash = state.latest_hash
        with pytest.raises(SealError):
            await seal_step(
                seal_engine=engine,
                state=state,
                step_type=StepType.PRE_GENERATOR,
                content_file_paths=["drafts/missing.md"],
                metadata=_pre_gen_meta(),
            )
        assert state.step_index == prior_step
        assert state.latest_hash == prior_hash

    @pytest.mark.asyncio
    async def test_engine_seal_failure_propagates(
        self,
        tmp_path: Path,
        workspace: Path,
    ) -> None:
        class _Boom(InMemorySealEngine):
            async def seal(  # type: ignore[override]
                self,
                **kw: Any,
            ) -> SealReceipt:
                raise SealError("boom")

        engine = _Boom.create(tmp_path, run_id="r")
        await engine.begin_chain()
        state = _StubState()
        _write_artefact(workspace, "drafts/x.md", b"x")
        with pytest.raises(SealError, match="boom"):
            await seal_step(
                seal_engine=engine,
                state=state,
                step_type=StepType.PRE_GENERATOR,
                content_file_paths=["drafts/x.md"],
                metadata=_pre_gen_meta(),
            )
        # State unchanged.
        assert state.step_index == 0


class TestSealStepPayloadShape:
    @pytest.mark.asyncio
    async def test_payload_is_canonical_json(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        state = _StubState()
        _write_artefact(workspace, "drafts/output.md", b"hello world")
        _, receipt = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.POST_GENERATOR,
            content_file_paths=["drafts/output.md"],
            metadata=_post_gen_meta(
                token_counts={"input": 100, "output": 200, "think": 50},
            ),
        )
        text = receipt.payload_path.read_text("utf-8")
        assert text.endswith("\n")
        assert "\r" not in text
        parsed = json.loads(text)
        re_canon = canonical_json_bytes(parsed) + b"\n"
        assert text.encode("utf-8") == re_canon
        # Metadata normalisation visible on the wire.
        assert parsed["metadata"]["input_tokens"] == 100
        assert parsed["metadata"]["output_tokens"] == 200
        assert parsed["metadata"]["model_id"] == "deepseek/deepseek-r1"

    @pytest.mark.asyncio
    async def test_content_files_recorded_with_sha256(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        state = _StubState()
        bytes_a = b"file-a"
        bytes_b = b"file-b"
        _write_artefact(workspace, "drafts/a.md", bytes_a)
        _write_artefact(workspace, "drafts/b.md", bytes_b)
        _, receipt = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/b.md", "drafts/a.md"],
            metadata=_pre_gen_meta(),
        )
        payload = json.loads(receipt.payload_path.read_text("utf-8"))
        files = payload["content_files"]
        # Sorted by path for stable output.
        assert [f["path"] for f in files] == ["drafts/a.md", "drafts/b.md"]
        assert files[0]["sha256"] == hashlib.sha256(bytes_a).hexdigest()
        assert files[1]["sha256"] == hashlib.sha256(bytes_b).hexdigest()

    @pytest.mark.asyncio
    async def test_receipt_parent_hash_matches_genesis(
        self,
        engine: InMemorySealEngine,
        workspace: Path,
    ) -> None:
        genesis_hash = engine.latest_hash
        state = _StubState()
        _write_artefact(workspace, "drafts/x.md", b"x")
        _, receipt = await seal_step(
            seal_engine=engine,
            state=state,
            step_type=StepType.PRE_GENERATOR,
            content_file_paths=["drafts/x.md"],
            metadata=_pre_gen_meta(),
        )
        on_disk = json.loads(receipt.receipt_path.read_text("utf-8"))
        assert on_disk["parent_hash"] == genesis_hash
