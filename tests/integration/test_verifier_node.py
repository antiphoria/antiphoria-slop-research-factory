# tests/integration/test_verifier_node.py

"""Integration tests for :func:`verifier_node`.

End-to-end with the real seal engine + canned tool client + canned
structured-output runner. The chain is verified at the end of every
test so any seal regression surfaces immediately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.llm.client import LLMResponse
from slop_research_factory.nodes.verifier_node import verifier_node
from slop_research_factory.seal.engine import InMemorySealEngine
from slop_research_factory.tools.canned import (
    CannedCitationCheckClient,
    CannedScript,
)
from slop_research_factory.types.enums import RunStatus, StepType, Verdict
from slop_research_factory.types.state import FactoryState
from slop_research_factory.types.tool_types import (
    CrossrefResult,
    SemanticScholarResult,
)
from slop_research_factory.types.verifier_output import VerifierOutput

# ── Helpers ────────────────────────────────────────────


def _empty_llm_response(model: str = "google/gemini-2.5-flash") -> LLMResponse:
    return LLMResponse(
        content="{}",
        raw_response={
            "id": "resp-001",
            "model": model,
            "choices": [{"message": {"content": "{}"}}],
        },
        input_tokens=42,
        output_tokens=99,
        think_tokens=0,
        model=model,
        api_response_id="resp-001",
        api_provider="google",
    )


def _make_verifier_output(
    *,
    verdict: Verdict = Verdict.CORRECT,
    verdict_confidence: float = 0.95,
    critique_entries: list[dict] | None = None,
) -> VerifierOutput:
    return VerifierOutput(
        critique_summary="A summary.",
        critique_entries=critique_entries or [],
        verdict=verdict,
        resolution_type="explanation",
        verdict_confidence=verdict_confidence,
        resolution="No major flaws.",
        confidence_logical_soundness=0.9,
        confidence_mathematical_rigor=0.85,
        confidence_citation_accuracy=0.9,
        confidence_scope_compliance=0.95,
        confidence_novelty_plausibility=0.4,
    )


def _structured_runner(parsed: VerifierOutput, response: LLMResponse | None = None):
    captured: dict = {}

    async def _runner(*, model: str, messages: list, response_model, **kw):
        captured["model"] = model
        captured["messages"] = messages
        captured["response_model"] = response_model
        return parsed, (response or _empty_llm_response(model))

    _runner.captured = captured  # type: ignore[attr-defined]
    return _runner


def _factory_state(workspace_root: Path, *, draft: str) -> FactoryState:
    return FactoryState(
        run_id="test-run-0001",
        status=RunStatus.VERIFYING,
        config=FactoryConfig(),
        brief={"thesis": "Cats run the internet."},
        step_index=0,
        latest_hash="",
        cycle_count=1,
        rejection_count=0,
        revision_count=0,
        current_draft=draft,
        workspace=str(workspace_root),
    )


# ── Fixtures ───────────────────────────────────────────


@pytest.fixture
async def engine(tmp_path: Path) -> InMemorySealEngine:
    eng = InMemorySealEngine.create(tmp_path, run_id="test-run-0001")
    await eng.begin_chain(research_brief={"thesis": "Cats run the internet."})
    return eng


# ── Tests ───────────────────────────────────────────────


class TestHappyPathCorrect:
    @pytest.mark.asyncio
    async def test_correct_verdict_seals_pre_and_post(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _factory_state(
            tmp_path,
            draft="A short draft with 10.1234/cats.123 cited inline.",
        )
        client = CannedCitationCheckClient(
            script=CannedScript.from_mapping(
                {
                    "crossref": {
                        "10.1234/cats.123": CrossrefResult(
                            found=True,
                            doi="10.1234/cats.123",
                            title="Cats",
                            authors=["A"],
                            year=2024,
                        ),
                    },
                    "semantic_scholar": {
                        "DOI:10.1234/cats.123": SemanticScholarResult(
                            found=True,
                            paper_id="DOI:10.1234/cats.123",
                            title="Cats",
                        ),
                    },
                },
            ),
        )
        runner = _structured_runner(_make_verifier_output(verdict=Verdict.CORRECT))

        result = await verifier_node(
            state,
            seal_engine=engine,
            workspace=stub_workspace,
            citation_check_client=client,
            structured_complete=runner,
        )

        assert result.current_critique is not None
        assert result.current_critique["verdict"] == "CORRECT"
        assert result.current_critique["effective_verdict"] == "CORRECT"
        # Genesis (0) + 2 tool calls + PRE + POST.
        assert engine.latest_step == 4
        # Chain verifies end-to-end.
        report = await engine.verify_chain()
        assert report.chain_intact is True
        assert report.total_steps == 5

    @pytest.mark.asyncio
    async def test_demotion_rule_triggers_when_confidence_below_threshold(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _factory_state(tmp_path, draft="No citations here.")
        runner = _structured_runner(
            _make_verifier_output(
                verdict=Verdict.CORRECT,
                verdict_confidence=0.5,  # below default 0.8 threshold
            ),
        )
        result = await verifier_node(
            state,
            seal_engine=engine,
            workspace=stub_workspace,
            citation_check_client=CannedCitationCheckClient(),
            structured_complete=runner,
        )
        assert result.current_critique is not None
        assert result.current_critique["verdict"] == "CORRECT"
        assert result.current_critique["effective_verdict"] == "FIXABLE"


class TestFixableVerdict:
    @pytest.mark.asyncio
    async def test_fixable_critique_persisted(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _factory_state(tmp_path, draft="Sloppy logic in §3.")
        runner = _structured_runner(
            _make_verifier_output(
                verdict=Verdict.FIXABLE,
                verdict_confidence=0.85,
                critique_entries=[
                    {
                        "category": "logical_gap",
                        "severity": "major",
                        "description": "Step 5 doesn't follow from Step 4.",
                    },
                ],
            ),
        )
        result = await verifier_node(
            state,
            seal_engine=engine,
            workspace=stub_workspace,
            citation_check_client=CannedCitationCheckClient(),
            structured_complete=runner,
        )
        assert result.current_critique is not None
        assert result.current_critique["verdict"] == "FIXABLE"
        assert result.current_critique["effective_verdict"] == "FIXABLE"
        assert result.current_critique["critique_hash"]
        # POST_VERIFIER seal carries critique_hash matching state.
        chain_files = sorted(
            (engine.chain_dir).glob("*POST_VERIFIER.payload.json"),
        )
        assert chain_files
        post_payload = json.loads(chain_files[-1].read_text(encoding="utf-8"))
        assert post_payload["metadata"]["critique_hash"] == result.current_critique["critique_hash"]
        assert post_payload["metadata"]["verdict"] == "FIXABLE"


class TestToolCallSeals:
    @pytest.mark.asyncio
    async def test_tool_call_seal_step_indices_recorded(
        self,
        engine: InMemorySealEngine,
        stub_workspace,
        tmp_path: Path,
    ) -> None:
        state = _factory_state(
            tmp_path,
            draft="Cite 10.1111/aaa and 10.2222/bbb here.",
        )
        runner = _structured_runner(_make_verifier_output(verdict=Verdict.CORRECT))
        result = await verifier_node(
            state,
            seal_engine=engine,
            workspace=stub_workspace,
            citation_check_client=CannedCitationCheckClient(),
            structured_complete=runner,
        )
        # 2 citations × 2 sources = 4 TOOL_CALL seals + PRE + POST = 6
        # plus genesis = 7
        report = await engine.verify_chain()
        assert report.total_steps == 7
        tool_call_steps = [s for s in report.steps if s.step_type == StepType.TOOL_CALL.value]
        assert len(tool_call_steps) == 4
        assert result.current_critique is not None
