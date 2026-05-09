# output/hai_card_renderer.py
# src/slop_research_factory/output/hai_card_renderer.py

"""
HAI Card Markdown renderer — D-6 §6.

Converts a :class:`~slop_research_factory.types.hai_card.HaiCard`
into a self-contained Markdown document suitable for publication
alongside the generated paper.

The security guarantee (D-1 §9) is rendered verbatim in a blockquote.
All numeric fields are formatted for human readability.

Spec references:
    D-1 §9    Security guarantee byte-identical text.
    D-2 §10   HAI Card schema.
    D-6 §6    Renderer contract.
    D-7 §7.4  Human review governance display.
"""

from __future__ import annotations

from slop_research_factory.types.enums import ConfidenceTier, HumanReviewStatus
from slop_research_factory.types.hai_card import HaiCard, ModelUsageRecord

__all__ = ["render_hai_card"]


def render_hai_card(card: HaiCard) -> str:
    """Render a complete HAI Card as Markdown.

    Args:
        card: A validated :class:`HaiCard` instance.

    Returns:
        UTF-8 Markdown string ready for ``output/hai_card.md``.
    """
    sections: list[str] = [
        _render_header(card),
        _render_security_guarantee(card),
        _render_identity(card),
        _render_models(card),
        _render_process(card),
        _render_verification(card),
        _render_provenance(card),
        _render_cost(card),
        _render_governance(card),
        _render_human_review(card),
        _render_footer(card),
    ]
    return "\n".join(sections)


# ── Section renderers ────────────────────────────────────────────────


def _render_header(card: HaiCard) -> str:
    return (
        "# Human–AI Interaction (HAI) Card\n\n"
        f"**Run ID:** `{card.run_id}`  \n"
        f"**Generated:** {card.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    )


def _render_security_guarantee(card: HaiCard) -> str:
    return (
        "\n---\n\n"
        "## ⚠️ Security Guarantee\n\n"
        f"> {card.security_guarantee}\n"
    )


def _render_identity(card: HaiCard) -> str:
    return (
        "\n---\n\n"
        "## Identity\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Brief Title | {card.brief_title} |\n"
        f"| Brief Hash | `{card.brief_hash[:16]}…` |\n"
        f"| Output Hash | `{card.output_hash[:16]}…` |\n"
    )


def _render_models(card: HaiCard) -> str:
    lines = [
        "\n## Model Usage\n",
        "| Model | Node | Input Tokens | Output Tokens | Calls |",
        "|-------|------|-------------:|-------------:|------:|",
    ]
    for rec in card.models_used:
        lines.append(
            f"| `{rec.model_id}` | {rec.node_name.value} "
            f"| {rec.input_tokens:,} | {rec.output_tokens:,} "
            f"| {rec.call_count} |"
        )

    total_in = sum(r.input_tokens for r in card.models_used)
    total_out = sum(r.output_tokens for r in card.models_used)
    total_calls = sum(r.call_count for r in card.models_used)
    lines.append(
        f"| **Total** | — "
        f"| **{total_in:,}** | **{total_out:,}** "
        f"| **{total_calls}** |"
    )
    lines.append("")
    return "\n".join(lines)


def _render_process(card: HaiCard) -> str:
    return (
        "\n## Process Summary\n\n"
        f"| Metric | Value |\n"
        f"|--------|------:|\n"
        f"| Total Cycles | {card.process.total_cycles} |\n"
        f"| Rejections (WRONG) | {card.process.rejection_count} |\n"
        f"| Revisions (FIXABLE) | {card.process.revision_count} |\n"
    )


def _render_verification(card: HaiCard) -> str:
    tier = ConfidenceTier.from_score(card.verification.verdict_confidence)
    tier_labels = {1: "T1 — Deterministic", 2: "T2 — LLM", 3: "T3 — Tool-grounded"}
    tier_label = tier_labels.get(card.verification.tier_reached, f"T{card.verification.tier_reached}")

    lines = [
        "\n## Verification Summary\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Final Verdict | **{card.verification.final_verdict.value}** |",
        f"| Confidence | {card.verification.verdict_confidence:.2%} ({tier.value}) |",
        f"| Tier Reached | {tier_label} |",
        f"| Deterministic Checks | {card.verification.deterministic_passed}/{card.verification.deterministic_total} |",
        f"| Citations Verified | {card.verification.citations_verified}/{card.verification.citations_total} |",
        "",
    ]
    return "\n".join(lines)


def _render_provenance(card: HaiCard) -> str:
    integrity = "✅ Verified" if card.chain_integrity_verified else "❌ BROKEN"
    return (
        "\n## Provenance Chain\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Total Seals | {card.total_seals} |\n"
        f"| Chain Integrity | {integrity} |\n"
        f"| Final Seal Hash | `{card.final_seal_hash[:16]}…` |\n"
    )


def _render_cost(card: HaiCard) -> str:
    return (
        "\n## Cost & Tokens\n\n"
        f"| Metric | Value |\n"
        f"|--------|------:|\n"
        f"| Total Input Tokens | {card.total_input_tokens:,} |\n"
        f"| Total Output Tokens | {card.total_output_tokens:,} |\n"
        f"| Estimated Cost (USD) | ${card.total_estimated_cost_usd:.4f} |\n"
    )


def _render_governance(card: HaiCard) -> str:
    return (
        "\n## Licensing & Governance\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Output License | {card.output_license} |\n"
        f"| Code License | {card.code_license} |\n"
        f"| Disclaimer | {card.disclaimer[:80]}{'…' if len(card.disclaimer) > 80 else ''} |\n"
    )


def _render_human_review(card: HaiCard) -> str:
    lines = [
        "\n## Human Review Status\n",
        f"**Status:** `{card.human_review_status.value}`\n",
    ]
    if card.human_review_status == HumanReviewStatus.REVIEWED:
        lines.append(f"**Reviewer:** {card.human_reviewer}\n")
        if card.human_review_timestamp:
            lines.append(
                f"**Reviewed:** "
                f"{card.human_review_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            )
    if card.human_review_notes:
        lines.append(f"\n**Notes:** {card.human_review_notes}\n")
    lines.append("")
    return "\n".join(lines)


def _render_footer(card: HaiCard) -> str:
    return (
        "\n---\n\n"
        "*This HAI Card was automatically generated by the SLOP Research Factory. "
        "It provides a machine-readable and human-readable summary of the AI "
        "generation process. The provenance chain provides cryptographic proof "
        "of the generation sequence.*\n"
    )