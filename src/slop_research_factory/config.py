# src/slop_research_factory/config.py

"""
FactoryConfig — frozen configuration for a single factory run.

Spec reference: D-2 §4 (Configuration Schema).
Once a run begins, the configuration is sealed into the genesis
step and cannot be modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dc_fields
from enum import StrEnum
from typing import Any

# Defined here (not only in ``types.enums``) so ``FactoryConfig`` stays in a
# module that never imports ``types.*`` — ``types.state`` imports
# ``FactoryConfig``, and ``types.enums`` re-exports :class:`CheckpointBackend`
# for a single JSON-serialisable enum namespace.


class CheckpointBackend(StrEnum):
    """Checkpoint persistence backend (D-2 §4).

    SQLITE   — JSON + local files (Phase 1 default).
    POSTGRES — Database-backed (Phase 2).
    """

    SQLITE = "SQLITE"
    POSTGRES = "POSTGRES"


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

    **Loop-limit precedence** (D-2 §4) is evaluated *per verdict*:

    * On **WRONG**: ``max_rejections`` first, then shared budgets
      (``max_total_tokens``, ``max_total_cost_usd``), then
      ``max_total_cycles``.
    * On **FIXABLE**: ``max_revisions`` first, then the same shared
      budgets, then ``max_total_cycles``.
    * **CORRECT** does not apply these loop caps; it finalizes (subject
      to orchestration-level checks outside this dataclass).
    """

    # -- Model topology (D-0 §4) ----------------------------------------
    generator_model: str = "deepseek/deepseek-r1"
    verifier_model: str = "google/gemini-2.5-flash"
    reviser_model: str = "deepseek/deepseek-r1"
    # reviser defaults to generator model (D-0 §4.2).

    # -- Loop limits -----------------------------------------------------
    max_rejections: int = 3  # WRONG verdicts before human rescue
    max_revisions: int = 5  # FIXABLE verdicts before human rescue
    max_total_cycles: int = 10  # Absolute loop cap
    max_total_tokens: int | None = None  # Optional hard token cap
    max_total_cost_usd: float | None = None  # Optional cost budget

    # -- Verifier behaviour (D-4 §8) ------------------------------------
    # Citation extractor prompts (D-3 §6) use ``verifier_model``; there is no
    # separate ``citation_extractor_model`` in v0.1.
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


def factory_config_from_mapping(data: dict[str, Any]) -> FactoryConfig:
    """Construct ``FactoryConfig`` from a plain mapping (JSON, TOML, etc.).

    Keys not in :class:`FactoryConfig` are **silently dropped** so older
    ``state.json`` or config files with experimental fields still load
    (forward compatibility, matching workspace I/O).  Tuple and enum
    fields are coerced the same way as :func:`load_config` output.
    """
    known = {f.name for f in dc_fields(FactoryConfig)}
    kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in known}
    if "checkpoint_backend" in kwargs and not isinstance(
        kwargs["checkpoint_backend"],
        CheckpointBackend,
    ):
        kwargs["checkpoint_backend"] = CheckpointBackend(
            str(kwargs["checkpoint_backend"]),
        )
    if "citation_check_sources" in kwargs:
        kwargs["citation_check_sources"] = tuple(
            kwargs["citation_check_sources"],
        )
    return FactoryConfig(**kwargs)
