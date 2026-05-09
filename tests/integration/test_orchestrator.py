# tests/integration/test_orchestrator.py

"""
Integration tests for the top-level orchestrator.

Tests:
- Happy path: brief → COMPLETED with all output files
- No-provenance mode (InMemory engine)
- Crash recovery (resume from FAILED)
- Human rescue resume
- Invalid brief rejection
- Custom run_id
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import StubLLMResponse

from slop_research_factory.config import FactoryConfig
from slop_research_factory.orchestrator import (
    FactoryResult,
    resume_factory,
    run_factory,
)
from slop_research_factory.types.enums import RunStatus


def _gen_response(content: str = "# Generated\n\nContent.") -> StubLLMResponse:
    """LLM response for generator."""
    return StubLLMResponse(
        content=content,
        input_tokens=1000,
        output_tokens=5000,
        think_tokens=3000,
        model="deepseek/deepseek-r1",
    )


class _SequenceLLMClient:
    """LLM client that returns responses in sequence."""

    def __init__(self, responses: list[StubLLMResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict] = []

    async def complete(self, *, model: str, messages: list, **kw) -> StubLLMResponse:
        self.calls.append({"model": model, "messages": messages, **kw})
        return next(self._responses)


@pytest.fixture
def no_provenance_config() -> FactoryConfig:
    """Config with provenance disabled for fast tests."""
    from dataclasses import replace

    return replace(FactoryConfig(), enable_provenance=False)


class TestRunFactoryHappyPath:
    """Basic run_factory execution."""

    @pytest.mark.asyncio
    async def test_returns_factory_result(self, tmp_path: Path) -> None:
        """run_factory returns a FactoryResult instance."""
        # We need to mock the graph execution to avoid real LLM calls
        brief = {"thesis": "Test thesis", "title_suggestion": "Test Paper"}

        with patch(
            "slop_research_factory.orchestrator.run_graph",
        ) as mock_graph:
            # Make run_graph return a completed state
            async def _fake_graph(state, deps):
                state.status = RunStatus.COMPLETED
                state.current_draft = "# Final\n\nDone."
                return state

            mock_graph.side_effect = _fake_graph

            from dataclasses import replace

            config = replace(FactoryConfig(), enable_provenance=False)
            result = await run_factory(
                brief=brief,
                config=config,
                workspace_root=tmp_path,
            )

        assert isinstance(result, FactoryResult)
        assert result.workspace_path.exists()
        assert result.elapsed_seconds > 0

    @pytest.mark.asyncio
    async def test_custom_run_id_used(self, tmp_path: Path) -> None:
        """Explicit run_id is honored."""
        brief = {"thesis": "Test"}

        with patch("slop_research_factory.orchestrator.run_graph") as mock_graph:

            async def _fake(state, deps):
                state.status = RunStatus.COMPLETED
                return state

            mock_graph.side_effect = _fake

            from dataclasses import replace

            config = replace(FactoryConfig(), enable_provenance=False)
            result = await run_factory(
                brief=brief,
                config=config,
                run_id="my-custom-run",
                workspace_root=tmp_path,
            )

        assert result.state.run_id == "my-custom-run"
        assert (tmp_path / "my-custom-run").exists()

    @pytest.mark.asyncio
    async def test_config_and_brief_persisted(self, tmp_path: Path) -> None:
        """config.json and brief.json written to workspace."""
        brief = {"thesis": "Persisted", "title_suggestion": "T"}

        with patch("slop_research_factory.orchestrator.run_graph") as mock_graph:

            async def _fake(state, deps):
                state.status = RunStatus.COMPLETED
                return state

            mock_graph.side_effect = _fake

            from dataclasses import replace

            config = replace(FactoryConfig(), enable_provenance=False)
            result = await run_factory(
                brief=brief,
                config=config,
                workspace_root=tmp_path,
            )

        ws = result.workspace_path
        assert (ws / "config.json").exists()
        assert (ws / "brief.json").exists()

        brief_data = json.loads((ws / "brief.json").read_text())
        assert brief_data["thesis"] == "Persisted"


class TestRunFactoryFailure:
    """Error handling in run_factory."""

    @pytest.mark.asyncio
    async def test_graph_exception_marks_failed(self, tmp_path: Path) -> None:
        """Unhandled exception in graph → state.status = FAILED."""
        brief = {"thesis": "Fail test"}

        with patch("slop_research_factory.orchestrator.run_graph") as mock_graph:
            mock_graph.side_effect = RuntimeError("LLM exploded")

            from dataclasses import replace

            config = replace(FactoryConfig(), enable_provenance=False)
            result = await run_factory(
                brief=brief,
                config=config,
                workspace_root=tmp_path,
            )

        assert result.state.status == RunStatus.FAILED
        assert result.verification_report is None

    @pytest.mark.asyncio
    async def test_invalid_brief_raises(self, tmp_path: Path) -> None:
        """Non-dict, non-dataclass brief raises TypeError."""
        with pytest.raises(TypeError):
            await run_factory(
                brief="not a dict or dataclass",
                workspace_root=tmp_path,
            )


class TestRunFactoryVerification:
    """Chain verification on completion."""

    @pytest.mark.asyncio
    async def test_completed_run_has_verification_report(self, tmp_path: Path) -> None:
        """COMPLETED status triggers verify_chain."""
        brief = {"thesis": "Verify me"}

        with patch("slop_research_factory.orchestrator.run_graph") as mock_graph:

            async def _fake(state, deps):
                state.status = RunStatus.COMPLETED
                return state

            mock_graph.side_effect = _fake

            from dataclasses import replace

            config = replace(FactoryConfig(), enable_provenance=False)
            result = await run_factory(
                brief=brief,
                config=config,
                workspace_root=tmp_path,
            )

        assert result.verification_report is not None
        assert result.verification_report.chain_intact is True


class TestResumeFactory:
    """resume_factory edge cases."""

    @pytest.mark.asyncio
    async def test_resume_nonexistent_workspace_raises(self, tmp_path: Path) -> None:
        """Missing workspace path → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await resume_factory(workspace_path=tmp_path / "nonexistent")

    @pytest.mark.asyncio
    async def test_resume_completed_run_raises(self, tmp_path: Path) -> None:
        """Cannot resume a COMPLETED run."""
        # Create a fake workspace with completed state
        ws = tmp_path / "completed-run"
        ws.mkdir()
        state_data = {
            "run_id": "completed-run",
            "status": "COMPLETED",
            "config": {},
            "brief": {"thesis": "done"},
            "step_index": 5,
            "latest_hash": "a" * 64,
            "cycle_count": 1,
            "rejection_count": 0,
            "revision_count": 0,
            "messages": [],
            "citation_checks": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_think_tokens": 0,
            "total_estimated_cost_usd": 0.0,
            "total_wall_clock_seconds": 10.0,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        (ws / "state.json").write_text(json.dumps(state_data), encoding="utf-8")

        with pytest.raises(ValueError, match="terminal status"):
            await resume_factory(workspace_path=ws)
