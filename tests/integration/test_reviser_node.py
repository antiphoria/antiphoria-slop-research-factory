# tests/integration/test_reviser_node.py

"""Integration tests for :func:`reviser_node` (D-3 §5 / D-5 §5.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.llm.client import CannedLLMClient, LLMResponse
from slop_research_factory.nodes.reviser_node import reviser_node
from slop_research_factory.seal.engine import InMemorySealEngine
from slop_research_factory.types.enums import RunStatus
from slop_research_factory.types.state import FactoryState


def _llm_response(content: str = "# Revised draft\nBetter now.") -> LLMResponse:
    return LLMResponse(
        content=content,
        raw_response={
            "id": "resp-rev",
            "model": "deepseek/deepseek-r1",
            "choices": [{"message": {"content": content}}],
        },
        input_tokens=10,
        output_tokens=20,
        think_tokens=None,
        model="deepseek/deepseek-r1",
        api_response_id="resp-rev",
        api_provider="deepseek",
    )


def _critique(verdict: str = "FIXABLE") -> dict:
    return {
        "verdict": verdict,
        "effective_verdict": verdict,
        "critique_summary": "Sloppy logic in §3.",
        "critique_entries": [
            {
                "category": "logical_gap",
                "severity": "major",
                "description": "Step 5 doesn't follow.",
                "suggested_fix": "Insert lemma.",
            },
        ],
        "resolution": "Add the missing lemma in §3.",
        "resolution_type": "remediation_plan",
        "verdict_confidence": 0.85,
        "critique_hash": "deadbeef" * 8,
    }


def _state(workspace_root: Path, *, draft: str, critique: dict, cycle: int = 1) -> FactoryState:
    state = FactoryState(
        run_id="test-run-0001",
        status=RunStatus.REVISING,
        config=FactoryConfig(),
        brief={"thesis": "Cats run the internet."},
        step_index=0,
        latest_hash="",
        cycle_count=cycle,
        rejection_count=0,
        revision_count=0,
        current_draft=draft,
        current_critique=critique,
        workspace=str(workspace_root),
    )
    return state


@pytest.fixture
async def engine(tmp_path: Path) -> InMemorySealEngine:
    eng = InMemorySealEngine.create(tmp_path, run_id="test-run-0001")
    await eng.begin_chain(research_brief={"thesis": "Cats run the internet."})
    return eng


class TestTargetedRepair:
    @pytest.mark.asyncio
    async def test_seals_and_updates_draft(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(tmp_path, draft="Old draft.", critique=_critique("FIXABLE"))
        client = CannedLLMClient([_llm_response("# Repaired\nFixed.")])
        result = await reviser_node(
            state,
            seal_engine=engine,
            llm_client=client,
            workspace=stub_workspace,
            mode="targeted_repair",
        )
        assert result.current_draft is not None
        assert "Repaired" in result.current_draft
        # Genesis (0) + PRE (1) + POST (2).
        assert engine.latest_step == 2
        report = await engine.verify_chain()
        assert report.chain_intact is True

    @pytest.mark.asyncio
    async def test_critique_hash_propagates_to_pre_seal(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(tmp_path, draft="Old.", critique=_critique("FIXABLE"))
        client = CannedLLMClient([_llm_response()])
        await reviser_node(
            state,
            seal_engine=engine,
            llm_client=client,
            workspace=stub_workspace,
            mode="targeted_repair",
        )
        chain_files = sorted(engine.chain_dir.glob("*PRE_REVISER.payload.json"))
        assert chain_files
        payload = json.loads(chain_files[-1].read_text(encoding="utf-8"))
        assert payload["metadata"]["critique_hash"] == "deadbeef" * 8
        assert payload["metadata"]["mode"] == "targeted_repair"

    @pytest.mark.asyncio
    async def test_cycle_count_advances(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(
            tmp_path,
            draft="Old.",
            critique=_critique("FIXABLE"),
            cycle=1,
        )
        client = CannedLLMClient([_llm_response()])
        result = await reviser_node(
            state,
            seal_engine=engine,
            llm_client=client,
            workspace=stub_workspace,
            mode="targeted_repair",
        )
        assert result.cycle_count == 2


class TestFullRewrite:
    @pytest.mark.asyncio
    async def test_seals_and_updates_draft(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(tmp_path, draft="Bad draft.", critique=_critique("WRONG"))
        client = CannedLLMClient([_llm_response("# Brand New\nFresh start.")])
        result = await reviser_node(
            state,
            seal_engine=engine,
            llm_client=client,
            workspace=stub_workspace,
            mode="full_rewrite",
        )
        assert result.current_draft is not None
        assert "Brand New" in result.current_draft
        report = await engine.verify_chain()
        assert report.chain_intact is True

    @pytest.mark.asyncio
    async def test_no_output_sets_status(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(tmp_path, draft="Bad.", critique=_critique("WRONG"))
        client = CannedLLMClient(
            [_llm_response("NO_OUTPUT: I cannot produce a valid revision.")],
        )
        result = await reviser_node(
            state,
            seal_engine=engine,
            llm_client=client,
            workspace=stub_workspace,
            mode="full_rewrite",
        )
        assert result.status == RunStatus.NO_OUTPUT


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_missing_draft_raises(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(tmp_path, draft="x", critique=_critique("FIXABLE"))
        state.current_draft = None
        with pytest.raises(ValueError, match="current_draft"):
            await reviser_node(
                state,
                seal_engine=engine,
                llm_client=CannedLLMClient([_llm_response()]),
                workspace=stub_workspace,
                mode="targeted_repair",
            )

    @pytest.mark.asyncio
    async def test_unknown_mode_raises(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _state(tmp_path, draft="Old.", critique=_critique("FIXABLE"))
        with pytest.raises(ValueError, match="unknown reviser mode"):
            await reviser_node(
                state,
                seal_engine=engine,
                llm_client=CannedLLMClient([_llm_response()]),
                workspace=stub_workspace,
                mode="unknown",  # type: ignore[arg-type]
            )
