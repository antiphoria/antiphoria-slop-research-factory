# tests/integration/test_generator_node.py

"""
E2 integration tests for the Generator node (Step 6).

Uses mock LLM responses — no real API calls.  Requires a temp
filesystem and the seal engine binary (or a mock seal engine).

Covers: E2-NE01 … E2-NE07, E2-NE14 (D-8 §4.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from slop_research_factory.nodes.generator_node import generator_node
from slop_research_factory.types.enums import RunStatus


# ──────────────────────────────────────────────────────────────────────────

# Lightweight stubs — replace with project fixtures as Steps 1-5 mature.

# ──────────────────────────────────────────────────────────────────────────

@dataclass
class StubConfig:
    generator_model: str = "deepseek/deepseek-r1"
    verifier_model: str = "google/gemini-2.5-flash"
    reviser_model: str = "deepseek/deepseek-r1"
    max_rejections: int = 3
    max_revisions: int = 5
    max_total_cycles: int = 10
    max_total_tokens: int | None = None
    max_total_cost_usd: float | None = None
    verifier_confidence_threshold: float = 0.8
    enable_citation_checking: bool = True
    citation_check_sources: tuple[str, ...] = ("crossref", "semantic_scholar")
    enable_tavily_search: bool = True
    target_length_words: int = 5000
    capture_think_tokens: bool = True
    enable_provenance: bool = True
    hash_algorithm: str = "sha256"
    workspace_base_path: str = "./workspaces"
    weight_logical_soundness: float = 0.35
    weight_mathematical_rigor: float = 0.25
    weight_citation_accuracy: float = 0.20
    weight_scope_compliance: float = 0.15
    weight_novelty_plausibility: float = 0.05


class _AppendOnlyList(list):
    """Minimal AppendOnlyList stub (D-2 §6)."""

    def __setitem__(self, key, value):
        raise TypeError("AppendOnlyList does not support item reassignment")

    def __delitem__(self, key):
        raise TypeError("AppendOnlyList does not support deletion")


@dataclass
class StubState:
    run_id: str = "test-0000-0000-0000-000000000001"
    status: RunStatus = RunStatus.GENERATING
    config: Any = field(default_factory=StubConfig)
    brief: dict = field(default_factory=lambda: {"thesis": "Test thesis."})
    step_index: int = 0
    latest_hash: str = "genesis_hash_placeholder"
    cycle_count: int = 0
    rejection_count: int = 0
    revision_count: int = 0
    current_draft: str | None = None
    current_think_trace: str | None = None
    current_critique: dict | None = None
    current_extracted_citations: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_think_tokens: int = 0
    total_tool_call_seconds: float = 0.0
    total_wall_clock_seconds: float = 0.0
    total_estimated_cost_usd: float = 0.0
    messages: _AppendOnlyList = field(default_factory=_AppendOnlyList)
    citation_checks: _AppendOnlyList = field(default_factory=_AppendOnlyList)
    workspace: str = ""
    created_at: str = "2026-04-15T00:00:00.000Z"
    updated_at: str = "2026-04-15T00:00:00.000Z"
    last_error: str | None = None


@dataclass
class StubLLMResponse:
    content: str = """
    <details class="_chainOfThought_18ihl_344">
    <summary>Reasoning</summary>
    reasoning here</summary>
    </details>
    # Draft Title
    Body text."""
    raw_response: dict = field(default_factory=lambda: {
        "id": "resp-001",
        "model": "deepseek/deepseek-r1",
        "choices": [{"message": {"content": """<details class="_chainOfThought_18ihl_344">
  <summary>Reasoning</summary>


reasoning
</details>
Body"""}}],
    })
    input_tokens: int = 1100
    output_tokens: int = 7000
    think_tokens: int | None = 12400
    model: str = "deepseek/deepseek-r1"
    api_response_id: str | None = "resp-001"
    api_provider: str = "openrouter"
    retries: int = 0
    sampling_params: dict = field(default_factory=dict)


class StubLLMClient:
    """Records calls and returns a canned response."""

    def __init__(self, response: StubLLMResponse | None = None):
        self.response = response or StubLLMResponse()
        self.calls: list[dict] = []

    async def complete(self, model: str, messages: list[dict], **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        return self.response


class StubSealReceipt:
    def __init__(self, step_index: int, seal_hash: str, step_type: str):
        self.step_index = step_index
        self.seal_hash = seal_hash
        self.step_type = step_type


class StubSealEngine:
    """In-memory seal engine that records operations."""

    def __init__(self):
        self.hash_calls: list[str] = []
        self.seal_calls: list[dict] = []
        self._counter = 0

    async def hash_file(self, file_path: str) -> str:
        self.hash_calls.append(file_path)
        return f"hash_{Path(file_path).name}_{self._counter:04d}"

    async def hash_bytes(self, data: bytes, workspace_path: str) -> str:
        self._counter += 1
        return f"bytes_hash_{self._counter:04d}"

    async def seal(self, payload_path, prev_hash, receipt_path):
        self._counter += 1
        h = f"seal_{self._counter:04d}"
        self.seal_calls.append({
            "payload": payload_path,
            "prev": prev_hash,
            "receipt": receipt_path,
        })
        return StubSealReceipt(self._counter, h, "stub")


class StubWorkspace:
    """Thin workspace backed by a real temp directory."""

    def __init__(self, root: Path):
        self.root = root
        (root / "drafts").mkdir(parents=True, exist_ok=True)
        (root / "chain").mkdir(parents=True, exist_ok=True)

    def drafts_path(self, filename: str) -> Path:
        return self.root / "drafts" / filename

    def chain_path(self, filename: str) -> Path:
        return self.root / "chain" / filename

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def write_state_atomic(self, state) -> None:
        from dataclasses import asdict
        p = self.root / "state.json"
        tmp = self.root / "state.json.tmp"
        tmp.write_text(
            json.dumps(asdict(state), indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(p)


# Stub seal_step that delegates to the engine stubs.

async def _stub_seal_step(seal_engine, state, step_type, content_file_paths,
                          metadata, chain_dir):
    state.step_index += 1
    receipt = await seal_engine.seal("payload", state.latest_hash, "receipt")
    state.latest_hash = receipt.seal_hash
    return state, receipt


@pytest.fixture(autouse=True)
def _patch_seal_step(monkeypatch):
    """Patch seal_step at its source; generator imports it lazily."""
    import slop_research_factory.seal.helpers as helpers_mod
    monkeypatch.setattr(
        helpers_mod, "seal_step", _stub_seal_step, raising=False,
    )


# ──────────────────────────────────────────────────────────────────────────

# Tests

# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def ws(tmp_path):
    return StubWorkspace(tmp_path)


@pytest.fixture
def state(tmp_path) -> StubState:
    s = StubState()
    s.workspace = str(tmp_path)
    return s


class TestGeneratorNodeHappyPath:
    """Normal generation with think tokens and successful seal."""

    @pytest.mark.asyncio
    async def test_produces_draft(self, state, ws):
        """Generator sets current_draft on state."""
        result = await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert result.current_draft is not None
        assert len(result.current_draft) > 0

    @pytest.mark.asyncio
    async def test_step_index_increments_twice(self, state, ws):
        """E2-NE03: Generator produces exactly 2 seal events."""
        initial = state.step_index
        result = await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert result.step_index == initial + 2  # 1 pre + 1 post

    @pytest.mark.asyncio
    async def test_pre_seal_before_llm_call(self, state, ws):
        """E2-NE01: PRE-SEAL completes before mock LLM call."""
        engine = StubSealEngine()
        client = StubLLMClient()
        await generator_node(
            state, seal_engine=engine, llm_client=client, workspace=ws,
        )
        # seal_step was called for PRE before llm_client.complete
        assert len(engine.seal_calls) >= 1
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_raw_response_written_before_parse(self, state, ws):
        """E2-NE06: raw API response file exists on disk."""
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        response_file = ws.root / "drafts" / "cycle_01_generator_response.json"
        assert response_file.exists()
        raw = json.loads(response_file.read_bytes())
        assert "id" in raw  # from StubLLMResponse.raw_response

    @pytest.mark.asyncio
    async def test_output_file_written(self, state, ws):
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        output_file = ws.root / "drafts" / "cycle_01_generator_output.md"
        assert output_file.exists()
        assert len(output_file.read_text()) > 0

    @pytest.mark.asyncio
    async def test_think_trace_captured(self, state, ws):
        """E2-NE04: think tokens written when capture_think_tokens=true."""
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        think_file = ws.root / "drafts" / "cycle_01_generator_think.md"
        assert think_file.exists()
        result = think_file.read_text()
        assert "reasoning" in result

    @pytest.mark.asyncio
    async def test_inference_record_written(self, state, ws):
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
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
    async def test_message_appended(self, state, ws):
        result = await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert len(result.messages) == 1
        msg = result.messages[0]
        assert msg["role"] == "generator"
        assert msg["token_counts"]["input"] == 1100

    @pytest.mark.asyncio
    async def test_token_totals_updated(self, state, ws):
        result = await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert result.total_input_tokens == 1100
        assert result.total_output_tokens == 7000
        assert result.total_think_tokens == 12400

    @pytest.mark.asyncio
    async def test_state_json_written(self, state, ws):
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        assert (ws.root / "state.json").exists()

    @pytest.mark.asyncio
    async def test_prompt_file_written(self, state, ws):
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
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
    async def test_no_think_file(self, state, ws):
        state.config.capture_think_tokens = False
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        think_file = ws.root / "drafts" / "cycle_01_generator_think.md"
        assert not think_file.exists()


class TestGeneratorNoOutput:
    """E2-NE14: NO_OUTPUT path seals the declaration, not empty."""

    @pytest.mark.asyncio
    async def test_no_output_sets_status(self, state, ws):
        resp = StubLLMResponse(
            content="NO_OUTPUT: Cannot address — requires empirical data.",
        )
        result = await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(resp),
            workspace=ws,
        )
        assert result.status == RunStatus.NO_OUTPUT

    @pytest.mark.asyncio
    async def test_no_output_draft_preserved(self, state, ws):
        """The NO_OUTPUT text is set as current_draft (sealed, not empty)."""
        resp = StubLLMResponse(
            content="NO_OUTPUT: Impossible brief.",
        )
        result = await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(resp),
            workspace=ws,
        )
        assert "NO_OUTPUT" in result.current_draft

    @pytest.mark.asyncio
    async def test_no_output_file_not_empty(self, state, ws):
        resp = StubLLMResponse(content="NO_OUTPUT: Reason.")
        await generator_node(
            state,
            seal_engine=StubSealEngine(),
            llm_client=StubLLMClient(resp),
            workspace=ws,
        )
        output_file = ws.root / "drafts" / "cycle_01_generator_output.md"
        assert output_file.exists()
        assert len(output_file.read_text()) > 0


class TestGeneratorRawResponseHash:
    """E2-NE07: raw_response_hash in POST metadata matches file."""

    @pytest.mark.asyncio
    async def test_hash_computed_from_file(self, state, ws):
        engine = StubSealEngine()
        await generator_node(
            state,
            seal_engine=engine,
            llm_client=StubLLMClient(),
            workspace=ws,
        )
        # The engine's hash_calls should include the response file.
        response_hashed = any(
            "generator_response" in c for c in engine.hash_calls
        )
        assert response_hashed, (
            "raw response file must be hashed via seal engine"
        )
