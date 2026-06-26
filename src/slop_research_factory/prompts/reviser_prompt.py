# src/slop_research_factory/prompts/reviser_prompt.py

"""Reviser prompt rendering.

Two flavours, driven by the upstream Verifier verdict:

* **targeted_repair** (``Verdict.FIXABLE``) — preserve unflagged
  passages, address each :class:`CritiqueEntry` explicitly.

* **full_rewrite** (``Verdict.WRONG``) — discard the previous draft's
  argument structure, attempt a fundamentally different approach.

Both modes share the same system prompt; the user message
differs in framing only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from slop_research_factory.prompts import load_prompt

if TYPE_CHECKING:
    from slop_research_factory.config import FactoryConfig
    from slop_research_factory.types.state import FactoryState

logger = logging.getLogger(__name__)

REVISER_PROMPT_VERSION = "reviser_v0.1"

ReviserMode = Literal["targeted_repair", "full_rewrite"]


# ── System prompt ────────────────────────────────────────


def load_reviser_system_prompt() -> str:
    """Return the Reviser system prompt with header stripped."""
    return load_prompt("reviser", "system")


# ── User message ─────────────────────────────────────────


def render_reviser_user_message(
    *,
    brief: dict[str, Any],
    previous_draft: str,
    verifier_output: dict[str, Any],
    critique_seal_hash: str,
    cycle_count: int,
    config: FactoryConfig,
    state: FactoryState,
    mode: ReviserMode,
    citation_check_results: list[dict[str, Any]] | None = None,
) -> str:
    """Render the Reviser user message."""
    parts: list[str] = []

    parts.append("<research_brief>")
    parts.append(f"Thesis: {brief['thesis']}")
    if brief.get("constraints"):
        parts.append(f"Constraints: {brief['constraints']}")
    if brief.get("domain"):
        parts.append(f"Domain: {brief['domain']}")
    if brief.get("target_venue"):
        parts.append(f"Target venue: {brief['target_venue']}")
    parts.append("</research_brief>")

    parts.append("")
    parts.append("<previous_draft>")
    parts.append(previous_draft)
    parts.append("</previous_draft>")

    parts.append("")
    parts.append("<reviewer_critique>")
    parts.append(f"Verdict: {verifier_output['verdict']}")
    parts.append(f"Critique hash: {critique_seal_hash}")
    parts.append(
        f"Cycle: {cycle_count} of {config.max_total_cycles}",
    )

    parts.append("")
    parts.append("Summary")
    parts.append(str(verifier_output.get("critique_summary", "")))

    entries = verifier_output.get("critique_entries", [])
    if entries:
        parts.append("")
        parts.append("Itemized Issues")
        for i, entry in enumerate(entries, start=1):
            severity = entry.get("severity", "minor")
            category = entry.get("category", "other")
            parts.append(f"Issue {i} [{severity}] — {category}")
            location = entry.get("location")
            if location:
                parts.append(f"Location: {location}")
            description = entry.get("description", "")
            parts.append(description)
            suggested_fix = entry.get("suggested_fix")
            if suggested_fix:
                parts.append(f"Suggested fix: {suggested_fix}")
            parts.append("")

    parts.append("Reviewer's Resolution")
    parts.append(str(verifier_output.get("resolution", "")))
    parts.append("</reviewer_critique>")

    if citation_check_results:
        parts.append("")
        parts.append("<citation_verification>")
        parts.append(
            "The following citations were checked by automated tools:",
        )
        for check in citation_check_results:
            citation = check.get("citation", {})
            citation_text = citation.get("citation_text", "(unknown)")
            result = check.get("result", "INCONCLUSIVE")
            parts.append(f'- "{citation_text}": {result}')
            if result == "NOT_FOUND":
                parts.append(
                    " ⚠ This citation could not be verified. Remove "
                    "it or replace it with a verified reference.",
                )
            elif result == "METADATA_MISMATCH":
                parts.append(
                    " ⚠ The citation exists but metadata does not "
                    "match. Correct the author/year/title.",
                )
            elif result == "VERIFIED":
                parts.append(
                    " ✓ This citation has been verified. Remove any "
                    "[UNVERIFIED] tag if it is still present.",
                )
        parts.append("</citation_verification>")

    parts.append("")
    if mode == "full_rewrite":
        parts.append(
            "MODE: FULL REWRITE. The reviewer assessed the previous "
            "draft as fundamentally flawed (verdict WRONG). Treat the "
            "previous draft as failed evidence, not as scaffolding. "
            "Discard its argument structure and attempt a "
            "fundamentally different approach to the thesis. If you "
            "believe no valid approach exists within your "
            "capabilities, output: NO_OUTPUT: [explanation].",
        )
    else:
        parts.append(
            "MODE: TARGETED REPAIR. Preserve unflagged passages "
            "verbatim. Address each itemized issue explicitly. Do not "
            "gratuitously rewrite passages that the reviewer found "
            "acceptable.",
        )

    parts.append("")
    parts.append(
        f"Target length: approximately {config.target_length_words} words.",
    )
    parts.append(
        f"Remaining revision budget: {max(config.max_revisions - state.revision_count, 0)}",
    )
    parts.append(
        f"Remaining rejection budget: {max(config.max_rejections - state.rejection_count, 0)}",
    )

    parts.append("")
    parts.append("Please produce the complete revised draft now.")

    return "\n".join(parts)


# ── Combined helper ──────────────────────────────────────


def render_reviser_prompt(
    *,
    brief: dict[str, Any],
    previous_draft: str,
    verifier_output: dict[str, Any],
    critique_seal_hash: str,
    cycle_count: int,
    config: FactoryConfig,
    state: FactoryState,
    mode: ReviserMode,
    citation_check_results: list[dict[str, Any]] | None = None,
) -> tuple[str, str, str]:
    """Render system, user, and audit text for the Reviser node."""
    system_prompt = load_reviser_system_prompt()
    user_message = render_reviser_user_message(
        brief=brief,
        previous_draft=previous_draft,
        verifier_output=verifier_output,
        critique_seal_hash=critique_seal_hash,
        cycle_count=cycle_count,
        config=config,
        state=state,
        mode=mode,
        citation_check_results=citation_check_results,
    )

    audit_lines = [
        f"# Reviser Prompt — {REVISER_PROMPT_VERSION} (mode={mode})",
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
