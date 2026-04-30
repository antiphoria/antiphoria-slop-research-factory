# tests/unit/test_verifier_prompt.py

"""Unit tests for the Verifier prompt renderer (D-3 §4)."""

from __future__ import annotations

from slop_research_factory.config import FactoryConfig
from slop_research_factory.prompts.verifier_prompt import (
    VERIFIER_PROMPT_VERSION,
    load_verifier_system_prompt,
    render_verifier_prompt,
    render_verifier_user_message,
)


def _brief() -> dict:
    return {
        "thesis": "Cats are quietly running the internet.",
        "domain": "sociology",
        "constraints": "Avoid anthropomorphism.",
        "target_venue": "First Monday",
        "key_references": ["Smith 2024 — Cats Online"],
    }


class TestSystemPrompt:
    def test_loads_text(self) -> None:
        text = load_verifier_system_prompt()
        assert "Verifier" in text or "VERIFIER" in text or "PRE-SCREENING FILTER" in text


class TestUserMessage:
    def test_includes_brief_and_draft(self) -> None:
        text = render_verifier_user_message(
            brief=_brief(),
            current_draft="Draft body.",
            config=FactoryConfig(),
            cycle_count=1,
        )
        assert "<research_brief>" in text
        assert "Cats are quietly" in text
        assert "<candidate_draft>" in text
        assert "Draft body." in text
        assert "<output_schema>" in text

    def test_includes_previous_critique_on_subsequent_cycles(self) -> None:
        text = render_verifier_user_message(
            brief=_brief(),
            current_draft="Revised.",
            config=FactoryConfig(),
            cycle_count=2,
            previous_verdict="FIXABLE",
            previous_critique_summary="Citations missing.",
        )
        assert "Previous verdict: FIXABLE" in text
        assert "Citations missing." in text

    def test_omits_revision_block_on_first_cycle(self) -> None:
        text = render_verifier_user_message(
            brief=_brief(),
            current_draft="Draft.",
            config=FactoryConfig(),
            cycle_count=1,
        )
        assert "Previous verdict" not in text

    def test_includes_citation_check_results_when_provided(self) -> None:
        text = render_verifier_user_message(
            brief=_brief(),
            current_draft="Draft.",
            config=FactoryConfig(),
            cycle_count=1,
            citation_check_results=[
                {
                    "citation": {"citation_text": "Smith 2024"},
                    "result": "VERIFIED",
                    "confidence": 0.95,
                    "notes": None,
                },
            ],
        )
        assert "AUTOMATED CITATION CHECK RESULTS" in text
        assert "Smith 2024" in text
        assert "Result: VERIFIED" in text


class TestCombinedRenderer:
    def test_returns_three_strings(self) -> None:
        sys_, user, audit = render_verifier_prompt(
            brief=_brief(),
            current_draft="Draft.",
            config=FactoryConfig(),
            cycle_count=1,
        )
        assert all(isinstance(x, str) for x in (sys_, user, audit))
        assert VERIFIER_PROMPT_VERSION in audit
        assert "## System Prompt" in audit
        assert "## User Message" in audit
