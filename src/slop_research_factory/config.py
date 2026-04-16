# src/slop_research_factory/config.py

"""
FactoryConfig — frozen configuration for a single factory run.

Spec reference: D-2 §4 (Configuration Schema).
Once a run begins, the configuration is sealed into the genesis
step and cannot be modified.
"""
from __future__ import annotations

from dataclasses import dataclass

from slop_research_factory.types.enums import CheckpointBackend


# -------------------------------------------------------------------
# FactoryConfig (D-2 §4)
# -------------------------------------------------------------------
@dataclass(frozen=True)
class FactoryConfig:
    """Frozen run configuration sealed into the genesis step.

    Every field carries a default so that ``FactoryConfig()`` succeeds
    with no arguments (E1-S01).  The class is frozen so that
    post-creation assignment raises ``FrozenInstanceError`` (E1-S02).

    The finalization node computes *configuration_overrides* by
    comparing the run config against ``FactoryConfig()``; only
    fields whose effective value differs from the default are
    recorded (D-2 §4, D-6 §4.6).

    **Loop-limit precedence** (D-2 §4):

    1. ``max_rejections``
    2. ``max_revisions``
    3. ``max_total_tokens`` / ``max_total_cost_usd`` (if set)
    4. ``max_total_cycles``
    """

    # -- Model topology (D-0 §4) ----------------------------------------
    generator_model: str = "deepseek/deepseek-r1"
    verifier_model: str = "google/gemini-2.5-flash"
    reviser_model: str = "deepseek/deepseek-r1"
    # reviser defaults to generator model (D-0 §4.2).

    # -- Loop limits -----------------------------------------------------
    max_rejections: int = 3       # WRONG verdicts before human rescue
    max_revisions: int = 5        # FIXABLE verdicts before human rescue
    max_total_cycles: int = 10    # Absolute loop cap
    max_total_tokens: int | None = None       # Optional hard token cap
    max_total_cost_usd: float | None = None   # Optional cost budget

    # -- Verifier behaviour (D-4 §8) ------------------------------------
    verifier_confidence_threshold: float = 0.8
    # Below this, a CORRECT verdict is demoted to FIXABLE (D-0 §8.1).

    enable_citation_checking: bool = True
    citation_check_sources: tuple[str, ...] = (
        "crossref",
        "semantic_scholar",
    )
    # Per D-1 §10 / Attack 3: multi-source is mandatory.
    enable_tavily_search: bool = True

    # Confidence dimension weights — MUST sum to 1.0 (D-4 §8).
    weight_logical_soundness: float = 0.35
    weight_mathematical_rigor: float = 0.25
    weight_citation_accuracy: float = 0.20
    weight_scope_compliance: float = 0.15
    weight_novelty_plausibility: float = 0.05

    # -- Output control --------------------------------------------------
    target_length_words: int = 5000
    capture_think_tokens: bool = True
    # Whether to capture and seal <think> traces (D-0 §4A).

    # -- Provenance (D-5 §11) -------------------------------------------
    enable_provenance: bool = True
    # Disabling requires BOTH this flag AND env var
    # ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE=true (D-1 §10).
    hash_algorithm: str = "sha256"

    # -- Infrastructure --------------------------------------------------
    workspace_base_path: str = "./workspaces"
    checkpoint_backend: CheckpointBackend = CheckpointBackend.SQLITE
