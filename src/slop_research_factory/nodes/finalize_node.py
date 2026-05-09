# nodes/finalize_node.py
# src/slop_research_factory/nodes/finalize_node.py

"""
Finalize node — assembles terminal output artifacts and seals the MANIFEST.

Unlike Generator/Verifier/Reviser, this node performs no LLM inference.
Its work is deterministic assembly:

  1. Verify chain integrity (read-only).
  2. Render ``paper.md`` (front matter + current_draft).
  3. Build and render ``hai_card.md``.
  4. Build ``manifest.json`` (run summary, model topology, config overrides).
  5. Optionally render ``provenance_report.md``.
  6. Seal a single MANIFEST step covering all output artifacts.
  7. Transition state to COMPLETED.

There is no PRE/POST split because no LLM call occurs; the MANIFEST
seal is the single terminal chain entry.

Spec references:
    D-0 §5.2   MANIFEST seal as chain terminal.
    D-2 §4     configuration_overrides computation.
    D-2 §10    HAI Card schema.
    D-5 §5.5   Finalize node contract.
    D-6 §6     Renderer contract.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from slop_research_factory.types.enums import (
    NodeName,
    RunStatus,
    StepType,
    Verdict,
)
from slop_research_factory.types.hai_card import (
    DEFAULT_DISCLAIMER,
    HaiCard,
    ModelUsageRecord,
    ProcessSummary,
    VerificationSummary,
)

if TYPE_CHECKING:
    from slop_research_factory.config import FactoryConfig
    from slop_research_factory.seal.engine import SealEngine, VerificationReport
    from slop_research_factory.types.state import FactoryState
    from slop_research_factory.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 with milliseconds."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _serialize_with_version(obj: dict[str, Any], version: str = "0.1") -> dict[str, Any]:
    """Add ``_schema_version`` key per D-2 §15."""
    return {"_schema_version": version, **obj}


# ── Configuration overrides (D-2 §4) ────────────────────────────────


def compute_configuration_overrides(config: FactoryConfig) -> dict[str, Any]:
    """Return fields whose effective value differs from FactoryConfig defaults.

    Per D-2 §4: "only fields whose effective value differs from the
    default are recorded."
    """
    from slop_research_factory.config import FactoryConfig as FC

    defaults = FC()
    overrides: dict[str, Any] = {}
    for f in dataclasses.fields(FC):
        current = getattr(config, f.name)
        default = getattr(defaults, f.name)
        if current != default:
            if isinstance(current, Enum):
                overrides[f.name] = current.value
            elif isinstance(current, tuple):
                overrides[f.name] = list(current)
            else:
                overrides[f.name] = current
    return overrides


# ── Model usage aggregation ──────────────────────────────────────────

_ROLE_TO_NODE: dict[str, NodeName] = {
    "generator": NodeName.GENERATOR,
    "verifier": NodeName.VERIFICATION,
    "reviser": NodeName.REVISER,
}


def _aggregate_model_usage(messages: list[dict[str, Any]]) -> tuple[ModelUsageRecord, ...]:
    """Aggregate per-(model, role) token counts from state.messages."""
    buckets: dict[tuple[str, str], dict[str, int]] = {}
    for msg in messages:
        role = msg.get("role", "")
        model = msg.get("model", "")
        if not model or role not in _ROLE_TO_NODE:
            continue
        key = (model, role)
        if key not in buckets:
            buckets[key] = {"input_tokens": 0, "output_tokens": 0, "call_count": 0}
        tc = msg.get("token_counts", {})
        buckets[key]["input_tokens"] += tc.get("input", 0) or 0
        buckets[key]["output_tokens"] += tc.get("output", 0) or 0
        buckets[key]["call_count"] += 1

    records: list[ModelUsageRecord] = []
    for (model, role), counts in sorted(buckets.items()):
        records.append(
            ModelUsageRecord(
                model_id=model,
                node_name=_ROLE_TO_NODE[role],
                input_tokens=counts["input_tokens"],
                output_tokens=counts["output_tokens"],
                call_count=counts["call_count"],
            )
        )
    return tuple(records)


# ── Verification summary extraction ─────────────────────────────────


def _build_verification_summary(
    state: FactoryState,
    config: FactoryConfig,
) -> VerificationSummary:
    """Extract VerificationSummary from state.current_critique + citation_checks."""
    critique = state.current_critique or {}

    # Final verdict
    raw_verdict = critique.get("effective_verdict") or critique.get("verdict", "CORRECT")
    try:
        final_verdict = Verdict(raw_verdict)
    except ValueError:
        final_verdict = Verdict.CORRECT

    # Confidence
    verdict_confidence = float(critique.get("verdict_confidence", 0.0))

    # Tier reached
    # T3 if citation checking was enabled and checks were performed
    # T2 if LLM verification ran (always true if we got here)
    # T1 if only deterministic checks (not implemented in M2)
    citations_total = len(state.citation_checks)
    if config.enable_citation_checking and citations_total > 0:
        tier_reached = 3
    else:
        tier_reached = 2

    # Citations verified
    citations_verified = sum(
        1 for c in state.citation_checks if c.get("result") == "VERIFIED"
    )

    # Deterministic checks (T1 — not yet implemented in M2)
    deterministic_passed = 0
    deterministic_total = 0

    return VerificationSummary(
        final_verdict=final_verdict,
        verdict_confidence=verdict_confidence,
        tier_reached=tier_reached,
        deterministic_passed=deterministic_passed,
        deterministic_total=deterministic_total,
        citations_verified=citations_verified,
        citations_total=citations_total,
    )


# ── Manifest builder ────────────────────────────────────────────────


def build_manifest(
    *,
    state: FactoryState,
    config: FactoryConfig,
    report: VerificationReport,
    output_hash: str,
    hai_card_hash: str,
    configuration_overrides: dict[str, Any],
) -> dict[str, Any]:
    """Build the manifest.json content dict."""
    critique = state.current_critique or {}
    final_verdict = critique.get("effective_verdict") or critique.get("verdict", "CORRECT")

    model_topology = {
        "generator": config.generator_model,
        "verifier": config.verifier_model,
        "reviser": config.reviser_model,
    }

    # Total steps in the complete chain (including the MANIFEST we'll seal)
    total_steps_final = (state.step_index + 1) + 1  # current latest + MANIFEST

    manifest: dict[str, Any] = {
        "run_id": state.run_id,
        "status": RunStatus.COMPLETED.value,
        "created_at": state.created_at,
        "completed_at": _now_iso(),
        "final_verdict": final_verdict,
        "verdict_confidence": float(critique.get("verdict_confidence", 0.0)),
        "total_steps": total_steps_final,
        "chain_integrity_verified": report.chain_intact,
        "model_topology": model_topology,
        "configuration_overrides": configuration_overrides,
        "brief_title": state.brief.get("title_suggestion")
        or state.brief.get("thesis", "Untitled")[:80],
        "cycle_count": state.cycle_count,
        "rejection_count": state.rejection_count,
        "revision_count": state.revision_count,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "total_think_tokens": state.total_think_tokens,
        "total_estimated_cost_usd": round(state.total_estimated_cost_usd, 6),
        "total_wall_clock_seconds": round(state.total_wall_clock_seconds, 3),
        "output_hash": output_hash,
        "hai_card_hash": hai_card_hash,
        "latest_chain_hash": state.latest_hash,
    }
    return manifest


# ── Paper renderer ───────────────────────────────────────────────────


def render_paper(state: FactoryState) -> str:
    """Render the final paper.md with YAML front matter."""
    title = state.brief.get("title_suggestion") or state.brief.get("thesis", "Untitled")[:120]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    front_matter = (
        "---\n"
        f"title: \"{title}\"\n"
        f"generated_by: SLOP Research Factory v0.1\n"
        f"run_id: \"{state.run_id}\"\n"
        f"generated_at: \"{now}\"\n"
        f"status: ai_generated_unreviewed\n"
        "---\n\n"
    )

    draft = state.current_draft or ""
    return front_matter + draft


# ── Provenance report renderer ───────────────────────────────────────


def render_provenance_report(report: VerificationReport) -> str:
    """Render a human-readable provenance verification report."""
    lines: list[str] = [
        "# Provenance Verification Report\n",
        f"**Run ID:** `{report.run_id}`\n",
        f"**Chain Intact:** {'✅ Yes' if report.chain_intact else '❌ No'}\n",
        f"**Total Steps Verified:** {report.total_steps}\n",
    ]
    if report.first_error_index is not None:
        lines.append(f"**First Error at Step:** {report.first_error_index}\n")
    lines.append("\n## Step Details\n")
    lines.append("| Step | Type | Status | Errors |")
    lines.append("|------|------|--------|--------|")
    for step in report.steps:
        status = "✅" if step.ok else "❌"
        errors = "; ".join(step.errors) if step.errors else "—"
        lines.append(f"| {step.step_index} | {step.step_type} | {status} | {errors} |")
    lines.append("")
    return "\n".join(lines)


# ── Finalize node entry point ────────────────────────────────────────


async def finalize_node(
    state: FactoryState,
    *,
    seal_engine: SealEngine,
    workspace: WorkspaceManager,
) -> FactoryState:
    """Assemble terminal output artifacts and seal the MANIFEST.

    Args:
        state:       Current ``FactoryState`` — mutated in place.
        seal_engine: Engine instance scoped to the run.
        workspace:   Workspace I/O helper.

    Returns:
        The updated ``FactoryState`` with ``status == COMPLETED``.

    Raises:
        SealError: On any seal-engine failure.
        ValueError: If required state fields are missing.
    """
    from slop_research_factory.output.hai_card_renderer import render_hai_card
    from slop_research_factory.seal.helpers import seal_step

    config = state.config
    workspace.chain_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "[finalize] [%s] Starting finalization — %d cycles completed",
        state.run_id[:8],
        state.cycle_count,
    )

    if state.current_draft is None:
        raise ValueError("finalize_node requires state.current_draft to be set")

    # ── Step 1: Verify chain integrity ────────────────────────────
    report = await seal_engine.verify_chain()
    logger.info(
        "[finalize] [%s] Chain verification: %s (%d steps)",
        state.run_id[:8],
        "INTACT" if report.chain_intact else "BROKEN",
        report.total_steps,
    )

    # ── Step 2: Render paper.md ───────────────────────────────────
    paper_content = render_paper(state)
    paper_path = workspace.write_output_file("paper.md", paper_content)
    output_hash = await seal_engine.hash_file(str(paper_path))

    logger.info(
        "[finalize] [%s] paper.md written (%d bytes, hash %s…)",
        state.run_id[:8],
        len(paper_content),
        output_hash[:12],
    )

    # ── Step 3: Build and render HAI Card ─────────────────────────
    brief_hash = await seal_engine.hash_file(str(workspace.brief_path))

    hai_card = HaiCard(
        run_id=state.run_id,
        generated_at=datetime.now(UTC),
        brief_title=(
            state.brief.get("title_suggestion")
            or state.brief.get("thesis", "Untitled")[:80]
        ),
        brief_hash=brief_hash,
        models_used=_aggregate_model_usage(list(state.messages)),
        process=ProcessSummary(
            total_cycles=state.cycle_count,
            rejection_count=state.rejection_count,
            revision_count=state.revision_count,
        ),
        verification=_build_verification_summary(state, config),
        total_seals=report.total_steps,
        chain_integrity_verified=report.chain_intact,
        final_seal_hash=state.latest_hash,
        output_hash=output_hash,
        disclaimer=DEFAULT_DISCLAIMER,
        total_input_tokens=state.total_input_tokens,
        total_output_tokens=state.total_output_tokens,
        total_estimated_cost_usd=round(state.total_estimated_cost_usd, 6),
        output_license="CC BY 4.0",
        code_license="Apache-2.0",
    )

    hai_card_content = render_hai_card(hai_card)
    hai_card_path = workspace.write_output_file("hai_card.md", hai_card_content)
    hai_card_hash = await seal_engine.hash_file(str(hai_card_path))

    logger.info(
        "[finalize] [%s] hai_card.md written (hash %s…)",
        state.run_id[:8],
        hai_card_hash[:12],
    )

    # ── Step 4: Build manifest.json ───────────────────────────────
    configuration_overrides = compute_configuration_overrides(config)

    manifest_data = build_manifest(
        state=state,
        config=config,
        report=report,
        output_hash=output_hash,
        hai_card_hash=hai_card_hash,
        configuration_overrides=configuration_overrides,
    )

    manifest_content = json.dumps(
        _serialize_with_version(manifest_data),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    manifest_path = workspace.write_output_file("manifest.json", manifest_content + "\n")
    manifest_hash = await seal_engine.hash_file(str(manifest_path))

    logger.info(
        "[finalize] [%s] manifest.json written (hash %s…)",
        state.run_id[:8],
        manifest_hash[:12],
    )

    # ── Step 5: Render provenance report ──────────────────────────
    report_content = render_provenance_report(report)
    report_path = workspace.write_output_file("provenance_report.md", report_content)
    report_hash = await seal_engine.hash_file(str(report_path))

    # ── Step 6: Seal MANIFEST ─────────────────────────────────────
    critique = state.current_critique or {}
    final_verdict = critique.get("effective_verdict") or critique.get("verdict", "CORRECT")

    model_topology = {
        "generator": config.generator_model,
        "verifier": config.verifier_model,
        "reviser": config.reviser_model,
    }

    manifest_meta = {
        "total_steps": state.step_index + 2,  # current + MANIFEST itself
        "final_verdict": final_verdict,
        "manifest_hash": manifest_hash,
        "hai_card_hash": hai_card_hash,
        "report_hash": report_hash,
        "model_topology": model_topology,
    }

    content_file_paths = [
        workspace.relative(paper_path),
        workspace.relative(hai_card_path),
        workspace.relative(manifest_path),
        workspace.relative(report_path),
    ]

    state, manifest_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.MANIFEST,
        content_file_paths=content_file_paths,
        metadata=manifest_meta,
    )

    logger.info(
        "[finalize] [%s] MANIFEST sealed (step %d, hash %s…)",
        state.run_id[:8],
        state.step_index,
        state.latest_hash[:12],
    )

    # ── Step 7: State update → COMPLETED ──────────────────────────
    state.status = RunStatus.COMPLETED
    state.updated_at = _now_iso()
    workspace.write_state(state)

    logger.info(
        "[finalize] [%s] Run COMPLETED — %d total seals, cost $%.4f",
        state.run_id[:8],
        state.step_index + 1,
        state.total_estimated_cost_usd,
    )

    return state