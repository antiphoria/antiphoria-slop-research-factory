# tests/unit/test_config.py

"""
E1 unit tests for config.py — D-2 §4.

Test-to-spec traceability
~~~~~~~~~~~~~~~~~~~~~~~~~
  E1-S01  FactoryConfig instantiates with all defaults.
  E1-S02  FactoryConfig is frozen.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.types.enums import CheckpointBackend


# ── E1-S01 — FactoryConfig all defaults (D-2 §4) ───────────────────


def test_e1_s01_factory_config_all_defaults() -> None:
    """FactoryConfig() succeeds with no arguments and every field
    carries its documented default value (D-2 §4)."""
    cfg = FactoryConfig()

    # -- Model topology -------------------------------------------
    assert cfg.generator_model == "deepseek/deepseek-r1"
    assert cfg.verifier_model == "google/gemini-2.5-flash"
    assert cfg.reviser_model == "deepseek/deepseek-r1"

    # -- Loop limits ----------------------------------------------
    assert cfg.max_rejections == 3
    assert cfg.max_revisions == 5
    assert cfg.max_total_cycles == 10
    assert cfg.max_total_tokens is None
    assert cfg.max_total_cost_usd is None

    # -- Verifier behaviour ---------------------------------------
    assert cfg.verifier_confidence_threshold == 0.8
    assert cfg.enable_citation_checking is True
    assert cfg.citation_check_sources == (
        "crossref",
        "semantic_scholar",
    )
    assert cfg.enable_tavily_search is True

    # -- Dimension weights (D-4 §8) — verify sum == 1.0 ----------
    assert cfg.weight_logical_soundness == 0.35
    assert cfg.weight_mathematical_rigor == 0.25
    assert cfg.weight_citation_accuracy == 0.20
    assert cfg.weight_scope_compliance == 0.15
    assert cfg.weight_novelty_plausibility == 0.05
    total_weight = (
        cfg.weight_logical_soundness
        + cfg.weight_mathematical_rigor
        + cfg.weight_citation_accuracy
        + cfg.weight_scope_compliance
        + cfg.weight_novelty_plausibility
    )
    assert abs(total_weight - 1.0) < 1e-9, (
        f"Default weights must sum to 1.0, got {total_weight}"
    )

    # -- Output control -------------------------------------------
    assert cfg.target_length_words == 5000
    assert cfg.capture_think_tokens is True

    # -- Provenance -----------------------------------------------
    assert cfg.enable_provenance is True
    assert cfg.hash_algorithm == "sha256"

    # -- Infrastructure -------------------------------------------
    assert cfg.workspace_base_path == "./workspaces"
    assert cfg.checkpoint_backend == CheckpointBackend.SQLITE


# ── E1-S02 — FactoryConfig frozen (D-2 §4) ─────────────────────────


def test_e1_s02_factory_config_frozen() -> None:
    """FactoryConfig is frozen; assignment to any field raises
    ``FrozenInstanceError`` (D-2 §4)."""
    cfg = FactoryConfig()

    # str field
    with pytest.raises(FrozenInstanceError):
        cfg.generator_model = "other/model"  # type: ignore[misc]

    # int field
    with pytest.raises(FrozenInstanceError):
        cfg.max_rejections = 99  # type: ignore[misc]

    # bool field
    with pytest.raises(FrozenInstanceError):
        cfg.enable_provenance = False  # type: ignore[misc]

    # Optional field
    with pytest.raises(FrozenInstanceError):
        cfg.max_total_tokens = 100_000  # type: ignore[misc]

    # float field
    with pytest.raises(FrozenInstanceError):
        cfg.verifier_confidence_threshold = 0.5  # type: ignore[misc]

    # Enum field
    with pytest.raises(FrozenInstanceError):
        cfg.checkpoint_backend = (  # type: ignore[misc]
            CheckpointBackend.POSTGRES
        )

    # tuple field
    with pytest.raises(FrozenInstanceError):
        cfg.citation_check_sources = (  # type: ignore[misc]
            ("crossref",)
        )
