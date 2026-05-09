# tests/integration/test_human_rescue_node.py

"""
Integration tests for the human rescue node.

Tests:
- Request JSON persisted to rescue/request.json
- Draft snapshot saved to rescue/draft_at_rescue.md
- Critique snapshot saved to rescue/critique_at_rescue.json
- HUMAN_GATE seal covers all rescue files
- State transitions to AWAITING_HUMAN
- Rescue reason correctly extracted from various scenarios
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_research_factory.nodes.human_rescue_node import (
    _extract_rescue_reason,
    human_rescue_node,
)
from slop_research_factory.types.enums import RescueReason, RunStatus, StepType
from tests.conftest import StubConfig, StubState, StubWorkspace


@pytest.fixture
def rescue_state(tmp_path: Path) -> StubState:
    """State triggering human rescue (max rejections exceeded)."""
    state = StubState()
    state.workspace = str(tmp_path)
    state.current_draft = "# Draft at rescue point\n\nIncomplete content."
    state.current_critique = {
        "verdict": "WRONG",
        "effective_verdict": "WRONG",
        "verdict_confidence": 0.85,
        "summary": "Fundamental logical errors.",
        "issues": ["Incorrect premise", "Missing citations"],
        "rescue_reason": RescueReason.MAX_REJECTIONS_EXCEEDED.value,
    }
    state.config = StubConfig(max_rejections=3)
    state.cycle_count = 4
    state.rejection_count = 3
    state.revision_count = 1
    state.total_input_tokens = 8000
    state.total_output_tokens = 20000
    state.step_index = 10
    state.latest_hash = "d" * 64
    return state


class TestRescueReasonExtraction:
    """_extract_rescue_reason logic."""

    def test_explicit_reason_from_critique(self) -> None:
        """Uses rescue_reason from critique when present."""
        state = StubState()
        state.current_critique = {
            "rescue_reason": RescueReason.MAX_REVISIONS_EXCEEDED.value,
        }
        state.config = StubConfig(max_rejections=99, max_revisions=99)
        result = _extract_rescue_reason(state)
        assert result == RescueReason.MAX_REVISIONS_EXCEEDED

    def test_infers_max_rejections(self) -> None:
        """Infers MAX_REJECTIONS when critique lacks explicit reason."""
        state = StubState()
        state.current_critique = {}
        state.config = StubConfig(max_rejections=3)
        state.rejection_count = 3
        result = _extract_rescue_reason(state)
        assert result == RescueReason.MAX_REJECTIONS_EXCEEDED

    def test_infers_max_revisions(self) -> None:
        """Infers MAX_REVISIONS when revision cap hit."""
        state = StubState()
        state.current_critique = {}
        state.config = StubConfig(max_rejections=99, max_revisions=5)
        state.rejection_count = 0
        state.revision_count = 5
        result = _extract_rescue_reason(state)
        assert result == RescueReason.MAX_REVISIONS_EXCEEDED

    def test_infers_cycle_cap(self) -> None:
        """Infers MAX_TOTAL_CYCLES when all specific caps are fine."""
        state = StubState()
        state.current_critique = {}
        state.config = StubConfig(
            max_rejections=99,
            max_revisions=99,
            max_total_cycles=10,
        )
        state.rejection_count = 0
        state.revision_count = 0
        state.cycle_count = 10
        result = _extract_rescue_reason(state)
        assert result == RescueReason.MAX_TOTAL_CYCLES_EXCEEDED


class TestHumanRescueNodeIntegration:
    """Full rescue node execution."""

    @pytest.mark.asyncio
    async def test_request_json_persisted(
        self,
        rescue_state: StubState,
        stub_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """rescue/request.json is written with expected structure."""
        await human_rescue_node(
            rescue_state,
            seal_engine=genesis_seal_engine,
            workspace=stub_workspace,
        )
        request_path = stub_workspace.root / "rescue" / "request.json"
        assert request_path.exists()
        data = json.loads(request_path.read_text(encoding="utf-8"))
        assert data["run_id"] == rescue_state.run_id
        assert data["rescue_reason"] == RescueReason.MAX_REJECTIONS_EXCEEDED.value

    @pytest.mark.asyncio
    async def test_draft_snapshot_saved(
        self,
        rescue_state: StubState,
        stub_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """Draft is preserved in rescue/draft_at_rescue.md."""
        await human_rescue_node(
            rescue_state,
            seal_engine=genesis_seal_engine,
            workspace=stub_workspace,
        )
        draft_path = stub_workspace.root / "rescue" / "draft_at_rescue.md"
        assert draft_path.exists()
        assert "Draft at rescue point" in draft_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_critique_snapshot_saved(
        self,
        rescue_state: StubState,
        stub_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """Critique is preserved in rescue/critique_at_rescue.json."""
        await human_rescue_node(
            rescue_state,
            seal_engine=genesis_seal_engine,
            workspace=stub_workspace,
        )
        critique_path = stub_workspace.root / "rescue" / "critique_at_rescue.json"
        assert critique_path.exists()
        data = json.loads(critique_path.read_text(encoding="utf-8"))
        assert data["verdict"] == "WRONG"

    @pytest.mark.asyncio
    async def test_state_transitions_to_awaiting_human(
        self,
        rescue_state: StubState,
        stub_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """State status becomes AWAITING_HUMAN."""
        result = await human_rescue_node(
            rescue_state,
            seal_engine=genesis_seal_engine,
            workspace=stub_workspace,
        )
        assert result.status == RunStatus.AWAITING_HUMAN

    @pytest.mark.asyncio
    async def test_human_gate_sealed(
        self,
        rescue_state: StubState,
        stub_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """HUMAN_GATE step appears in chain."""
        await human_rescue_node(
            rescue_state,
            seal_engine=genesis_seal_engine,
            workspace=stub_workspace,
        )
        report = await genesis_seal_engine.verify_chain()
        assert report.chain_intact
        gate_steps = [s for s in report.steps if s.step_type == StepType.HUMAN_GATE.value]
        assert len(gate_steps) == 1

    @pytest.mark.asyncio
    async def test_no_draft_still_succeeds(
        self,
        rescue_state: StubState,
        stub_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """Rescue works even without a current_draft."""
        rescue_state.current_draft = None
        result = await human_rescue_node(
            rescue_state,
            seal_engine=genesis_seal_engine,
            workspace=stub_workspace,
        )
        assert result.status == RunStatus.AWAITING_HUMAN
        draft_path = stub_workspace.root / "rescue" / "draft_at_rescue.md"
        assert not draft_path.exists()
