# src/slop_research_factory/nodes/generator_node.py

"""
Generator node — Implementation Step 6 (D-0 §13).

Executes the four-phase node protocol (D-5 §4) for the Generator:

  Phase 1  PRE-SEAL    Render & seal the prompt intent.
  Phase 2  INFERENCE   Call the Generator LLM; capture raw bytes first.
  Phase 3  POST-SEAL   Write artefacts; seal the outcome.
  Phase 4  STATE UPDATE Mutate FactoryState; persist checkpoint.

Primary specification references:
  D-3 §3   — Generator system prompt and user-message template.
  D-5 §5.2 — Generator seal sequence and metadata schemas.
  D-5 §6   — Raw API response sealing (bytes before parse).
  D-3 §7   — NO_OUTPUT detection.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from slop_research_factory.llm.no_output import detect_no_output
from slop_research_factory.llm.think_parser import parse_think_tokens
from slop_research_factory.prompts.generator_prompt import (
    GENERATOR_PROMPT_VERSION,
    render_generator_prompt,
)
from slop_research_factory.types.enums import RunStatus, StepType
from slop_research_factory.types.inference import InferenceRecord

if TYPE_CHECKING:
    from slop_research_factory.llm.client import LLMClient, LLMResponse
    from slop_research_factory.seal.engine import SealEngine
    from slop_research_factory.types.state import FactoryState
    from slop_research_factory.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------

# Helpers

# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """UTC timestamp in ISO-8601 with milliseconds (D-2 §13)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _cycle_prefix(cycle: int) -> str:
    """``cycle_01``, ``cycle_02``, … (D-2 §13 naming contract)."""
    return f"cycle_{cycle:02d}"


def _serialize_with_version(obj: dict, version: str = "0.1") -> dict:
    """Add ``_schema_version`` key per D-2 §15."""
    return {"_schema_version": version, **obj}


# ---------------------------------------------------------------------------

# Generator node entry point

# ---------------------------------------------------------------------------

async def generator_node(
    state: FactoryState,
    *,
    seal_engine: SealEngine,
    llm_client: LLMClient,
    workspace: WorkspaceManager,
) -> FactoryState:
    """Run the Generator node with full provenance sealing.

    Args:
        state:       Current ``FactoryState`` — mutated in place.
        seal_engine: Async wrapper around ``slop-cli`` (D-5 §3).
        llm_client:  LiteLLM async wrapper (Step 4).
        workspace:   Workspace I/O helper (Step 2).

    Returns:
        The updated ``FactoryState``.  If NO_OUTPUT was detected the
        ``status`` field is set to ``RunStatus.NO_OUTPUT`` and the
        orchestrator MUST NOT route to the Verifier.

    Raises:
        SealError: On any seal-engine failure (results in FAILED status
                   at the orchestrator level per D-5 §13).
    """
    from slop_research_factory.seal.helpers import seal_step  # Step 3

    config = state.config
    cycle = state.cycle_count + 1
    prefix = _cycle_prefix(cycle)
    chain_dir = str(workspace.run_dir / "chain")

    logger.info(
        "[generator] [%s] Starting Generator — cycle %d, model %s",
        state.run_id[:8],
        cycle,
        config.generator_model,
    )

    # ── Phase 1: PRE-SEAL ─────────────────────────────────────────────
    system_prompt, user_message, audit_text = render_generator_prompt(
        state.brief, config,
    )

    prompt_path = workspace.drafts_path(f"{prefix}_generator_prompt.md")
    workspace.write_text(prompt_path, audit_text)

    prompt_hash = await seal_engine.hash_file(str(prompt_path))

    pre_meta = {
        "prompt_hash": prompt_hash,
        "model": config.generator_model,
        "cycle": cycle,
        "prompt_version": GENERATOR_PROMPT_VERSION,
    }
    state, _pre_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.PRE_GENERATOR,
        content_file_paths=[workspace.relative(prompt_path)],
        metadata=pre_meta,
        chain_dir=chain_dir,
    )

    logger.info(
        "[generator] [%s] PRE-SEAL complete (step %d, hash %s…)",
        state.run_id[:8],
        state.step_index,
        state.latest_hash[:12],
    )

    # ── Phase 2: INFERENCE ─────────────────────────────────────────────
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    ts_start = _now_iso()
    wall_start = time.monotonic()

    response: LLMResponse = await llm_client.complete(
        model=config.generator_model,
        messages=messages,
    )

    wall_end = time.monotonic()
    ts_end = _now_iso()
    duration_s = wall_end - wall_start

    logger.info(
        "[generator] [%s] Response received (%d output tokens, %.1fs)",
        state.run_id[:8],
        response.output_tokens,
        duration_s,
    )

    # ── Raw response sealing (D-5 §6) ─────────────────────────────────
    # Write raw bytes BEFORE any parsing.
    raw_bytes = json.dumps(
        response.raw_response,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    response_path = workspace.drafts_path(
        f"{prefix}_generator_response.json",
    )
    workspace.write_bytes(response_path, raw_bytes)

    raw_response_hash = await seal_engine.hash_file(str(response_path))

    # Parse think trace and final output AFTER writing raw bytes.
    think_trace, final_output = parse_think_tokens(response.content)

    # Write final output.
    output_path = workspace.drafts_path(f"{prefix}_generator_output.md")
    workspace.write_text(output_path, final_output)

    # Write think trace (if captured and present).
    think_path: Path | None = None
    if config.capture_think_tokens and think_trace is not None:
        think_path = workspace.drafts_path(f"{prefix}_generator_think.md")
        workspace.write_text(think_path, think_trace)

    # ── NO_OUTPUT detection (D-3 §7) ──────────────────────────────────
    is_no_output, no_output_explanation = detect_no_output(final_output)
    if is_no_output:
        logger.info(
            "[generator] [%s] NO_OUTPUT declared: %s",
            state.run_id[:8],
            (no_output_explanation or "")[:120],
        )

    # ── Phase 3: POST-SEAL ─────────────────────────────────────────────
    # Compute individual file hashes for metadata.
    draft_hash = await seal_engine.hash_file(str(output_path))
    think_hash: str | None = None
    if think_path is not None:
        think_hash = await seal_engine.hash_file(str(think_path))

    # Build InferenceRecord (D-2 §9).
    inference_record = InferenceRecord(
        run_id=state.run_id,
        step_index=state.step_index + 1,  # will match POST step
        role="generator",
        model=config.generator_model,
        timestamp_start=ts_start,
        timestamp_end=ts_end,
        duration_seconds=round(duration_s, 3),
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        think_tokens=response.think_tokens,
        prompt_hash=prompt_hash,
        response_hash=raw_response_hash,
        response_body_hash=draft_hash,
        think_trace_hash=think_hash,
        api_provider=response.api_provider,
        api_response_id=response.api_response_id,
        retries=getattr(response, "retries", 0),
        error=None,
        sampling_params=getattr(response, "sampling_params", {}),
    )

    record_path = workspace.drafts_path(f"{prefix}_generator_record.json")
    workspace.write_json(
        record_path,
        _serialize_with_version(asdict(inference_record)),
    )

    # Collect content files covered by this seal (D-5 §7, D-5 §16 #18).
    post_content_files = [
        workspace.relative(output_path),
        workspace.relative(response_path),
        workspace.relative(record_path),
    ]
    if think_path is not None:
        post_content_files.append(workspace.relative(think_path))

    post_meta = {
        "draft_hash": draft_hash,
        "think_hash": think_hash,
        "raw_response_hash": raw_response_hash,
        "model": config.generator_model,
        "token_counts": {
            "input": response.input_tokens,
            "output": response.output_tokens,
            "think": response.think_tokens,
        },
        "cycle": cycle,
        "api_response_id": response.api_response_id,
        "prompt_version": GENERATOR_PROMPT_VERSION,
        "is_no_output": is_no_output,
    }

    state, _post_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.POST_GENERATOR,
        content_file_paths=post_content_files,
        metadata=post_meta,
        chain_dir=chain_dir,
    )

    logger.info(
        "[generator] [%s] POST-SEAL complete (step %d, hash %s…)",
        state.run_id[:8],
        state.step_index,
        state.latest_hash[:12],
    )

    # ── Phase 4: STATE UPDATE ──────────────────────────────────────────
    state.current_draft = final_output
    state.current_think_trace = think_trace

    state.total_input_tokens += response.input_tokens
    state.total_output_tokens += response.output_tokens
    state.total_think_tokens += response.think_tokens or 0
    state.total_wall_clock_seconds += duration_s
    # Cost estimate (rough; exact pricing lives in D-9 §12).
    state.total_estimated_cost_usd += _estimate_cost(
        config.generator_model,
        response.input_tokens,
        response.output_tokens,
    )

    state.messages.append(
        {
            "role": "generator",
            "step_index": state.step_index,
            "timestamp": ts_end,
            "model": config.generator_model,
            "prompt_hash": prompt_hash,
            "response_hash": raw_response_hash,
            "token_counts": {
                "input": response.input_tokens,
                "output": response.output_tokens,
                "think": response.think_tokens,
            },
        }
    )

    state.cycle_count = cycle

    if is_no_output:
        state.status = RunStatus.NO_OUTPUT

    state.updated_at = _now_iso()

    # Atomic checkpoint (D-2 §6 serialization contract).
    workspace.write_state_atomic(state)

    logger.info(
        "[generator] [%s] State updated — draft %d words, status %s",
        state.run_id[:8],
        len(final_output.split()),
        state.status.value,
    )

    return state


# ---------------------------------------------------------------------------

# Rough cost estimation (D-9 §12.1 pricing table, April 2026)

# ---------------------------------------------------------------------------

_COST_TABLE: dict[str, tuple[float, float]] = {
    # model_substring → ($/M input, $/M output)
    "deepseek-r1": (0.55, 2.19),
    "gemini-2.5-flash": (0.15, 0.60),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return a rough USD cost estimate. Falls back to zero if unknown."""
    for key, (inp_rate, out_rate) in _COST_TABLE.items():
        if key in model:
            return (
                input_tokens * inp_rate / 1_000_000
                + output_tokens * out_rate / 1_000_000
            )
    return 0.0