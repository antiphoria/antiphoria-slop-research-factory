# src/slop_research_factory/prompts/verifier_prompt.py

"""Verifier prompt rendering.

Loads the system prompt from ``prompts/verifier/system_v0.1.txt`` and
builds the user message in Python. The ``user_template_v0.1.txt`` file
is kept on disk as the human-readable specification anchor
and is never re-evaluated at runtime — rendering is programmatic so we
get type checking and clean control flow.

Citation check results are merged into the
``<evaluation_context>`` block when present.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from slop_research_factory.prompts import load_prompt
from slop_research_factory.types.verifier_output import VerifierOutput

if TYPE_CHECKING:
    from slop_research_factory.config import FactoryConfig

logger = logging.getLogger(__name__)

VERIFIER_PROMPT_VERSION = "verifier_v0.1"


# ── System prompt ────────────────────────────────────────


def load_verifier_system_prompt() -> str:
    """Return the Verifier system prompt with header stripped."""
    return load_prompt("verifier", "system")


# ── User message ─────────────────────────────────────────


def render_verifier_user_message(
    *,
    brief: dict[str, Any],
    current_draft: str,
    config: FactoryConfig,
    cycle_count: int,
    previous_verdict: str | None = None,
    previous_critique_summary: str | None = None,
    citation_check_results: list[dict[str, Any]] | None = None,
    schema_json: str | None = None,
) -> str:
    """Render the Verifier user message.

    Args:
        brief: Serialised :class:`ResearchBrief` (``state.brief``).
        current_draft: The draft text the Verifier evaluates.
        config: Frozen :class:`FactoryConfig` for this run.
        cycle_count: Cycle number (1-indexed).
        previous_verdict: Last cycle's verdict, if cycle_count > 1.
        previous_critique_summary: Last cycle's critique summary,
            if cycle_count > 1.
        citation_check_results: Per-citation tool results (already
            ``model_dump``-ed). Each entry is expected to expose
            ``citation``, ``result``, ``confidence``, ``notes``.
        schema_json: ``VerifierOutput.model_json_schema()`` rendered
            JSON. Defaults to invoking the model.
    """
    if schema_json is None:
        schema_json = json.dumps(
            VerifierOutput.model_json_schema(),
            indent=2,
        )

    parts: list[str] = []

    parts.append("<research_brief>")
    parts.append(f"Thesis: {brief['thesis']}")
    if brief.get("constraints"):
        parts.append(f"Constraints: {brief['constraints']}")
    if brief.get("domain"):
        parts.append(f"Domain: {brief['domain']}")
    if brief.get("target_venue"):
        parts.append(f"Target venue: {brief['target_venue']}")
    if brief.get("key_references"):
        parts.append("Key references provided by the human author:")
        for ref in brief["key_references"]:
            parts.append(f"- {ref}")
    parts.append("</research_brief>")

    parts.append("")
    parts.append("<candidate_draft>")
    parts.append(current_draft)
    parts.append("</candidate_draft>")

    parts.append("")
    parts.append("<evaluation_context>")
    parts.append(
        f"This is evaluation cycle {cycle_count} of a maximum {config.max_total_cycles}.",
    )

    if cycle_count > 1 and previous_verdict:
        parts.append(f"Previous verdict: {previous_verdict}")
        if previous_critique_summary:
            parts.append(
                f"Previous critique summary: {previous_critique_summary}",
            )
        parts.append(
            "The draft above is a REVISED version responding to the "
            "previous critique. Pay particular attention to whether the "
            "previously identified flaws have been addressed.",
        )
        parts.append(
            "The previous critique summary is advisory context, not a "
            "binding judgment. Evaluate the current draft independently.",
        )

    if citation_check_results:
        parts.append("")
        parts.append(
            "AUTOMATED CITATION CHECK RESULTS (from external tools):",
        )
        for check in citation_check_results:
            citation = check.get("citation", {})
            citation_text = citation.get("citation_text", "(unknown)")
            parts.append(f'- Citation: "{citation_text}"')
            parts.append(f" Result: {check.get('result', 'INCONCLUSIVE')}")
            parts.append(f" Confidence: {check.get('confidence', 0.0)}")
            notes = check.get("notes")
            if notes:
                parts.append(f" Note: {notes}")
        parts.append(
            "Use these results to inform your "
            "confidence_citation_accuracy score. These checks are "
            "deterministic (DOI lookups) or tool-assisted (abstract "
            "retrieval) and are more reliable than your own citation "
            "memory.",
        )

    parts.append(
        "If the draft is dramatically shorter than the requested target "
        "length, treat that as a scope/completeness issue and mention it "
        "in your critique.",
    )
    parts.append("</evaluation_context>")

    parts.append("")
    parts.append(
        "Produce your evaluation as a JSON object conforming to the "
        "schema below. Output ONLY the JSON object — no preamble, no "
        "commentary, no markdown fencing.",
    )
    parts.append("")
    parts.append("<output_schema>")
    parts.append(schema_json)
    parts.append("</output_schema>")

    return "\n".join(parts)


# ── Combined helper ──────────────────────────────────────


def render_verifier_prompt(
    *,
    brief: dict[str, Any],
    current_draft: str,
    config: FactoryConfig,
    cycle_count: int,
    previous_verdict: str | None = None,
    previous_critique_summary: str | None = None,
    citation_check_results: list[dict[str, Any]] | None = None,
) -> tuple[str, str, str]:
    """Render system, user, and audit text for the Verifier node.

    Returns:
        ``(system_prompt, user_message, audit_text)`` — the audit
        text is the file written to ``drafts/cycle_{C}_verifier_prompt.md``.
    """
    system_prompt = load_verifier_system_prompt()
    user_message = render_verifier_user_message(
        brief=brief,
        current_draft=current_draft,
        config=config,
        cycle_count=cycle_count,
        previous_verdict=previous_verdict,
        previous_critique_summary=previous_critique_summary,
        citation_check_results=citation_check_results,
    )

    audit_lines = [
        f"# Verifier Prompt — {VERIFIER_PROMPT_VERSION}",
        "",
        "## System Prompt",
        "",
        system_prompt,
        "",
        "## User Message",
        "",
        user_message,
        "",
    ]
    audit_text = "\n".join(audit_lines)
    return system_prompt, user_message, audit_text
