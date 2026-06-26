# src/slop_research_factory/nodes/verifier_node.py

"""Verifier node.3.

Executes the seven-phase Verifier protocol:

    1. Deterministic pre-checks (no seals; deferred to a future
       milestone).
    2. Citation extraction (no seal).
    3. Tool-grounded citation checks (1+ TOOL_CALL seals each).
    4. PRE_VERIFIER seal.
    5. Instructor structured LLM call.
    6. Post-processing (verdict composition + demotion).
    7. POST_VERIFIER seal.
    8. State update + checkpoint.

Test seams:
    * ``citation_check_client``: any object satisfying
      :class:`~slop_research_factory.tools.CitationCheckClient`. Tests
      inject :class:`~slop_research_factory.tools.CannedCitationCheckClient`.
    * ``structured_complete``: optional callable matching
      :func:`complete_structured`'s signature. When ``None``, the
      production Instructor client is used.

"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

from slop_research_factory.citations.extractor import extract_citations
from slop_research_factory.engine.routing import (
    apply_routing_deltas,
    compute_effective_verdict,
    route_after_verification,
)
from slop_research_factory.prompts.verifier_prompt import (
    VERIFIER_PROMPT_VERSION,
    render_verifier_prompt,
)
from slop_research_factory.types.enums import (
    CitationCheckResult,
    StepType,
)
from slop_research_factory.types.tool_types import (
    CrossrefQuery,
    SemanticScholarQuery,
)
from slop_research_factory.types.verifier_output import (
    CitationCheckEntry,
    CitationEntry,
    VerifierOutput,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

    from slop_research_factory.llm.client import LLMResponse
    from slop_research_factory.seal.engine import SealEngine
    from slop_research_factory.tools.protocol import (
        CitationCheckClient,
        ToolInvocation,
    )
    from slop_research_factory.types.state import FactoryState
    from slop_research_factory.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="BaseModel")

StructuredCompleteFn = Callable[
    ...,
    Coroutine[Any, Any, tuple[Any, "LLMResponse"]],
]


# ── Helpers ──────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _cycle_prefix(cycle: int) -> str:
    return f"cycle_{cycle:02d}"


def _serialize_with_version(obj: dict[str, Any], version: str = "0.1") -> dict[str, Any]:
    return {"_schema_version": version, **obj}


def _query_summary(query: Any) -> str:
    """Compact human-readable query summary for TOOL_CALL metadata."""
    if isinstance(query, CrossrefQuery):
        return query.doi or query.query_title or query.query_author or "?"
    if isinstance(query, SemanticScholarQuery):
        return query.paper_id or query.query_title or "?"
    return str(query)


# Maximum title / free-text length passed to Semantic Scholar title search.
_MAX_S2_QUERY_TEXT_LEN = 512


def _semantic_scholar_query_from_citation(citation: CitationEntry) -> SemanticScholarQuery | None:
    """Build an S2 graph lookup when we have an id or searchable text.

    Regex extraction often yields ``citation_text`` without a structured
    ``claimed_title``; fall back to stripped raw text so we never construct
    :class:`SemanticScholarQuery` with neither ``paper_id`` nor ``query_title``.
    """
    if citation.doi and citation.doi.strip():
        return SemanticScholarQuery(paper_id=f"DOI:{citation.doi.strip()}")
    if citation.arxiv_id and citation.arxiv_id.strip():
        return SemanticScholarQuery(paper_id=f"arXiv:{citation.arxiv_id.strip()}")
    title = (citation.claimed_title or "").strip() or None
    if title is None:
        raw = (citation.citation_text or "").strip()
        if raw:
            title = raw[:_MAX_S2_QUERY_TEXT_LEN]
    if not title:
        return None
    return SemanticScholarQuery(query_title=title[:_MAX_S2_QUERY_TEXT_LEN])


# ── Verdict composition ──────────────────────────────────


def _aggregate_citation_check(
    citation: CitationEntry,
    crossref_inv: ToolInvocation | None,
    s2_inv: ToolInvocation | None,
) -> CitationCheckEntry:
    """Combine per-source results into a single :class:`CitationCheckEntry`.

    Lightweight rules for M2:

    * **VERIFIED** — at least one source returned ``found=True``.
    * **NOT_FOUND** — every probed source replied with ``found=False``.
    * **INCONCLUSIVE** — every probed source raised :class:`ToolError`.

    More nuanced detection (METADATA_MISMATCH) lives behind the LLM
    extractor in M3.
    """
    sources: list[str] = []
    crossref_match: dict[str, Any] | None = None
    s2_match: dict[str, Any] | None = None
    any_found = False
    any_error = False
    notes_parts: list[str] = []

    if crossref_inv is not None:
        sources.append("crossref")
        if crossref_inv.status == "ok":
            any_found = True
            crossref_match = (
                asdict(crossref_inv.result)
                if hasattr(crossref_inv.result, "__dataclass_fields__")
                else None
            )
        elif crossref_inv.status == "error":
            any_error = True
            notes_parts.append(f"crossref error: {crossref_inv.error}")

    if s2_inv is not None:
        sources.append("semantic_scholar")
        if s2_inv.status == "ok":
            any_found = True
            s2_match = (
                asdict(s2_inv.result) if hasattr(s2_inv.result, "__dataclass_fields__") else None
            )
        elif s2_inv.status == "error":
            any_error = True
            notes_parts.append(f"s2 error: {s2_inv.error}")

    if not sources:
        return CitationCheckEntry(
            citation=citation,
            result=CitationCheckResult.INCONCLUSIVE,
            checked_sources=[],
            crossref_match=None,
            semantic_scholar_match=None,
            tavily_response=None,
            confidence=0.0,
            notes=(
                "; ".join(notes_parts)
                if notes_parts
                else "no external citation lookup performed (missing identifiers)"
            ),
        )

    if any_found:
        result = CitationCheckResult.VERIFIED
        confidence = 0.95
    elif any_error and not sources:
        result = CitationCheckResult.INCONCLUSIVE
        confidence = 0.0
    elif any_error:
        result = CitationCheckResult.INCONCLUSIVE
        confidence = 0.2
    else:
        result = CitationCheckResult.NOT_FOUND
        confidence = 0.9

    return CitationCheckEntry(
        citation=citation,
        result=result,
        checked_sources=sources,
        crossref_match=crossref_match,
        semantic_scholar_match=s2_match,
        tavily_response=None,
        confidence=confidence,
        notes="; ".join(notes_parts) or None,
    )


def _compose_verifier_output(
    raw: VerifierOutput,
    *,
    citation_checks: list[CitationCheckEntry],
) -> VerifierOutput:
    """Apply confidence composition rules.

    M2 implementation:

    * If any tool-grounded check is :data:`CitationCheckResult.NOT_FOUND`,
      cap ``confidence_citation_accuracy`` at ``0.4``.
    * ``confidence_novelty_plausibility`` is capped at ``0.5``.

    Returns a fresh :class:`VerifierOutput`; the input model is not
    mutated (``BaseModel.model_copy(update=...)``).
    """
    updates: dict[str, Any] = {}
    if citation_checks and any(c.result == CitationCheckResult.NOT_FOUND for c in citation_checks):
        updates["confidence_citation_accuracy"] = min(
            raw.confidence_citation_accuracy,
            0.4,
        )
    updates["confidence_novelty_plausibility"] = min(
        raw.confidence_novelty_plausibility,
        0.5,
    )
    if not updates:
        return raw
    return raw.model_copy(update=updates)


# ── Verifier node entry point ────────────────────────────


async def verifier_node(  # noqa: PLR0915 - phased protocol is intentionally explicit
    state: FactoryState,
    *,
    seal_engine: SealEngine,
    workspace: WorkspaceManager,
    citation_check_client: CitationCheckClient,
    structured_complete: StructuredCompleteFn | None = None,
) -> FactoryState:
    """Run one Verifier cycle on ``state.current_draft``.

    Args:
        state: Current :class:`FactoryState` (mutated in place).
        seal_engine: Engine instance scoped to the run.
        workspace: Workspace I/O helper.
        citation_check_client: Tool client (canned or HTTP-backed).
        structured_complete: Override for the structured LLM call.
            Tests inject a deterministic callable; production code
            leaves this ``None`` so the Instructor / LiteLLM stack is
            used.

    Returns:
        The updated ``FactoryState``. ``state.current_critique`` is
        populated with the composed verdict on success; the caller
        runs :func:`route_after_verification` next.
    """
    from slop_research_factory.llm.structured import complete_structured
    from slop_research_factory.seal.helpers import seal_step

    config = state.config
    cycle = state.cycle_count
    prefix = _cycle_prefix(cycle)
    workspace.chain_dir.mkdir(parents=True, exist_ok=True)

    if state.current_draft is None:
        msg = "verifier_node requires state.current_draft to be set"
        raise ValueError(msg)
    current_draft: str = state.current_draft

    logger.info(
        "[verifier] [%s] Starting Verifier — cycle %d, model %s",
        state.run_id[:8],
        cycle,
        config.verifier_model,
    )

    # ── Phase 1: deterministic pre-checks (skipped in M2) ──────────
    # ── Phase 2: citation extraction (no seal) ────────────────────
    extracted = (
        extract_citations(current_draft, mode="regex") if config.enable_citation_checking else []
    )

    citations_path = workspace.citations_path(f"{prefix}_extracted.json")
    workspace.write_json(
        citations_path,
        _serialize_with_version(
            {"citations": [c.model_dump() for c in extracted]},
        ),
    )

    logger.info(
        "[verifier] [%s] Phase 2: extracted %d citation(s)",
        state.run_id[:8],
        len(extracted),
    )

    # ── Phase 3: tool-grounded citation checks (TOOL_CALL seals) ──
    citation_checks: list[CitationCheckEntry] = []
    tool_call_steps: list[int] = []

    sources = set(config.citation_check_sources)

    for idx, citation in enumerate(extracted):
        cr_invocation: ToolInvocation | None = None
        s2_invocation: ToolInvocation | None = None

        if config.enable_citation_checking and "crossref" in sources and citation.doi:
            cr_invocation = await citation_check_client.crossref(
                CrossrefQuery(doi=citation.doi),
            )
            tool_path = workspace.tools_path(f"crossref_{cycle:02d}_{idx}.json")
            workspace.write_json(
                tool_path,
                _serialize_with_version(cr_invocation.to_dict()),
            )
            tool_meta = {
                "tool_name": "crossref",
                "query": _query_summary(cr_invocation.query),
                "response_hash": await seal_engine.hash_file(str(tool_path)),
                "parent_step": None,
                "elapsed_seconds": cr_invocation.elapsed_seconds,
                "result_status": cr_invocation.status,
                "cycle": cycle,
            }
            state, _r = await seal_step(
                seal_engine=seal_engine,
                state=state,
                step_type=StepType.TOOL_CALL,
                content_file_paths=[workspace.relative(tool_path)],
                metadata=tool_meta,
            )
            tool_call_steps.append(state.step_index)

        if config.enable_citation_checking and "semantic_scholar" in sources:
            s2_query = _semantic_scholar_query_from_citation(citation)
            if s2_query is None:
                logger.debug(
                    "[verifier] [%s] Skipping Semantic Scholar for citation %d "
                    "(no doi, arxiv id, or query text)",
                    state.run_id[:8],
                    idx,
                )
            else:
                s2_invocation = await citation_check_client.semantic_scholar(s2_query)
                tool_path = workspace.tools_path(f"semantic_scholar_{cycle:02d}_{idx}.json")
                workspace.write_json(
                    tool_path,
                    _serialize_with_version(s2_invocation.to_dict()),
                )
                tool_meta = {
                    "tool_name": "semantic_scholar",
                    "query": _query_summary(s2_invocation.query),
                    "response_hash": await seal_engine.hash_file(str(tool_path)),
                    "parent_step": None,
                    "elapsed_seconds": s2_invocation.elapsed_seconds,
                    "result_status": s2_invocation.status,
                    "cycle": cycle,
                }
                state, _r = await seal_step(
                    seal_engine=seal_engine,
                    state=state,
                    step_type=StepType.TOOL_CALL,
                    content_file_paths=[workspace.relative(tool_path)],
                    metadata=tool_meta,
                )
                tool_call_steps.append(state.step_index)

        check = _aggregate_citation_check(citation, cr_invocation, s2_invocation)
        citation_checks.append(check)

    # ── Phase 4: PRE-SEAL verifier intent ─────────────────────────
    citation_check_dicts = [c.model_dump() for c in citation_checks]

    previous_verdict: str | None = None
    previous_critique_summary: str | None = None
    if state.current_critique:
        previous_verdict = state.current_critique.get("verdict")
        previous_critique_summary = state.current_critique.get("critique_summary")

    system_prompt, user_message, audit_text = render_verifier_prompt(
        brief=state.brief,
        current_draft=current_draft,
        config=config,
        cycle_count=cycle,
        previous_verdict=previous_verdict,
        previous_critique_summary=previous_critique_summary,
        citation_check_results=citation_check_dicts,
    )

    prompt_path = workspace.drafts_path(f"{prefix}_verifier_prompt.md")
    workspace.write_text(prompt_path, audit_text)

    draft_path = workspace.drafts_path(f"{prefix}_verifier_input_draft.md")
    workspace.write_text(draft_path, current_draft)

    prompt_hash = await seal_engine.hash_file(str(prompt_path))
    draft_hash = await seal_engine.hash_file(str(draft_path))

    pre_meta = {
        "prompt_hash": prompt_hash,
        "model": config.verifier_model,
        "cycle": cycle,
        "num_citations_checked": len(citation_checks),
        "tool_call_steps": tool_call_steps,
        "draft_hash": draft_hash,
        "draft_version": cycle,
        "prompt_version": VERIFIER_PROMPT_VERSION,
    }
    state, _pre_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.PRE_VERIFIER,
        content_file_paths=[
            workspace.relative(prompt_path),
            workspace.relative(draft_path),
        ],
        metadata=pre_meta,
    )

    logger.info(
        "[verifier] [%s] PRE-SEAL complete (step %d, %d tool calls)",
        state.run_id[:8],
        state.step_index,
        len(tool_call_steps),
    )

    # ── Phase 5: structured LLM call ─────────────────────────────
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    ts_start = _now_iso()
    wall_start = time.monotonic()

    runner = structured_complete or complete_structured
    parsed_raw, llm_response = await runner(
        model=config.verifier_model,
        messages=messages,
        response_model=VerifierOutput,
    )
    parsed = cast(VerifierOutput, parsed_raw)

    wall_end = time.monotonic()
    ts_end = _now_iso()
    duration_s = wall_end - wall_start

    # ── Raw response ─────────────────
    raw_bytes = json.dumps(
        llm_response.raw_response,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    response_path = workspace.drafts_path(f"{prefix}_verifier_response.json")
    workspace.write_bytes(response_path, raw_bytes)
    raw_response_hash = await seal_engine.hash_file(str(response_path))

    # ── Phase 6: post-processing ─────────────────────────────────
    composed = _compose_verifier_output(parsed, citation_checks=citation_checks)
    effective_verdict = compute_effective_verdict(
        composed.verdict,
        composed.verdict_confidence,
        config.verifier_confidence_threshold,
    )

    # Canonicalised JSON dumps for sealing.
    raw_output_path = workspace.drafts_path(
        f"{prefix}_verifier_output_raw.json",
    )
    composed_output_path = workspace.drafts_path(
        f"{prefix}_verifier_output.json",
    )
    workspace.write_json(
        raw_output_path,
        _serialize_with_version(parsed.model_dump(mode="json")),
    )
    workspace.write_json(
        composed_output_path,
        _serialize_with_version(composed.model_dump(mode="json")),
    )
    raw_critique_hash = await seal_engine.hash_file(str(raw_output_path))
    composed_critique_hash = await seal_engine.hash_file(str(composed_output_path))

    record_path = workspace.drafts_path(f"{prefix}_verifier_record.json")
    workspace.write_json(
        record_path,
        _serialize_with_version(
            {
                "run_id": state.run_id,
                "step_index": state.step_index + 1,
                "role": "verifier",
                "model": config.verifier_model,
                "timestamp_start": ts_start,
                "timestamp_end": ts_end,
                "duration_seconds": round(duration_s, 3),
                "input_tokens": llm_response.input_tokens,
                "output_tokens": llm_response.output_tokens,
                "think_tokens": llm_response.think_tokens,
                "prompt_hash": prompt_hash,
                "raw_response_hash": raw_response_hash,
                "raw_critique_hash": raw_critique_hash,
                "composed_critique_hash": composed_critique_hash,
                "raw_verdict": composed.verdict.value,
                "effective_verdict": effective_verdict.value,
                "verdict_confidence": composed.verdict_confidence,
                "api_provider": llm_response.api_provider,
                "api_response_id": llm_response.api_response_id,
            },
        ),
    )

    # ── Phase 7: POST-SEAL verifier outcome ──────────────────────
    post_meta = {
        "raw_critique_hash": raw_critique_hash,
        "critique_hash": composed_critique_hash,
        "raw_verdict": composed.verdict.value,
        "verdict": effective_verdict.value,
        "confidence": float(composed.verdict_confidence),
        "model": config.verifier_model,
        "cycle": cycle,
        "token_counts": {
            "input": llm_response.input_tokens,
            "output": llm_response.output_tokens,
            "think": llm_response.think_tokens,
        },
        "resolution_type": composed.resolution_type,
        "api_response_id": llm_response.api_response_id,
        "prompt_version": VERIFIER_PROMPT_VERSION,
    }
    post_content_files = [
        workspace.relative(composed_output_path),
        workspace.relative(raw_output_path),
        workspace.relative(response_path),
        workspace.relative(record_path),
    ]
    state, _post_receipt = await seal_step(
        seal_engine=seal_engine,
        state=state,
        step_type=StepType.POST_VERIFIER,
        content_file_paths=post_content_files,
        metadata=post_meta,
    )

    logger.info(
        "[verifier] [%s] POST-SEAL complete — verdict %s (raw=%s, conf=%.2f)",
        state.run_id[:8],
        effective_verdict.value,
        composed.verdict.value,
        composed.verdict_confidence,
    )

    # ── Routing decision ─────────────────────────────────────────
    # Computed inside the node so the LangGraph conditional edge can
    # read the verdict from ``state.current_critique`` without
    # re-running the budget logic. ``apply_routing_deltas`` is invoked
    # here too: doing so inside a conditional edge would mutate a
    # snapshot that LangGraph then discards.
    decision = route_after_verification(state, effective_verdict)
    apply_routing_deltas(state, decision)

    # ── State update ─────────────────────────────────────────────
    composed_dict = composed.model_dump(mode="json")
    composed_dict["effective_verdict"] = effective_verdict.value
    composed_dict["critique_hash"] = composed_critique_hash
    composed_dict["next_node"] = decision.next_node
    composed_dict["reviser_mode"] = decision.reviser_mode
    composed_dict["rescue_reason"] = (
        decision.rescue_reason.value if decision.rescue_reason else None
    )
    state.current_critique = composed_dict
    state.current_extracted_citations = [c.model_dump() for c in extracted]
    for check_dict in citation_check_dicts:
        state.citation_checks.append(check_dict)

    state.total_input_tokens += llm_response.input_tokens
    state.total_output_tokens += llm_response.output_tokens
    if llm_response.think_tokens is not None:
        state.total_think_tokens += llm_response.think_tokens
    state.total_wall_clock_seconds += duration_s

    state.messages.append(
        {
            "role": "verifier",
            "step_index": state.step_index,
            "timestamp": ts_end,
            "model": config.verifier_model,
            "prompt_hash": prompt_hash,
            "response_hash": raw_response_hash,
            "verdict": effective_verdict.value,
            "verdict_confidence": composed.verdict_confidence,
            "token_counts": {
                "input": llm_response.input_tokens,
                "output": llm_response.output_tokens,
                "think": llm_response.think_tokens,
            },
        },
    )

    state.updated_at = _now_iso()
    workspace.write_state(state)

    logger.info(
        "[verifier] [%s] State updated — verdict %s, total cycles %d",
        state.run_id[:8],
        effective_verdict.value,
        state.cycle_count,
    )

    return state
