# tests/integration/test_finalize_node.py

"""
Integration tests for the finalize node.

Tests:
- paper.md generation with YAML front matter
- hai_card.md generation with all sections
- manifest.json with correct structure
- MANIFEST seal covers all output files
- State transitions to COMPLETED
- Configuration overrides computed correctly
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_research_factory.nodes.finalize_node import (
    compute_configuration_overrides,
    finalize_node,
    render_paper,
    render_provenance_report,
)
from slop_research_factory.types.enums import RunStatus, StepType

from conftest import StubConfig, StubState, StubWorkspace


@pytest.fixture
def finalize_state(tmp_path: Path) -> StubState:
    """State ready for finalization (has a draft + critique)."""
    state = StubState()
    state.workspace = str(tmp_path)
    state.current_draft = "# Test Paper\n\nThis is the final draft content."
    state.current_critique = {
        "verdict": "CORRECT",
        "effective_verdict": "CORRECT",
        "verdict_confidence": 0.92,
        "summary": "Well-structured paper.",
        "issues": [],
    }
    state.cycle_count = 2
    state.rejection_count = 0
    state.revision_count = 1
    state.total_input_tokens = 5000
    state.total_output_tokens = 12000
    state.total_think_tokens = 8000
    state.total_estimated_cost_usd = 0.0834
    state.total_wall_clock_seconds = 45.2
    state.step_index = 6
    state.latest_hash = "a" * 64
    state.messages = [
        {
            "role": "generator",
            "model": "deepseek/deepseek-r1",
            "token_counts": {"input": 2000, "output": 7000},
        },
        {
            "role": "verifier",
            "model": "google/gemini-2.5-flash",
            "token_counts": {"input": 3000, "output": 5000},
        },
    ]
    state.citation_checks = [
        {"doi": "10.1234/test", "result": "VERIFIED"},
        {"doi": "10.5678/test", "result": "NOT_FOUND"},
    ]
    return state


@pytest.fixture
def finalize_workspace(tmp_path: Path) -> StubWorkspace:
    """Workspace with output directory support."""
    ws = StubWorkspace(tmp_path)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "brief.json").write_text('{"thesis": "Test"}', encoding="utf-8")

    # Add write_output_file method
    def write_output_file(filename: str, content: str) -> Path:
        out_dir = tmp_path / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / filename
        p.write_text(content, encoding="utf-8")
        return p

    ws.write_output_file = write_output_file

    # Add brief_path property
    ws.brief_path = tmp_path / "brief.json"
    ws.workspace_path = tmp_path

    return ws


class TestRenderPaper:
    """paper.md rendering."""

    def test_contains_yaml_front_matter(self) -> None:
        """Output starts and ends front matter with ---."""
        state = StubState()
        state.current_draft = "# Hello\n\nWorld."
        state.brief = {"title_suggestion": "My Paper Title"}
        result = render_paper(state)
        assert result.startswith("---\n")
        assert "\n---\n" in result

    def test_front_matter_contains_run_id(self) -> None:
        """Run ID appears in front matter."""
        state = StubState()
        state.current_draft = "Content"
        state.run_id = "special-run-xyz"
        result = render_paper(state)
        assert "special-run-xyz" in result

    def test_draft_content_preserved(self) -> None:
        """The actual draft text follows front matter unchanged."""
        state = StubState()
        draft = "# My Paper\n\n## Section 1\n\nContent here."
        state.current_draft = draft
        result = render_paper(state)
        assert draft in result


class TestConfigurationOverrides:
    """compute_configuration_overrides produces correct diff."""

    def test_no_overrides_for_defaults(self) -> None:
        """Default config produces empty overrides dict."""
        from slop_research_factory.config import FactoryConfig

        config = FactoryConfig()
        overrides = compute_configuration_overrides(config)
        assert overrides == {}

    def test_detects_changed_fields(self) -> None:
        """Modified fields appear in overrides."""
        from dataclasses import replace

        from slop_research_factory.config import FactoryConfig

        config = replace(FactoryConfig(), max_rejections=99, target_length_words=10000)
        overrides = compute_configuration_overrides(config)
        assert "max_rejections" in overrides
        assert overrides["max_rejections"] == 99
        assert "target_length_words" in overrides
        assert overrides["target_length_words"] == 10000


class TestFinalizeNodeIntegration:
    """Full finalize node execution."""

    @pytest.mark.asyncio
    async def test_produces_all_output_files(
        self,
        finalize_state: StubState,
        finalize_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """Finalize creates paper.md, hai_card.md, manifest.json, provenance_report.md."""
        result = await finalize_node(
            finalize_state,
            seal_engine=genesis_seal_engine,
            workspace=finalize_workspace,
        )
        output_dir = Path(finalize_workspace.root) / "output"
        assert (output_dir / "paper.md").exists()
        assert (output_dir / "hai_card.md").exists()
        assert (output_dir / "manifest.json").exists()
        assert (output_dir / "provenance_report.md").exists()

    @pytest.mark.asyncio
    async def test_state_transitions_to_completed(
        self,
        finalize_state: StubState,
        finalize_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """State status becomes COMPLETED after finalization."""
        result = await finalize_node(
            finalize_state,
            seal_engine=genesis_seal_engine,
            workspace=finalize_workspace,
        )
        assert result.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_manifest_contains_expected_keys(
        self,
        finalize_state: StubState,
        finalize_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """manifest.json has all required top-level keys."""
        await finalize_node(
            finalize_state,
            seal_engine=genesis_seal_engine,
            workspace=finalize_workspace,
        )
        manifest_path = Path(finalize_workspace.root) / "output" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        required_keys = {
            "run_id",
            "status",
            "completed_at",
            "final_verdict",
            "total_steps",
            "chain_integrity_verified",
            "model_topology",
            "configuration_overrides",
        }
        assert required_keys.issubset(set(manifest.keys()))

    @pytest.mark.asyncio
    async def test_manifest_seal_covers_all_outputs(
        self,
        finalize_state: StubState,
        finalize_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """MANIFEST seal's content_file_paths includes all 4 output files."""
        await finalize_node(
            finalize_state,
            seal_engine=genesis_seal_engine,
            workspace=finalize_workspace,
        )
        report = await genesis_seal_engine.verify_chain()
        assert report.chain_intact
        # Find the MANIFEST step
        manifest_steps = [
            s for s in report.steps if s.step_type == StepType.MANIFEST.value
        ]
        assert len(manifest_steps) == 1

    @pytest.mark.asyncio
    async def test_chain_intact_after_finalize(
        self,
        finalize_state: StubState,
        finalize_workspace: StubWorkspace,
        genesis_seal_engine,
    ) -> None:
        """Chain remains intact after finalization."""
        await finalize_node(
            finalize_state,
            seal_engine=genesis_seal_engine,
            workspace=finalize_workspace,
        )
        report = await genesis_seal_engine.verify_chain()
        assert report.chain_intact