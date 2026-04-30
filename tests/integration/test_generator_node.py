# tests/integration/test_generator_node.py

"""
E2 integration tests for the Generator node (Step 6).

After M1.1 these tests run against the **real** seal layer
(:class:`~slop_research_factory.seal.engine.InMemorySealEngine` +
:func:`~slop_research_factory.seal.helpers.seal_step`); only the LLM
side stays mocked via :class:`StubLLMClient`. The engine fixture has
``begin_chain`` already called, so the chain on disk looks:

  ``000000_GENESIS.* → 000001_PRE_GENERATOR.* → 000002_POST_GENERATOR.*``

Covers: E2-NE01 … E2-NE07, E2-NE14 (D-8 §4.4) plus a chain-integrity
smoke test asserting the resulting workspace verifies via
:meth:`SealEngine.verify_chain`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_research_factory.nodes.generator_node import generator_node
from slop_research_factory.seal.engine import InMemorySealEngine
from slop_research_factory.types.enums import RunStatus
from tests.conftest import StubLLMClient, StubLLMResponse, StubState, StubWorkspace

# ──────────────────────────────────────────────────────────────────────────
# Fixtures local to this module (shadow tmp_path-anchored shared ones)
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def ws(tmp_path: Path) -> StubWorkspace:
    return StubWorkspace(tmp_path)


@pytest.fixture
def state(tmp_path: Path) -> StubState:
    s = StubState()
    s.workspace = str(tmp_path)
    return s


@pytest.fixture
async def engine(tmp_path: Path, state: StubState) -> InMemorySealEngine:
    """Engine with genesis sealed — mirrors orchestrator wire-up."""
    eng = InMemorySealEngine.create(tmp_path, run_id=state.run_id)
    await eng.begin_chain(research_brief=state.brief)
    return eng


# ──────────────────────────────────────────────────────────────────────────
# Happy-path tests
# ──────────────────────────────────────────────────────────────────────────


class TestGeneratorNodeHappyPath:
    """Normal generation with think tokens and successful seal."""

    @pytest.mark.asyncio
    async def test_produces_draft(self, state, ws, engine) -> None:
        result = await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert result.current_draft is not None
        assert len(result.current_draft) > 0

    @pytest.mark.asyncio
    async def test_step_index_increments_twice(self, state, ws, engine) -> None:
        """E2-NE03: Generator produces exactly 2 seal events on top of genesis."""
        result = await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        # Genesis(0) + PRE(1) + POST(2) → engine.latest_step == 2.
        assert result.step_index == 2
        assert engine.latest_step == 2

    @pytest.mark.asyncio
    async def test_pre_seal_before_llm_call(self, state, ws, engine) -> None:
        """E2-NE01: PRE-SEAL completes before mock LLM call."""
        client = StubLLMClient()
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=client,
            workspace=ws,
        )
        # The pre-seal receipt exists on disk before the post-seal one
        # (file ordering by step_index reflects creation order).
        pre = ws.root / "chain" / "000001_PRE_GENERATOR.receipt.json"
        post = ws.root / "chain" / "000002_POST_GENERATOR.receipt.json"
        assert pre.is_file()
        assert post.is_file()
        assert pre.stat().st_mtime <= post.stat().st_mtime
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_raw_response_written_before_parse(self, state, ws, engine) -> None:
        """E2-NE06: raw API response file exists on disk."""
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        response_file = ws.root / "drafts" / "cycle_01_generator_response.json"
        assert response_file.exists()
        raw = json.loads(response_file.read_bytes())
        assert "id" in raw  # from StubLLMResponse.raw_response

    @pytest.mark.asyncio
    async def test_output_file_written(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        output_file = ws.root / "drafts" / "cycle_01_generator_output.md"
        assert output_file.exists()
        assert len(output_file.read_text()) > 0

    @pytest.mark.asyncio
    async def test_think_trace_captured(self, state, ws, engine) -> None:
        """E2-NE04: think tokens written when capture_think_tokens=true."""
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        think_file = ws.root / "drafts" / "cycle_01_generator_think.md"
        assert think_file.exists()
        result = think_file.read_text()
        assert "reasoning" in result

    @pytest.mark.asyncio
    async def test_inference_record_written(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        record_file = ws.root / "drafts" / "cycle_01_generator_record.json"
        assert record_file.exists()
        record = json.loads(record_file.read_text())
        assert record["_schema_version"] == "0.1"
        assert record["role"] == "generator"
        assert record["input_tokens"] == 1100
        assert record["output_tokens"] == 7000

    @pytest.mark.asyncio
    async def test_message_appended(self, state, ws, engine) -> None:
        result = await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert len(result.messages) == 1
        msg = result.messages[0]
        assert msg["role"] == "generator"
        assert msg["token_counts"]["input"] == 1100

    @pytest.mark.asyncio
    async def test_token_totals_updated(self, state, ws, engine) -> None:
        result = await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert result.total_input_tokens == 1100
        assert result.total_output_tokens == 7000
        assert result.total_think_tokens == 12400

    @pytest.mark.asyncio
    async def test_state_json_written(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert (ws.root / "state.json").exists()

    @pytest.mark.asyncio
    async def test_prompt_file_written(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        prompt_file = ws.root / "drafts" / "cycle_01_generator_prompt.md"
        assert prompt_file.exists()
        text = prompt_file.read_text()
        assert "## System Prompt" in text
        assert "## User Message" in text
        assert "Test thesis" in text


class TestGeneratorNoThinkCapture:
    """E2-NE05: think tokens NOT captured when disabled."""

    @pytest.mark.asyncio
    async def test_no_think_file(self, state, ws, engine) -> None:
        state.config.capture_think_tokens = False
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        think_file = ws.root / "drafts" / "cycle_01_generator_think.md"
        assert not think_file.exists()


class TestGeneratorNoOutput:
    """E2-NE14: NO_OUTPUT path seals the declaration, not empty."""

    @pytest.mark.asyncio
    async def test_no_output_sets_status(self, state, ws, engine) -> None:
        resp = StubLLMResponse(
            content="NO_OUTPUT: Cannot address — requires empirical data.",
        )
        result = await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(resp),
            workspace=ws,
        )
        assert result.status == RunStatus.NO_OUTPUT

    @pytest.mark.asyncio
    async def test_no_output_draft_preserved(self, state, ws, engine) -> None:
        """The NO_OUTPUT text is set as current_draft (sealed, not empty)."""
        resp = StubLLMResponse(content="NO_OUTPUT: Impossible brief.")
        result = await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(resp),
            workspace=ws,
        )
        assert "NO_OUTPUT" in result.current_draft

    @pytest.mark.asyncio
    async def test_no_output_file_not_empty(self, state, ws, engine) -> None:
        resp = StubLLMResponse(content="NO_OUTPUT: Reason.")
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(resp),
            workspace=ws,
        )
        output_file = ws.root / "drafts" / "cycle_01_generator_output.md"
        assert output_file.exists()
        assert len(output_file.read_text()) > 0


class TestGeneratorRawResponseHash:
    """E2-NE07: raw_response file hash is captured in the chain payload."""

    @pytest.mark.asyncio
    async def test_response_file_hashed_in_post_payload(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        post_payload = json.loads(
            (ws.root / "chain" / "000002_POST_GENERATOR.payload.json").read_text("utf-8")
        )
        paths = [f["path"] for f in post_payload["content_files"]]
        assert any("generator_response.json" in p for p in paths), paths


class TestGeneratorChainIntegrity:
    """M1 acceptance gate: produced workspace must verify cleanly."""

    @pytest.mark.asyncio
    async def test_chain_verifies_after_generator(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        report = await engine.verify_chain()
        assert report.chain_intact, report.summary()
        assert report.total_steps == 3  # genesis + pre + post

    @pytest.mark.asyncio
    async def test_post_seal_chains_to_pre_seal(self, state, ws, engine) -> None:
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        genesis = json.loads((ws.root / "chain" / "000000_GENESIS.receipt.json").read_text("utf-8"))
        pre = json.loads(
            (ws.root / "chain" / "000001_PRE_GENERATOR.receipt.json").read_text("utf-8")
        )
        post = json.loads(
            (ws.root / "chain" / "000002_POST_GENERATOR.receipt.json").read_text("utf-8")
        )
        assert genesis["parent_hash"] is None
        assert pre["parent_hash"] == genesis["content_hash"]
        assert post["parent_hash"] == pre["content_hash"]
        assert state.latest_hash == post["content_hash"]
