# tests/unit/test_hai_card_renderer.py

"""
Unit tests for HAI Card Markdown renderer.

Tests:
- Complete render produces valid Markdown structure
- Security guarantee rendered byte-identical
- All sections present
- Empty/zero fields handled gracefully
- Model usage table formatting
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from slop_research_factory.output.hai_card_renderer import render_hai_card
from slop_research_factory.types.enums import (
    HumanReviewStatus,
    NodeName,
    Verdict,
)
from slop_research_factory.types.hai_card import (
    DEFAULT_DISCLAIMER,
    SECURITY_GUARANTEE,
    HaiCard,
    ModelUsageRecord,
    ProcessSummary,
    VerificationSummary,
)


def _minimal_card(**overrides) -> HaiCard:
    """Build a minimal valid HaiCard for testing."""
    defaults = dict(
        run_id="test-run-001",
        generated_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        brief_title="Test Research Paper",
        brief_hash="a" * 64,
        models_used=(
            ModelUsageRecord(
                model_id="deepseek/deepseek-r1",
                node_name=NodeName.GENERATOR,
                input_tokens=1000,
                output_tokens=5000,
                call_count=1,
            ),
        ),
        process=ProcessSummary(
            total_cycles=2,
            rejection_count=0,
            revision_count=1,
        ),
        verification=VerificationSummary(
            final_verdict=Verdict.CORRECT,
            verdict_confidence=0.92,
            tier_reached=3,
            deterministic_passed=0,
            deterministic_total=0,
            citations_verified=3,
            citations_total=4,
        ),
        total_seals=8,
        chain_integrity_verified=True,
        final_seal_hash="b" * 64,
        output_hash="c" * 64,
        disclaimer=DEFAULT_DISCLAIMER,
        total_input_tokens=2000,
        total_output_tokens=8000,
        total_estimated_cost_usd=0.0523,
        output_license="CC BY 4.0",
        code_license="Apache-2.0",
    )
    defaults.update(overrides)
    return HaiCard(**defaults)


class TestBasicRendering:
    """Core rendering output structure."""

    def test_renders_non_empty_string(self) -> None:
        """Render produces non-empty output."""
        card = _minimal_card()
        result = render_hai_card(card)
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_h1_header(self) -> None:
        """Output starts with the HAI Card title."""
        card = _minimal_card()
        result = render_hai_card(card)
        assert "# Human–AI Interaction (HAI) Card" in result

    def test_contains_run_id(self) -> None:
        """Run ID appears in output."""
        card = _minimal_card(run_id="my-special-run-xyz")
        result = render_hai_card(card)
        assert "my-special-run-xyz" in result

    def test_all_sections_present(self) -> None:
        """All expected section headers appear."""
        card = _minimal_card()
        result = render_hai_card(card)
        expected_sections = [
            "## ⚠️ Security Guarantee",
            "## Identity",
            "## Model Usage",
            "## Process Summary",
            "## Verification Summary",
            "## Provenance Chain",
            "## Cost & Tokens",
            "## Licensing & Governance",
            "## Human Review Status",
        ]
        for section in expected_sections:
            assert section in result, f"Missing section: {section}"


class TestSecurityGuarantee:
    """D-1 §9: Security guarantee must be byte-identical."""

    def test_security_guarantee_present(self) -> None:
        """The security guarantee text appears verbatim."""
        card = _minimal_card()
        result = render_hai_card(card)
        assert SECURITY_GUARANTEE in result

    def test_security_guarantee_in_blockquote(self) -> None:
        """Security guarantee is rendered inside a blockquote."""
        card = _minimal_card()
        result = render_hai_card(card)
        # Find the line containing the guarantee — should start with >
        for line in result.splitlines():
            if SECURITY_GUARANTEE[:30] in line:
                assert line.strip().startswith(">")
                break
        else:
            pytest.fail("Security guarantee not found in any line")


class TestModelUsageTable:
    """Model usage section renders correctly."""

    def test_single_model_row(self) -> None:
        """Single model produces one data row."""
        card = _minimal_card()
        result = render_hai_card(card)
        assert "deepseek/deepseek-r1" in result
        assert "1,000" in result or "1000" in result

    def test_multiple_models(self) -> None:
        """Multiple models each get their own row."""
        card = _minimal_card(
            models_used=(
                ModelUsageRecord(
                    model_id="deepseek/deepseek-r1",
                    node_name=NodeName.GENERATOR,
                    input_tokens=1000,
                    output_tokens=5000,
                    call_count=1,
                ),
                ModelUsageRecord(
                    model_id="google/gemini-2.5-flash",
                    node_name=NodeName.VERIFICATION,
                    input_tokens=2000,
                    output_tokens=3000,
                    call_count=2,
                ),
            ),
        )
        result = render_hai_card(card)
        assert "deepseek/deepseek-r1" in result
        assert "google/gemini-2.5-flash" in result

    def test_total_row_present(self) -> None:
        """A total row aggregates all models."""
        card = _minimal_card()
        result = render_hai_card(card)
        assert "**Total**" in result


class TestEdgeCases:
    """Edge cases and zero values."""

    def test_zero_citations(self) -> None:
        """Zero citations doesn't crash."""
        card = _minimal_card(
            verification=VerificationSummary(
                final_verdict=Verdict.CORRECT,
                verdict_confidence=0.95,
                tier_reached=2,
                deterministic_passed=0,
                deterministic_total=0,
                citations_verified=0,
                citations_total=0,
            ),
        )
        result = render_hai_card(card)
        assert "0/0" in result

    def test_chain_broken_indicator(self) -> None:
        """Broken chain shows appropriate indicator."""
        card = _minimal_card(chain_integrity_verified=False)
        result = render_hai_card(card)
        assert "❌" in result or "BROKEN" in result

    def test_cost_formatted(self) -> None:
        """Cost appears with dollar sign."""
        card = _minimal_card(total_estimated_cost_usd=1.2345)
        result = render_hai_card(card)
        assert "$1.2345" in result or "$1.23" in result

    def test_human_review_unreviewed(self) -> None:
        """Default unreviewed status renders."""
        card = _minimal_card()
        result = render_hai_card(card)
        assert HumanReviewStatus.NOT_REVIEWED.value in result
