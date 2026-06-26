# src/slop_research_factory/nodes/reviser_node.py

"""Reviser node.4.

Mirrors the four-phase Generator protocol with two key differences:

1. The PRE-seal metadata embeds ``critique_hash`` so the chain links
   the revision to the precise critique that triggered it.
2. The user message branches on ``mode``: ``targeted_repair`` for
   FIXABLE inputs, ``full_rewrite`` for WRONG inputs.

The node remains a pure ``LLMClient`` consumer (no Instructor); it
emits free-form Markdown like the Generator.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slop_research_factory.engine.routing import (
    FULL_REWRITE,
    TARGETED_REPAIR,
)
from slop_research_factory.llm.no_output import detect_no_output
from slop_research_factory.llm.think_parser import parse_think_tokens
from slop_research_factory.prompts.reviser_prompt import (
    REVISER_PROMPT_VERSION,
    ReviserMode,
    render_reviser_prompt,
)
from slop_research_factory.types.enums import RunStatus, StepType
from slop_research_factory.types.inference import InferenceRecord

if TYPE_CHECKING:
    from slop_research_factory.llm.client import LLMClient, LLMResponse
    from slop_research_factory.seal.engine import SealEngine
    from slop_research_factory.types.state import FactoryState
    from slop_research_factory.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _cycle_prefix(cycle: int) -> str:
    return f"cycle_{cycle:02d}"


def _serialize_with_version(obj: dict[str, Any], version: str = "0.1") -> dict[str, Any]:
    return {"_schema_version": version, **obj}


# ── Reviser node entry point ─────────────────────────────


async def reviser_node(  # noqa: PLR0915 - phased protocol is intentionally explicit
    state: FactoryState,
    *,
    seal_engine: SealEngine,
    llm_client: LLMClient,
    workspace: WorkspaceManager,
    mode: ReviserMode,
) -> FactoryState:
    """Run one Reviser cycle.

    Args:
        state: Current :class:`FactoryState` (mutated in place).
            Must have ``current_critique`` populated by the upstream
            Verifier and a non-empty ``current_draft``.
        seal_engine: Engine instance scoped to the run.
        llm_client: Generator-style LLM client (raw completion).
        workspace: Workspace I/O helper.
        mode: ``"targeted_repair"`` or ``"full_rewrite"``. Wired by
            the orchestrator from
            :class:`~slop_research_factory.engine.routing.RoutingDecision`.

    Returns:
        The updated ``FactoryState``. ``state.current_draft`` holds the
        revised text. NO_OUTPUT declarations set
        :data:`RunStatus.NO_OUTPUT`.
    """
    from slop_research_factory.seal.helpers import seal_step

    if state.current_draft is None:
        raise ValueError("reviser_node requires state.current_draft to be set")
    if state.current_critique is None:
        raise ValueError("reviser_node requires state.current_critique to be set")
    if mode not in {TARGETED_REPAIR, FULL_REWRITE}:
        raise ValueError(f"unknown reviser mode: {mode!r}")

    config = state.config
    cycle = state.cycle_count + 1
    prefix = _cycle_prefix(cycle)
    workspace.chain_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "[reviser] [%s] Starting Reviser — cycle %d, mode %s, model %s",
        state.run_id[:8],
        cycle,
        mode,
        config.reviser_model,
    )

    # ── Phase 1: PRE-SEAL ────────────────────────────────────────
    critique_hash = state.current_critique.get("critique_hash")
    verdict = state.current_critique.get("verdict")
    if not critique_hash:
        raise ValueError(
            "reviser_node requires state.current_critique['critique_hash'] "
            "(populated by verifier_node POST-seal)",
        )

    system_prompt, user_message, audit_text = render_reviser_prompt(
        brief=state.brief,
        previous_draft=state.current_draft,
        verifier_output=state.current_critique,
        critique_seal_hash=critique_hash,
        cycle_count=cycle,
        config=config,
        state=state,
        mode=mode,
    )

    prompt_path = workspace.drafts_path(f"{prefix}_reviser_prompt.md")
    workspace.write_text(prompt_path, audit_text)
    prompt_hash = await seal_engine.hash_file(str(prompt_path))

    pre_meta = {
        "prompt_hash": prompt_hash,
        "critique_hash": critique_hash,
        "model": config.reviser_model,
        "cycle": cycle,
        "mode": mode,
        "verdict": verdict,
        "prompt_version": REVISER_PROMPT_VERSION,
    }
    state, _pre_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.PRE_REVISER,
        content_file_paths=[workspace.relative(prompt_path)],
        metadata=pre_meta,
    )

    logger.info(
        "[reviser] [%s] PRE-SEAL complete (step %d)",
        state.run_id[:8],
        state.step_index,
    )

    # ── Phase 2: INFERENCE ───────────────────────────────────────
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    ts_start = _now_iso()
    wall_start = time.monotonic()

    logger.info(
        "[reviser] [%s] Awaiting LLM response (model=%s)…",
        state.run_id[:8],
        config.reviser_model,
    )
    response: LLMResponse = await llm_client.complete(
        model=config.reviser_model,
        messages=messages,
    )

    wall_end = time.monotonic()
    ts_end = _now_iso()
    duration_s = wall_end - wall_start

    raw_bytes = json.dumps(
        response.raw_response,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    response_path = workspace.drafts_path(f"{prefix}_reviser_response.json")
    workspace.write_bytes(response_path, raw_bytes)
    raw_response_hash = await seal_engine.hash_file(str(response_path))

    think_trace, final_output = parse_think_tokens(response.content)
    output_path = workspace.drafts_path(f"{prefix}_reviser_output.md")
    workspace.write_text(output_path, final_output)

    think_path: Path | None = None
    if config.capture_think_tokens and think_trace is not None:
        think_path = workspace.drafts_path(f"{prefix}_reviser_think.md")
        workspace.write_text(think_path, think_trace)

    is_no_output, no_output_explanation = detect_no_output(final_output)
    if is_no_output:
        logger.info(
            "[reviser] [%s] NO_OUTPUT declared: %s",
            state.run_id[:8],
            (no_output_explanation or "")[:120],
        )

    # ── Phase 3: POST-SEAL ───────────────────────────────────────
    draft_hash = await seal_engine.hash_file(str(output_path))
    think_hash: str | None = None
    if think_path is not None:
        think_hash = await seal_engine.hash_file(str(think_path))

    inference_record = InferenceRecord(
        run_id=state.run_id,
        step_index=state.step_index + 1,
        role="reviser",
        model=config.reviser_model,
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

    record_path = workspace.drafts_path(f"{prefix}_reviser_record.json")
    workspace.write_json(
        record_path,
        _serialize_with_version(asdict(inference_record)),
    )

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
        "model": config.reviser_model,
        "token_counts": {
            "input": response.input_tokens,
            "output": response.output_tokens,
            "think": response.think_tokens,
        },
        "cycle": cycle,
        "mode": mode,
        "critique_hash": critique_hash,
        "api_response_id": response.api_response_id,
        "prompt_version": REVISER_PROMPT_VERSION,
        "is_no_output": is_no_output,
    }
    state, _post_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.POST_REVISER,
        content_file_paths=post_content_files,
        metadata=post_meta,
    )

    logger.info(
        "[reviser] [%s] POST-SEAL complete (step %d)",
        state.run_id[:8],
        state.step_index,
    )

    # ── Phase 4: STATE UPDATE ────────────────────────────────────
    state.current_draft = final_output
    state.current_think_trace = think_trace

    state.total_input_tokens += response.input_tokens
    state.total_output_tokens += response.output_tokens
    if response.think_tokens is not None:
        state.total_think_tokens += response.think_tokens
    state.total_wall_clock_seconds += duration_s

    state.messages.append(
        {
            "role": "reviser",
            "step_index": state.step_index,
            "timestamp": ts_end,
            "model": config.reviser_model,
            "mode": mode,
            "prompt_hash": prompt_hash,
            "response_hash": raw_response_hash,
            "critique_hash": critique_hash,
            "token_counts": {
                "input": response.input_tokens,
                "output": response.output_tokens,
                "think": response.think_tokens,
            },
        },
    )

    state.cycle_count = cycle

    if is_no_output:
        state.status = RunStatus.NO_OUTPUT

    state.updated_at = _now_iso()
    workspace.write_state(state)

    logger.info(
        "[reviser] [%s] Revised draft ready — %d words, mode=%s, %s verdict",
        state.run_id[:8],
        len(final_output.split()),
        mode,
        verdict or "?",
    )

    return state
