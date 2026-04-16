# tests/unit/test_generator_prompt.py

"""
E1 unit tests for Generator prompt rendering (Step 6 / D-3 §3).

No LLM calls, no network, no filesystem side-effects beyond tmpdir.
"""

from __future__ import annotations

from slop_research_factory.prompts.generator_prompt import (
    GENERATOR_PROMPT_VERSION,
    render_generator_prompt,
    render_generator_user_message,
)


# ---------------------------------------------------------------------------

# Minimal FactoryConfig stub (from Step 1)

# ---------------------------------------------------------------------------

class _StubConfig:
    """Bare-minimum config stand-in for prompt tests."""

    target_length_words: int = 5000
    generator_model: str = "deepseek/deepseek-r1"


def _make_brief(**overrides) -> dict:
    base = {"thesis": "Test thesis statement"}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------

# System prompt tests

# ---------------------------------------------------------------------------

class TestGeneratorSystemPrompt:
    def test_loads_without_error(self):
        """System prompt file can be loaded (E1-level: no network)."""
        # If the file doesn't exist in the test env, render_generator_prompt
        # would raise FileNotFoundError; this asserts the file is accessible.
        _sys, _usr, _audit = render_generator_prompt(
            _make_brief(), _StubConfig(),
        )
        assert len(_sys) > 200, "System prompt looks too short"

    def test_contains_no_output_instruction(self):
        """D-3 §3.1: system prompt must include NO_OUTPUT instruction."""
        _sys, _, _ = render_generator_prompt(_make_brief(), _StubConfig())
        assert "NO_OUTPUT" in _sys

    def test_contains_unverified_instruction(self):
        """D-3 §3.1: system prompt must instruct [UNVERIFIED] tagging."""
        _sys, _, _ = render_generator_prompt(_make_brief(), _StubConfig())
        assert "[UNVERIFIED]" in _sys

    def test_no_persona_inflation(self):
        """D-3 §12 anti-pattern: no 'world-class expert' phrasing."""
        _sys, _, _ = render_generator_prompt(_make_brief(), _StubConfig())
        lower = _sys.lower()
        assert "world-class" not in lower
        assert "foremost expert" not in lower
        assert "nobel" not in lower


# ---------------------------------------------------------------------------

# User message tests

# ---------------------------------------------------------------------------

class TestGeneratorUserMessage:
    def test_thesis_present(self):
        msg = render_generator_user_message(
            _make_brief(thesis="Investigate Erdős–Ko–Rado"),
            _StubConfig(),
        )
        assert "Investigate Erdős–Ko–Rado" in msg

    def test_xml_brief_tags(self):
        """D-3 §2.2 rule 4: brief inside XML tags, verbatim."""
        msg = render_generator_user_message(_make_brief(), _StubConfig())
        assert "<research_brief>" in msg
        assert "</research_brief>" in msg

    def test_target_length_present(self):
        cfg = _StubConfig()
        cfg.target_length_words = 3000
        msg = render_generator_user_message(_make_brief(), cfg)
        assert "3000" in msg

    def test_optional_title_suggestion(self):
        msg_with = render_generator_user_message(
            _make_brief(title_suggestion="My Title"), _StubConfig(),
        )
        assert "My Title" in msg_with

        msg_without = render_generator_user_message(
            _make_brief(), _StubConfig(),
        )
        assert "Suggested title" not in msg_without

    def test_optional_outline(self):
        msg = render_generator_user_message(
            _make_brief(outline=["Introduction", "Methods", "Results"]),
            _StubConfig(),
        )
        assert "1. Introduction" in msg
        assert "2. Methods" in msg
        assert "3. Results" in msg

    def test_optional_key_references(self):
        msg = render_generator_user_message(
            _make_brief(key_references=["arXiv:2301.12345", "doi:10/abc"]),
            _StubConfig(),
        )
        assert "arXiv:2301.12345" in msg
        assert "doi:10/abc" in msg
        # D-3 §3.2: partial-reference tolerance note
        assert "partial" in msg.lower()

    def test_optional_constraints(self):
        msg = render_generator_user_message(
            _make_brief(constraints="Elementary techniques only"),
            _StubConfig(),
        )
        assert "Elementary techniques only" in msg

    def test_optional_domain(self):
        msg = render_generator_user_message(
            _make_brief(domain="algebraic topology"),
            _StubConfig(),
        )
        assert "algebraic topology" in msg

    def test_optional_target_venue(self):
        msg = render_generator_user_message(
            _make_brief(target_venue="JAIGP"),
            _StubConfig(),
        )
        assert "JAIGP" in msg

    def test_minimal_brief_renders(self):
        """Only thesis is required; all optionals absent."""
        msg = render_generator_user_message(
            {"thesis": "Minimal"},
            _StubConfig(),
        )
        assert "Minimal" in msg
        assert "Suggested title" not in msg
        assert "Outline" not in msg

    def test_unverified_reminder(self):
        """D-3 §3.2: final instruction to flag uncertain citations."""
        msg = render_generator_user_message(_make_brief(), _StubConfig())
        assert "[UNVERIFIED]" in msg


# ---------------------------------------------------------------------------

# Audit text / combined prompt

# ---------------------------------------------------------------------------

class TestAuditText:
    def test_contains_both_sections(self):
        _, _, audit = render_generator_prompt(_make_brief(), _StubConfig())
        assert "## System Prompt" in audit
        assert "## User Message" in audit

    def test_prompt_version_in_header(self):
        _, _, audit = render_generator_prompt(_make_brief(), _StubConfig())
        assert GENERATOR_PROMPT_VERSION in audit
