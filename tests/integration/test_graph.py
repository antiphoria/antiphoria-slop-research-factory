# tests/integration/test_graph.py

"""Integration tests for the M2 LangGraph (BRIEF→GEN→VER→[ROUTE]…)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.engine.graph import GraphDependencies, run_graph
from slop_research_factory.engine.routing import (
    FINALIZE_NODE,
    HUMAN_RESCUE_NODE,
)
from slop_research_factory.llm.client import CannedLLMClient, LLMResponse
from slop_research_factory.seal.engine import InMemorySealEngine
from slop_research_factory.tools.canned import CannedCitationCheckClient
from slop_research_factory.types.enums import RunStatus, Verdict
from slop_research_factory.types.state import FactoryState
from slop_research_factory.types.verifier_output import VerifierOutput

# ── Helpers ────────────────────────────────────────────


def _gen_response(content: str = "# Draft\nBody.") -> LLMResponse:
    return LLMResponse(
        content=content,
        raw_response={
            "id": "resp-gen",
            "model": "deepseek/deepseek-r1",
            "choices": [{"message": {"content": content}}],
        },
        input_tokens=10,
        output_tokens=20,
        think_tokens=None,
        model="deepseek/deepseek-r1",
        api_response_id="resp-gen",
        api_provider="deepseek",
    )


def _verifier_output(
    *,
    verdict: Verdict,
    confidence: float = 0.95,
    critique_entries: list[dict] | None = None,
) -> VerifierOutput:
    return VerifierOutput(
        critique_summary="ok" if verdict is Verdict.CORRECT else "issues found",
        critique_entries=critique_entries
        or (
            []
            if verdict is Verdict.CORRECT
            else [
                {
                    "category": "logical_gap",
                    "severity": "major",
                    "description": "fix me",
                },
            ]
        ),
        verdict=verdict,
        resolution_type="explanation",
        verdict_confidence=confidence,
        resolution="No major flaws." if verdict is Verdict.CORRECT else "Patch §3.",
        confidence_logical_soundness=0.9,
        confidence_mathematical_rigor=0.9,
        confidence_citation_accuracy=0.9,
        confidence_scope_compliance=0.9,
        confidence_novelty_plausibility=0.4,
    )


def _structured_runner_sequence(parsed_outputs: list[VerifierOutput]):
    iterator: Iterator[VerifierOutput] = iter(parsed_outputs)

    async def _runner(*, model: str, messages: list, response_model, **kw):
        try:
            parsed = next(iterator)
        except StopIteration as exc:
            raise AssertionError(
                "structured runner exhausted — extend parsed_outputs sequence",
            ) from exc
        return parsed, LLMResponse(
            content="{}",
            raw_response={
                "id": "resp-ver",
                "model": model,
                "choices": [{"message": {"content": "{}"}}],
            },
            input_tokens=5,
            output_tokens=5,
            think_tokens=None,
            model=model,
            api_response_id="resp-ver",
            api_provider="google",
        )

    return _runner


def _initial_state(
    workspace_root: Path, *, max_revisions: int = 5, max_rejections: int = 3
) -> FactoryState:
    return FactoryState(
        run_id="test-run-0001",
        status=RunStatus.GENERATING,
        config=FactoryConfig(
            max_revisions=max_revisions,
            max_rejections=max_rejections,
        ),
        brief={"thesis": "Cats run the internet."},
        step_index=0,
        latest_hash="",
        cycle_count=0,
        rejection_count=0,
        revision_count=0,
        workspace=str(workspace_root),
    )


@pytest.fixture
async def engine(tmp_path: Path) -> InMemorySealEngine:
    eng = InMemorySealEngine.create(tmp_path, run_id="test-run-0001")
    await eng.begin_chain(research_brief={"thesis": "Cats run the internet."})
    return eng


def _deps(
    engine: InMemorySealEngine,
    workspace,
    llm_responses: list[LLMResponse],
    verifier_outputs: list[VerifierOutput],
) -> GraphDependencies:
    return GraphDependencies(
        seal_engine=engine,
        workspace=workspace,
        llm_client=CannedLLMClient(llm_responses),
        citation_check_client=CannedCitationCheckClient(),
        structured_complete=_structured_runner_sequence(verifier_outputs),
    )


# ── Tests ──────────────────────────────────────────────


class TestHappyCorrectPath:
    @pytest.mark.asyncio
    async def test_one_cycle_correct_finalises(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _initial_state(tmp_path)
        deps = _deps(
            engine,
            stub_workspace,
            llm_responses=[_gen_response()],
            verifier_outputs=[_verifier_output(verdict=Verdict.CORRECT)],
        )
        result = await run_graph(state, deps)
        assert result.status == RunStatus.COMPLETED
        report = await engine.verify_chain()
        assert report.chain_intact is True


class TestFixableCycle:
    @pytest.mark.asyncio
    async def test_fixable_then_correct_finalises(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _initial_state(tmp_path)
        deps = _deps(
            engine,
            stub_workspace,
            llm_responses=[
                _gen_response("# Initial draft"),
                _gen_response("# Repaired draft"),  # reviser uses same client
            ],
            verifier_outputs=[
                _verifier_output(
                    verdict=Verdict.FIXABLE,
                    confidence=0.85,
                ),
                _verifier_output(verdict=Verdict.CORRECT),
            ],
        )
        result = await run_graph(state, deps)
        assert result.status == RunStatus.COMPLETED
        assert result.cycle_count == 2
        # Revision counter incremented exactly once.
        assert result.revision_count == 1
        assert result.current_critique is not None
        assert result.current_critique["effective_verdict"] == "CORRECT"


class TestCapsEscalation:
    @pytest.mark.asyncio
    async def test_max_revisions_routes_to_rescue(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        # max_revisions=1 → first FIXABLE consumes the budget, second
        # FIXABLE escalates.
        state = _initial_state(tmp_path, max_revisions=1)
        deps = _deps(
            engine,
            stub_workspace,
            llm_responses=[
                _gen_response("# initial"),
                _gen_response("# revised"),
            ],
            verifier_outputs=[
                _verifier_output(verdict=Verdict.FIXABLE, confidence=0.9),
                _verifier_output(verdict=Verdict.FIXABLE, confidence=0.9),
            ],
        )
        result = await run_graph(state, deps)
        assert result.status == RunStatus.AWAITING_HUMAN
        assert result.revision_count == 1


class TestRoutingNodeIds:
    """Sanity check that the graph builder returns the constants we expect."""

    def test_constants_exist(self) -> None:
        assert FINALIZE_NODE == "finalize_manifest"
        assert HUMAN_RESCUE_NODE == "human_rescue_queue"
