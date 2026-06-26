# tests/conftest.py

"""
Shared fixtures and stubs for the M1+ test suite.

Promoted from ``tests/integration/test_generator_node.py`` so M2's
verifier / reviser node tests can reuse the same minimal stubs without
copy-paste drift.

The fixtures cover:

- A duck-typed :class:`StubConfig` mirroring
  :class:`slop_research_factory.config.FactoryConfig`.
- A duck-typed :class:`StubState` matching the field set
  ``generator_node`` (and future nodes) consume from
  :class:`slop_research_factory.types.state.FactoryState`.
- :class:`StubLLMResponse` / :class:`StubLLMClient` for canned
  inference (mirrors
  :class:`slop_research_factory.llm.client.LLMResponse` /
  :class:`~slop_research_factory.llm.client.LLMClient` but stays a
  plain dataclass so historical tests keep working).
- :class:`StubWorkspace` — a thin
  :class:`~slop_research_factory.workspace.manager.WorkspaceManager`
  surrogate that the generator already calls into.

Real concrete components (:class:`InMemorySealEngine`, ``seal_step``)
are imported from the production package; nodes are exercised against
the real seal layer so the chain emitted by these tests verifies via
:meth:`SealEngine.verify_chain`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pytest

from slop_research_factory.config import CheckpointBackend
from slop_research_factory.types.enums import RunStatus

# ──────────────────────────────────────────────────────────────────────────
# AppendOnlyList stub
# ──────────────────────────────────────────────────────────────────────────


class _AppendOnlyList(list):
    """Mirror of AppendOnlyList; suffices for stub state."""

    def __setitem__(self, key: Any, value: Any) -> None:  # noqa: D401
        raise TypeError("AppendOnlyList does not support item reassignment")

    def __delitem__(self, key: Any) -> None:
        raise TypeError("AppendOnlyList does not support deletion")


# ──────────────────────────────────────────────────────────────────────────
# Stub config / state matching FactoryConfig + FactoryState shape
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class StubConfig:
    """Lean clone of :class:`FactoryConfig` for tests that need duck-typing."""

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
    checkpoint_backend: CheckpointBackend = CheckpointBackend.SQLITE
    weight_logical_soundness: float = 0.35
    weight_mathematical_rigor: float = 0.25
    weight_citation_accuracy: float = 0.20
    weight_scope_compliance: float = 0.15
    weight_novelty_plausibility: float = 0.05


@dataclass
class StubState:
    """Lean clone of :class:`FactoryState` for stub-driven node tests.

    ``latest_hash`` defaults to the empty string so ``seal_step`` treats
    the first seal as genesis-anchored (parent_hash=None). Real runs
    will overwrite this in M2's ``begin_chain``.
    """

    run_id: str = "test-0000-0000-0000-000000000001"
    status: RunStatus = RunStatus.GENERATING
    config: Any = field(default_factory=StubConfig)
    brief: dict = field(default_factory=lambda: {"thesis": "Test thesis."})
    step_index: int = 0
    latest_hash: str = ""
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


# ──────────────────────────────────────────────────────────────────────────
# Stub LLM client / response (kept structurally compatible with LLMResponse)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class StubLLMResponse:
    """Mirror of :class:`~slop_research_factory.llm.client.LLMResponse`.

    Kept as a plain mutable dataclass so historical tests can build
    overridden instances by argument; production code consumes only
    the fields, not the concrete class.
    """

    content: str = (
        '<details class="_chainOfThought_18ihl_344">\n'
        "<summary>Reasoning</summary>\n"
        "reasoning here\n"
        "</details>\n"
        "# Draft Title\n"
        "Body text."
    )
    raw_response: dict = field(
        default_factory=lambda: {
            "id": "resp-001",
            "model": "deepseek/deepseek-r1",
            "choices": [
                {
                    "message": {
                        "content": (
                            '<details class="_chainOfThought_18ihl_344">\n'
                            "<summary>Reasoning</summary>\n\n\n"
                            "reasoning\n"
                            "</details>\n"
                            "Body"
                        )
                    }
                }
            ],
        }
    )
    input_tokens: int = 1100
    output_tokens: int = 7000
    think_tokens: int | None = 12400
    model: str = "deepseek/deepseek-r1"
    api_response_id: str | None = "resp-001"
    api_provider: str = "openrouter"
    retries: int = 0
    sampling_params: dict = field(default_factory=dict)


class StubLLMClient:
    """Records calls and returns a canned :class:`StubLLMResponse`."""

    def __init__(self, response: StubLLMResponse | None = None) -> None:
        self.response = response or StubLLMResponse()
        self.calls: list[dict] = []

    async def complete(self, *, model: str, messages: list[dict], **kw: Any) -> StubLLMResponse:
        self.calls.append({"model": model, "messages": messages, **kw})
        return self.response


# ──────────────────────────────────────────────────────────────────────────
# Stub workspace
# ──────────────────────────────────────────────────────────────────────────


class StubWorkspace:
    """Lightweight workspace surrogate used by node tests.

    Exposes the minimum surface ``generator_node`` (and other nodes)
    consume: ``drafts_path``, ``chain_dir``, ``relative``, plus atomic
    file write helpers. No fsync — speed matters more in tests.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "drafts").mkdir(parents=True, exist_ok=True)
        (root / "chain").mkdir(parents=True, exist_ok=True)
        (root / "output").mkdir(parents=True, exist_ok=True)

    @property
    def run_dir(self) -> Path:
        """Align with :class:`WorkspaceManager.run_dir` (stub root = run root)."""
        return self.root

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def brief_path(self) -> Path:
        return self.root / "brief.json"

    @property
    def workspace_path(self) -> Path:
        return self.root

    def drafts_path(self, filename: str) -> Path:
        return self.root / "drafts" / filename

    def tools_path(self, filename: str) -> Path:
        (self.root / "tools").mkdir(parents=True, exist_ok=True)
        return self.root / "tools" / filename

    def citations_path(self, filename: str) -> Path:
        (self.root / "citations").mkdir(parents=True, exist_ok=True)
        return self.root / "citations" / filename

    @property
    def chain_dir(self) -> Path:
        return self.root / "chain"

    def chain_path(self, filename: str) -> Path:
        return self.root / "chain" / filename

    def relative(self, path: Path) -> str:
        return str(Path(path).relative_to(self.root))

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_output_file(self, filename: str, content: str) -> Path:
        path = self.output_dir / filename
        self.write_text(path, content)
        return path

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def write_state(self, state: Any) -> None:
        p = self.root / "state.json"
        tmp = self.root / "state.json.tmp"
        tmp.write_text(
            json.dumps(asdict(state), indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(p)


# ──────────────────────────────────────────────────────────────────────────
# Pytest fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_workspace(tmp_path: Path) -> StubWorkspace:
    """Stub workspace anchored at pytest's per-test ``tmp_path``."""
    return StubWorkspace(tmp_path)


@pytest.fixture
def stub_state(tmp_path: Path) -> StubState:
    """Fresh :class:`StubState` rooted at ``tmp_path``."""
    s = StubState()
    s.workspace = str(tmp_path)
    return s


@pytest.fixture
def in_memory_seal_engine(tmp_path: Path):
    """Concrete in-memory seal engine, scoped to ``tmp_path``.

    Genesis is **not** sealed — tests that need a chain start should
    request :func:`genesis_seal_engine` instead. Use this fixture for
    unit tests that exercise pre-genesis edge cases.
    """
    from slop_research_factory.seal.engine import InMemorySealEngine

    return InMemorySealEngine.create(tmp_path, run_id="test-run-0001")


@pytest.fixture
async def genesis_seal_engine(tmp_path: Path):
    """In-memory engine with ``begin_chain`` already called.

    Mirrors the orchestrator's M2 wire-up so node tests can call
    :func:`seal_step` directly and have parent linkage point at the
    genesis content hash rather than ``None``.
    """
    from slop_research_factory.seal.engine import InMemorySealEngine

    engine = InMemorySealEngine.create(tmp_path, run_id="test-run-0001")
    await engine.begin_chain(research_brief={"title": "test"})
    return engine


@pytest.fixture
def stub_llm_client():
    """Default :class:`StubLLMClient` with the standard reasoning payload."""
    return StubLLMClient()
