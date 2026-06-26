# tests/unit/test_reviser_prompt.py

"""Unit tests for the Reviser prompt renderer."""

from __future__ import annotations

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.prompts.reviser_prompt import (
    REVISER_PROMPT_VERSION,
    load_reviser_system_prompt,
    render_reviser_prompt,
    render_reviser_user_message,
)
from slop_research_factory.types.enums import RunStatus
from slop_research_factory.types.state import FactoryState


@pytest.fixture
def state() -> FactoryState:
    return FactoryState(
        run_id="run-rev",
        status=RunStatus.GENERATING,
        config=FactoryConfig(),
        brief={"thesis": "T"},
        step_index=2,
        latest_hash="h",
        cycle_count=1,
        rejection_count=0,
        revision_count=0,
        current_draft="Old draft.",
    )


def _brief() -> dict:
    return {"thesis": "Cats run the internet.", "domain": "sociology"}


def _verifier_output_fixable() -> dict:
    return {
        "verdict": "FIXABLE",
        "critique_summary": "Sloppy logic in §3.",
        "critique_entries": [
            {
                "category": "logical_gap",
                "severity": "major",
                "location": "§3 ¶2",
                "description": "Step 5 doesn't follow from Step 4.",
                "suggested_fix": "Insert intermediate lemma.",
            },
        ],
        "resolution": "Revise §3 with the missing lemma.",
        "resolution_type": "remediation_plan",
    }


def _verifier_output_wrong() -> dict:
    return {
        "verdict": "WRONG",
        "critique_summary": "Argument is fundamentally circular.",
        "critique_entries": [
            {
                "category": "logical_gap",
                "severity": "critical",
                "description": "Premise assumes the conclusion.",
            },
        ],
        "resolution": "Restart with a non-circular framing.",
        "resolution_type": "explanation",
    }


class TestSystemPrompt:
    def test_loads_text(self) -> None:
        text = load_reviser_system_prompt()
        assert "REVISING" in text or "research drafting assistant" in text


class TestTargetedRepairMode:
    def test_includes_critique_and_repair_framing(self, state: FactoryState) -> None:
        text = render_reviser_user_message(
            brief=_brief(),
            previous_draft="Old draft.",
            verifier_output=_verifier_output_fixable(),
            critique_seal_hash="abc123",
            cycle_count=1,
            config=FactoryConfig(),
            state=state,
            mode="targeted_repair",
        )
        assert "Verdict: FIXABLE" in text
        assert "Critique hash: abc123" in text
        assert "Sloppy logic in §3." in text
        assert "Step 5 doesn't follow" in text
        assert "MODE: TARGETED REPAIR" in text


class TestFullRewriteMode:
    def test_includes_full_rewrite_framing(self, state: FactoryState) -> None:
        text = render_reviser_user_message(
            brief=_brief(),
            previous_draft="Old.",
            verifier_output=_verifier_output_wrong(),
            critique_seal_hash="def456",
            cycle_count=2,
            config=FactoryConfig(),
            state=state,
            mode="full_rewrite",
        )
        assert "Verdict: WRONG" in text
        assert "MODE: FULL REWRITE" in text
        assert "fundamentally different approach" in text


class TestRemainingBudgets:
    def test_displays_budgets(self, state: FactoryState) -> None:
        cfg = FactoryConfig(max_revisions=4, max_rejections=2)
        state.revision_count = 1
        state.rejection_count = 0
        text = render_reviser_user_message(
            brief=_brief(),
            previous_draft="x",
            verifier_output=_verifier_output_fixable(),
            critique_seal_hash="h",
            cycle_count=1,
            config=cfg,
            state=state,
            mode="targeted_repair",
        )
        assert "Remaining revision budget: 3" in text
        assert "Remaining rejection budget: 2" in text


class TestCombined:
    def test_returns_three_strings(self, state: FactoryState) -> None:
        sys_, user, audit = render_reviser_prompt(
            brief=_brief(),
            previous_draft="Old.",
            verifier_output=_verifier_output_fixable(),
            critique_seal_hash="h",
            cycle_count=1,
            config=FactoryConfig(),
            state=state,
            mode="targeted_repair",
        )
        assert all(isinstance(x, str) for x in (sys_, user, audit))
        assert REVISER_PROMPT_VERSION in audit
        assert "mode=targeted_repair" in audit
