# orchestrator.py
# src/slop_research_factory/orchestrator.py

"""
Top-level orchestrator — single entry point for the SLOP Research Factory.

This module owns the lifecycle of a single pipeline run:

  1. Bootstrap — run ID, workspace, config, seal engine.
  2. Genesis — seal the initial state (brief + config).
  3. Execution — invoke the LangGraph pipeline.
  4. Terminal handling — verify chain, persist final state, log outcome.
  5. Return — hand back the terminal ``FactoryState``.

Usage:

.. code-block:: python

    from slop_research_factory.orchestrator import run_factory
    from slop_research_factory.types.brief import ResearchBrief

    brief = ResearchBrief(thesis="...", ...)
    state = await run_factory(brief)

For CLI usage see ``slop_research_factory.cli``.

Resume semantics (v0.1.0):
    When ``resume=True``, the orchestrator loads existing workspace
    state, reconnects to the chain (verifying integrity), and re-enters
    the graph from the appropriate node. This is required for
    crash recovery and human-rescue resume.

Spec references:
    D-0 §13   Implementation step plan.
    D-2 §3    Run lifecycle.
    D-2 §4    Configuration contract.
    D-5 §3    Orchestrator responsibilities.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from slop_research_factory.config import FactoryConfig
from slop_research_factory.engine.graph import GraphDependencies, run_graph
from slop_research_factory.seal.sdk_adapter import create_seal_engine
from slop_research_factory.types.enums import RunStatus
from slop_research_factory.types.provenance import VerificationReport
from slop_research_factory.types.state import AppendOnlyList, FactoryState
from slop_research_factory.workspace.manager import WorkspaceManager

__all__ = [
    "FactoryResult",
    "resume_factory",
    "run_factory",
]

logger = logging.getLogger(__name__)


# ── Result wrapper ───────────────────────────────────────────────────


class FactoryResult:
    """Container for the terminal outcome of a factory run.

    Attributes:
        state:               Final :class:`FactoryState`.
        verification_report: Chain verification result (``None`` if
            verification was skipped due to non-COMPLETED status).
        workspace_path:      Absolute path to the workspace directory.
        elapsed_seconds:     Wall-clock time for the entire run.
    """

    __slots__ = ("elapsed_seconds", "state", "verification_report", "workspace_path")

    def __init__(
        self,
        state: FactoryState,
        verification_report: VerificationReport | None,
        workspace_path: Path,
        elapsed_seconds: float,
    ) -> None:
        self.state = state
        self.verification_report = verification_report
        self.workspace_path = workspace_path
        self.elapsed_seconds = elapsed_seconds

    @property
    def success(self) -> bool:
        """True if the run completed successfully with an intact chain."""
        if self.state.status != RunStatus.COMPLETED:
            return False
        if self.verification_report is None:
            return False
        return self.verification_report.chain_intact

    def summary(self) -> str:
        """One-line human-readable summary."""
        status = self.state.status.value
        chain = ""
        if self.verification_report:
            chain = " chain=INTACT" if self.verification_report.chain_intact else " chain=BROKEN"
        return (
            f"[{self.state.run_id[:8]}] status={status}{chain} "
            f"cycles={self.state.cycle_count} "
            f"cost=${self.state.total_estimated_cost_usd:.4f} "
            f"elapsed={self.elapsed_seconds:.1f}s"
        )


# ── Helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _generate_run_id() -> str:
    """Generate a unique run identifier (UUID4, no hyphens for filesystem safety)."""
    return uuid.uuid4().hex


def _serialize_json(data: Any) -> str:
    """Canonical JSON with sorted keys and 2-space indent."""
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


# ── LLM client construction ─────────────────────────────────────────


def _build_llm_client(config: FactoryConfig) -> Any:
    """Construct the appropriate LLM client based on config.

    Returns a :class:`LiteLLMClient` for production or a
    :class:`CannedLLMClient` when explicitly requested (testing).
    """
    from slop_research_factory.llm.client import LiteLLMClient

    sampling: dict[str, Any] = {}
    if config.default_temperature is not None:
        sampling["temperature"] = config.default_temperature
    if config.default_top_p is not None:
        sampling["top_p"] = config.default_top_p
    if config.default_max_tokens is not None:
        sampling["max_tokens"] = config.default_max_tokens

    return LiteLLMClient(
        default_sampling=sampling,
        num_retries=config.llm_retries,
        request_timeout_seconds=config.llm_timeout_seconds,
    )


def _build_citation_client(config: FactoryConfig) -> Any:
    """Construct the citation check client.

    v0.1.0: Always returns a canned client (no HTTP backends yet).
    Future: conditionally construct HTTP client when
    ``config.citation_backend == "http"``.
    """
    from slop_research_factory.tools.canned import default_canned_client

    return default_canned_client()


def _build_structured_complete(config: FactoryConfig) -> Any:
    """Build the structured completion callable for the verifier.

    Returns ``complete_structured`` from the structured module, or
    ``None`` if instructor is not available (falls back to manual
    parsing in verifier node).
    """
    try:
        from slop_research_factory.llm.structured import complete_structured

        return complete_structured
    except ImportError:
        logger.warning("[orchestrator] instructor not installed — verifier will use manual parsing")
        return None


# ── State bootstrapping ──────────────────────────────────────────────


def _bootstrap_state(
    *,
    run_id: str,
    config: FactoryConfig,
    brief: dict[str, Any],
    step_index: int,
    latest_hash: str | None,
) -> FactoryState:
    """Construct the initial FactoryState after genesis is sealed."""
    now = _now_iso()
    return FactoryState(
        run_id=run_id,
        config=config,
        status=RunStatus.GENERATING,
        brief=brief,
        current_draft=None,
        current_critique=None,
        messages=AppendOnlyList(),
        citation_checks=AppendOnlyList(),
        step_index=step_index,
        latest_hash=latest_hash or "",
        cycle_count=0,
        rejection_count=0,
        revision_count=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_think_tokens=0,
        total_estimated_cost_usd=0.0,
        total_wall_clock_seconds=0.0,
        created_at=now,
        updated_at=now,
    )


# ── Main entry point ────────────────────────────────────────────────


async def run_factory(
    brief: Any,
    config: FactoryConfig | None = None,
    *,
    run_id: str | None = None,
    workspace_root: Path | str | None = None,
    llm_client: Any | None = None,
    citation_client: Any | None = None,
    structured_complete: Any | None = None,
) -> FactoryResult:
    """Execute a complete research factory pipeline.

    This is the **primary public API** for programmatic usage.

    Args:
        brief:              Research brief (dataclass or dict). If a
            dataclass, ``.to_dict()`` or ``dataclasses.asdict()`` is
            called to produce the serialisable form.
        config:             Factory configuration. Defaults are used
            when ``None``.
        run_id:             Unique identifier for this run. Auto-
            generated (UUID4) when ``None``.
        workspace_root:     Parent directory for run workspaces.
            Defaults to ``./workspace``.
        llm_client:         Pre-built LLM client (test seam). When
            ``None``, a :class:`LiteLLMClient` is constructed from
            config.
        citation_client:    Pre-built citation client (test seam).
            When ``None``, a canned client is used.
        structured_complete: Pre-built structured completion callable
            (test seam). When ``None``, auto-detected.

    Returns:
        A :class:`FactoryResult` containing the terminal state,
        verification report, and run metadata.

    Raises:
        RuntimeError: On unrecoverable infrastructure failures (missing
            deps, filesystem errors).
        ValueError:  On invalid brief or config.
    """
    wall_start = time.monotonic()
    config = config or FactoryConfig()
    run_id = run_id or _generate_run_id()
    workspace_root = Path(workspace_root or "./workspace")

    logger.info(
        "[orchestrator] [%s] Starting factory run",
        run_id[:8],
    )

    # ── 5.2: Run ID ──────────────────────────────────────────────
    logger.info("[orchestrator] [%s] Run ID: %s", run_id[:8], run_id)

    # ── 5.3: Workspace ───────────────────────────────────────────
    workspace_path = workspace_root / run_id
    workspace = WorkspaceManager(workspace_root, run_id)
    workspace.initialize()

    logger.info(
        "[orchestrator] [%s] Workspace: %s",
        run_id[:8],
        workspace_path,
    )

    # ── 5.4: Persist config + brief ──────────────────────────────
    brief_dict = _coerce_brief(brief)
    config_dict = _coerce_config(config)

    config_path = workspace_path / "config.json"
    config_path.write_text(_serialize_json(config_dict), encoding="utf-8")

    brief_path = workspace_path / "brief.json"
    brief_path.write_text(_serialize_json(brief_dict), encoding="utf-8")

    logger.info(
        "[orchestrator] [%s] Config + brief persisted",
        run_id[:8],
    )

    # ── 5.5: Seal engine ─────────────────────────────────────────
    seal_engine = create_seal_engine(
        workspace=workspace_path,
        run_id=run_id,
        enable_provenance=config.enable_provenance,
        resume=False,
    )

    # ── 5.6: Genesis ─────────────────────────────────────────────
    genesis_receipt = await seal_engine.begin_chain(
        research_brief=brief_dict,
        metadata={
            "config_hash": await seal_engine.hash_file(str(config_path)),
            "brief_hash": await seal_engine.hash_file(str(brief_path)),
            "factory_version": "0.1.0",
        },
    )

    logger.info(
        "[orchestrator] [%s] GENESIS sealed (step=%d, hash=%s…)",
        run_id[:8],
        genesis_receipt.step_index,
        genesis_receipt.entry_hash[:12],
    )

    # ── 5.7: Bootstrap state ─────────────────────────────────────
    state = _bootstrap_state(
        run_id=run_id,
        config=config,
        brief=brief_dict,
        step_index=genesis_receipt.step_index,
        latest_hash=genesis_receipt.entry_hash,
    )

    # Persist initial state checkpoint
    workspace.write_state(state)

    # ── 5.8: Build dependencies + run graph ──────────────────────
    effective_llm = llm_client or _build_llm_client(config)
    effective_citation = citation_client or _build_citation_client(config)
    effective_structured = structured_complete or _build_structured_complete(config)

    deps = GraphDependencies(
        seal_engine=seal_engine,
        workspace=workspace,
        llm_client=effective_llm,
        citation_check_client=effective_citation,
        structured_complete=effective_structured,
    )

    logger.info(
        "[orchestrator] [%s] Entering pipeline graph",
        run_id[:8],
    )

    try:
        state = await run_graph(state, deps)
    except Exception:
        logger.exception(
            "[orchestrator] [%s] Pipeline graph raised — marking FAILED",
            run_id[:8],
        )
        state.status = RunStatus.FAILED
        state.updated_at = _now_iso()
        workspace.write_state(state)

    # ── 5.9: Terminal status handling ─────────────────────────────
    wall_elapsed = time.monotonic() - wall_start
    state.total_wall_clock_seconds = round(wall_elapsed, 3)
    state.updated_at = _now_iso()

    verification_report: VerificationReport | None = None

    if state.status == RunStatus.COMPLETED:
        # 5.10: Verify chain integrity
        verification_report = await seal_engine.verify_chain()
        _log_completion(state, verification_report, wall_elapsed)

        # Persist verification report
        report_dict = _verification_report_to_dict(verification_report)
        report_path = workspace_path / "output" / "chain_verification.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_serialize_json(report_dict), encoding="utf-8")

    elif state.status == RunStatus.FAILED:
        logger.error(
            "[orchestrator] [%s] Run FAILED after %.1fs",
            run_id[:8],
            wall_elapsed,
        )

    elif state.status == RunStatus.NO_OUTPUT:
        logger.warning(
            "[orchestrator] [%s] Run terminated NO_OUTPUT after %.1fs — "
            "model declined to produce substantive content",
            run_id[:8],
            wall_elapsed,
        )

    elif state.status == RunStatus.AWAITING_HUMAN:
        logger.info(
            "[orchestrator] [%s] Run paused AWAITING_HUMAN after %.1fs — "
            "inspect workspace/rescue/ and resume via CLI",
            run_id[:8],
            wall_elapsed,
        )

    else:
        logger.warning(
            "[orchestrator] [%s] Run ended with unexpected status: %s",
            run_id[:8],
            state.status.value,
        )

    # Final state checkpoint
    workspace.write_state(state)

    result = FactoryResult(
        state=state,
        verification_report=verification_report,
        workspace_path=workspace_path,
        elapsed_seconds=round(wall_elapsed, 3),
    )

    logger.info("[orchestrator] [%s] %s", run_id[:8], result.summary())
    return result


# ── Resume entry point ───────────────────────────────────────────────


async def resume_factory(
    workspace_path: Path | str,
    *,
    llm_client: Any | None = None,
    citation_client: Any | None = None,
    structured_complete: Any | None = None,
    human_response: dict[str, Any] | None = None,
) -> FactoryResult:
    """Resume a paused or crashed factory run.

    This handles two scenarios:

    1. **Crash recovery**: The run was interrupted mid-pipeline. The
       orchestrator loads the last checkpoint, reconnects to the chain
       (verifying integrity), and re-enters the graph.

    2. **Human rescue resume**: The run is in ``AWAITING_HUMAN`` status.
       The operator has placed corrections in ``rescue/response.json``
       (or passed them via ``human_response``). The orchestrator applies
       corrections and re-enters the graph.

    Args:
        workspace_path:     Path to existing run workspace.
        llm_client:         Pre-built LLM client (test seam).
        citation_client:    Pre-built citation client (test seam).
        structured_complete: Pre-built structured callable (test seam).
        human_response:     Human corrections dict (alternative to
            reading ``rescue/response.json``).

    Returns:
        A :class:`FactoryResult` for the resumed run.

    Raises:
        FileNotFoundError: If workspace or state file doesn't exist.
        ValueError:        If state cannot be loaded.
        RuntimeError:      If chain integrity check fails on resume.
    """
    wall_start = time.monotonic()
    workspace_path = Path(workspace_path).resolve()
    workspace = WorkspaceManager.for_run_directory(workspace_path)

    # Load persisted state
    state = workspace.load_state()
    run_id = state.run_id
    config = state.config

    logger.info(
        "[orchestrator] [%s] Resuming run (status=%s, step=%d)",
        run_id[:8],
        state.status.value,
        state.step_index,
    )

    # Reconnect seal engine (verifies chain integrity)
    seal_engine = create_seal_engine(
        workspace=workspace_path,
        run_id=run_id,
        enable_provenance=config.enable_provenance,
        resume=True,
    )

    # Handle human rescue resume
    if state.status == RunStatus.AWAITING_HUMAN:
        response = human_response or _load_human_response(workspace_path)
        if response is None:
            raise ValueError(
                f"Run {run_id} is AWAITING_HUMAN but no response found. "
                f"Place corrections in {workspace_path}/rescue/response.json "
                f"or pass human_response= argument."
            )
        state = _apply_human_response(state, response)
        logger.info(
            "[orchestrator] [%s] Human response applied — resuming as %s",
            run_id[:8],
            state.status.value,
        )

    elif state.status in (RunStatus.COMPLETED, RunStatus.NO_OUTPUT):
        raise ValueError(
            f"Run {run_id} already in terminal status {state.status.value} — cannot resume."
        )

    elif state.status == RunStatus.FAILED:
        # Re-enter from last known good point
        state.status = RunStatus.GENERATING
        logger.info(
            "[orchestrator] [%s] FAILED → GENERATING (retry from last checkpoint)",
            run_id[:8],
        )

    # Build dependencies
    effective_llm = llm_client or _build_llm_client(config)
    effective_citation = citation_client or _build_citation_client(config)
    effective_structured = structured_complete or _build_structured_complete(config)

    deps = GraphDependencies(
        seal_engine=seal_engine,
        workspace=workspace,
        llm_client=effective_llm,
        citation_check_client=effective_citation,
        structured_complete=effective_structured,
    )

    logger.info(
        "[orchestrator] [%s] Re-entering pipeline graph",
        run_id[:8],
    )

    try:
        state = await run_graph(state, deps)
    except Exception:
        logger.exception(
            "[orchestrator] [%s] Pipeline graph raised on resume — marking FAILED",
            run_id[:8],
        )
        state.status = RunStatus.FAILED
        state.updated_at = _now_iso()
        workspace.write_state(state)

    # Terminal handling (same as run_factory)
    wall_elapsed = time.monotonic() - wall_start
    state.total_wall_clock_seconds += round(wall_elapsed, 3)
    state.updated_at = _now_iso()

    verification_report: VerificationReport | None = None

    if state.status == RunStatus.COMPLETED:
        verification_report = await seal_engine.verify_chain()
        _log_completion(state, verification_report, wall_elapsed)

        report_dict = _verification_report_to_dict(verification_report)
        report_path = workspace_path / "output" / "chain_verification.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_serialize_json(report_dict), encoding="utf-8")

    workspace.write_state(state)

    result = FactoryResult(
        state=state,
        verification_report=verification_report,
        workspace_path=workspace_path,
        elapsed_seconds=round(wall_elapsed, 3),
    )

    logger.info("[orchestrator] [%s] %s", run_id[:8], result.summary())
    return result


# ── Internal helpers ─────────────────────────────────────────────────


def _coerce_brief(brief: Any) -> dict[str, Any]:
    """Coerce a brief (dataclass, Pydantic, or dict) to a plain dict."""
    if isinstance(brief, dict):
        return dict(brief)
    if hasattr(brief, "model_dump"):
        return brief.model_dump()
    if hasattr(brief, "to_dict"):
        return brief.to_dict()
    # dataclass fallback
    import dataclasses

    if dataclasses.is_dataclass(brief) and not isinstance(brief, type):
        return dataclasses.asdict(brief)
    raise TypeError(
        f"Cannot coerce brief of type {type(brief).__name__} to dict. "
        f"Expected a dataclass, Pydantic model, or plain dict."
    )


def _coerce_config(config: FactoryConfig) -> dict[str, Any]:
    """Coerce FactoryConfig to a JSON-serialisable dict."""
    import dataclasses
    from enum import Enum

    result: dict[str, Any] = {}
    for f in dataclasses.fields(config):
        value = getattr(config, f.name)
        if isinstance(value, Enum):
            result[f.name] = value.value
        elif isinstance(value, tuple):
            result[f.name] = list(value)
        elif isinstance(value, Path):
            result[f.name] = str(value)
        else:
            result[f.name] = value
    return result


def _load_human_response(workspace_path: Path) -> dict[str, Any] | None:
    """Load human response from rescue/response.json if present."""
    response_path = workspace_path / "rescue" / "response.json"
    if not response_path.exists():
        return None
    try:
        content = response_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "[orchestrator] Failed to load human response: %s",
            exc,
        )
        return None


def _apply_human_response(
    state: FactoryState,
    response: dict[str, Any],
) -> FactoryState:
    """Apply human corrections to state and transition out of AWAITING_HUMAN.

    The human response dict may contain:
    - ``corrected_draft``: Replacement draft text.
    - ``corrected_brief``: Updated brief fields (merged).
    - ``action``: One of "retry", "revise", "accept".
    - ``notes``: Human notes (stored in metadata).
    """
    action = response.get("action", "retry")

    # Apply draft correction
    if "corrected_draft" in response:
        state.current_draft = response["corrected_draft"]
        logger.info("[orchestrator] Human provided corrected draft")

    # Merge brief corrections
    if "corrected_brief" in response and isinstance(response["corrected_brief"], dict):
        state.brief.update(response["corrected_brief"])
        logger.info("[orchestrator] Human updated brief fields")

    # Determine re-entry status
    if action == "accept":
        # Human accepts current state — go straight to finalize
        state.status = RunStatus.FINALIZING
    elif action == "revise":
        # Human wants one more revision pass
        state.status = RunStatus.REVISING
    else:
        # Default: retry from generation
        state.status = RunStatus.GENERATING

    state.updated_at = _now_iso()
    return state


def _log_completion(
    state: FactoryState,
    report: VerificationReport,
    elapsed: float,
) -> None:
    """Log a structured completion message."""
    integrity = "INTACT" if report.chain_intact else "BROKEN"
    logger.info(
        "[orchestrator] [%s] Run COMPLETED — chain=%s steps=%d cycles=%d cost=$%.4f elapsed=%.1fs",
        state.run_id[:8],
        integrity,
        report.total_steps,
        state.cycle_count,
        state.total_estimated_cost_usd,
        elapsed,
    )
    if not report.chain_intact:
        logger.error(
            "[orchestrator] [%s] ⚠️  CHAIN INTEGRITY FAILURE at step %d",
            state.run_id[:8],
            report.first_error_index,
        )


def _verification_report_to_dict(report: VerificationReport) -> dict[str, Any]:
    """Serialize a VerificationReport to a JSON-friendly dict."""
    return {
        "_schema_version": "0.1",
        "run_id": report.run_id,
        "chain_intact": report.chain_intact,
        "total_steps": report.total_steps,
        "first_error_index": report.first_error_index,
        "steps": [
            {
                "step_index": s.step_index,
                "step_type": s.step_type,
                "record_path": str(s.record_path) if s.record_path else None,
                "signature_valid": s.signature_valid,
                "content_hashes_valid": s.content_hashes_valid,
                "previous_hash_matches": s.previous_hash_matches,
                "canonical_form_valid": s.canonical_form_valid,
                "errors": s.errors,
                "ok": s.ok,
            }
            for s in report.steps
        ],
    }
