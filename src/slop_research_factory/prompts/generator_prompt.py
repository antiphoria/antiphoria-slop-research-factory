# src/slop_research_factory/prompts/generator_prompt.py

"""
Generator prompt rendering — Step 6 (D-3 §3, D-3 §11).

Loads the system prompt from prompts/generator/system_v0.1.txt and
renders the user message programmatically from ResearchBrief + FactoryConfig.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from slop_research_factory.prompts import load_prompt

if TYPE_CHECKING:
    from slop_research_factory.config import FactoryConfig

logger = logging.getLogger(__name__)

GENERATOR_PROMPT_VERSION = "generator_v0.1"

# ---------------------------------------------------------------------------

# Prompt file resolution

# ---------------------------------------------------------------------------


def load_generator_system_prompt() -> str:
    """Load the Generator system prompt (D-3 §3.1)."""
    return load_prompt("generator", "system")


# ---------------------------------------------------------------------------

# User message rendering (D-3 §3.2)

# ---------------------------------------------------------------------------


def render_generator_user_message(
    brief: dict[str, Any],
    config: FactoryConfig,
) -> str:
    """Build the Generator user message from a serialized ResearchBrief + config.

    Renders the template from D-3 §3.2 programmatically.  The brief
    dict is ``ResearchBrief.model_dump()`` stored in ``FactoryState.brief``.

    Args:
        brief: Serialized ResearchBrief (``state.brief``).
        config: The frozen FactoryConfig for this run.

    Returns:
        The complete user-message string ready for the LLM.
    """
    parts: list[str] = []
    parts.append("<research_brief>")
    parts.append(f"Thesis: {brief['thesis']}")

    if brief.get("title_suggestion"):
        parts.append(f"\nSuggested title: {brief['title_suggestion']}")

    if brief.get("outline"):
        parts.append("\nOutline:")
        for i, section in enumerate(brief["outline"], start=1):
            parts.append(f"  {i}. {section}")

    if brief.get("key_references"):
        parts.append("\nKey references to engage with:")
        for ref in brief["key_references"]:
            parts.append(f"- {ref}")
        parts.append(
            "\n(These references may be partial. Engage with whatever "
            "information is provided rather than rejecting incomplete entries.)"
        )

    if brief.get("constraints"):
        parts.append(f"\nConstraints: {brief['constraints']}")

    if brief.get("domain"):
        parts.append(f"\nDomain: {brief['domain']}")

    if brief.get("target_venue"):
        parts.append(f"\nTarget venue: {brief['target_venue']}")

    parts.append("</research_brief>")
    parts.append(
        f"\nTarget length: approximately {config.target_length_words} words."
    )
    parts.append(
        "\nPlease produce the draft now. Remember to flag any uncertain "
        "citations with [UNVERIFIED]."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------

# Combined prompt for audit file + LLM messages

# ---------------------------------------------------------------------------


def render_generator_prompt(
    brief: dict[str, Any],
    config: FactoryConfig,
) -> tuple[str, str, str]:
    """Render the full Generator prompt set.

    Returns:
        A 3-tuple of ``(system_prompt, user_message, audit_text)`` where
        *audit_text* is the combined Markdown written to the workspace
        prompt file for the sealed record.
    """
    system_prompt = load_generator_system_prompt()
    user_message = render_generator_user_message(brief, config)

    # Audit file: human-readable combined prompt (D-5 §5.2 Phase 1).
    audit_lines = [
        f"# Generator Prompt — {GENERATOR_PROMPT_VERSION}",
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
