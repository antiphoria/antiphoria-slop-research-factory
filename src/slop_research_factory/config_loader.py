# src/slop_research_factory/config_loader.py

"""
Configuration loader: antiphoria.toml + env → FactoryConfig.

Reads the optional ``antiphoria.toml`` file, applies programmatic
overrides, validates D-4/D-5 invariants, and returns a frozen
``FactoryConfig``.

Resolution order (last wins):
    1. ``FactoryConfig`` defaults  (D-2 §4)
    2. ``antiphoria.toml`` on disk
    3. *overrides* dict            (CLI flags / programmatic callers)

Spec references:
    D-2 §4   FactoryConfig field definitions and defaults.
    D-4 §8   Confidence weights must sum to 1.0.
    D-5 §11  Provenance disable requires env-var safety gate.
    D-1 §10  ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE.
"""
from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any

from slop_research_factory.config import CheckpointBackend, FactoryConfig

__all__ = ["load_config", "ConfigLoadError"]

logger = logging.getLogger(__name__)


# ===================================================================

# Exception

# ===================================================================

class ConfigLoadError(Exception):
    """Raised when configuration loading or validation fails."""


# ===================================================================

# Constants

# ===================================================================

_KNOWN_FIELDS: frozenset[str] = frozenset(
    f.name for f in dc_fields(FactoryConfig)
)

_DEFAULT_TOML_SEARCH: tuple[Path, ...] = (
    Path("antiphoria.toml"),
    Path("config") / "antiphoria.toml",
    Path.home() / ".config" / "antiphoria" / "antiphoria.toml",
)


# ===================================================================

# TOML key → FactoryConfig field mapping tables

# ===================================================================

# Each top-level TOML section maps its keys to FactoryConfig fields.

# Keys present in the file override defaults; absent keys keep them.

_SECTION_MAP: dict[str, dict[str, str]] = {
    "models": {
        "generator": "generator_model",
        "verifier":  "verifier_model",
        "reviser":   "reviser_model",
    },
    "limits": {
        "max_rejections":   "max_rejections",
        "max_revisions":    "max_revisions",
        "max_total_cycles": "max_total_cycles",
        "max_total_tokens": "max_total_tokens",
        "max_total_cost_usd": "max_total_cost_usd",
    },
    "output": {
        "target_length_words":  "target_length_words",
        "capture_think_tokens": "capture_think_tokens",
    },
    "provenance": {
        "enabled":        "enable_provenance",
        "hash_algorithm": "hash_algorithm",
    },
    "infrastructure": {
        "workspace_base_path": "workspace_base_path",
        "checkpoint_backend":  "checkpoint_backend",
    },
}

_VERIFIER_SCALAR_MAP: dict[str, str] = {
    "confidence_threshold":     "verifier_confidence_threshold",
    "enable_citation_checking": "enable_citation_checking",
    "citation_check_sources":   "citation_check_sources",
    "enable_tavily_search":     "enable_tavily_search",
}

_WEIGHT_MAP: dict[str, str] = {
    "logical_soundness":    "weight_logical_soundness",
    "mathematical_rigor":   "weight_mathematical_rigor",
    "citation_accuracy":    "weight_citation_accuracy",
    "scope_compliance":     "weight_scope_compliance",
    "novelty_plausibility": "weight_novelty_plausibility",
}


# ===================================================================

# TOML discovery

# ===================================================================

def _find_toml(explicit: str | Path | None) -> Path | None:
    """Return the path to the TOML config, or ``None`` if absent.

    When *explicit* is given, it must exist (raises on miss).
    Otherwise the default search paths are tried in order.
    """
    if explicit is not None:
        p = Path(explicit)
        if p.is_file():
            return p
        raise FileNotFoundError(
            f"Explicit config path does not exist: {p}"
        )
    for candidate in _DEFAULT_TOML_SEARCH:
        if candidate.is_file():
            return candidate
    return None


# ===================================================================

# Flattening: nested TOML → flat FactoryConfig kwargs

# ===================================================================

def _flatten_toml(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert nested TOML tables into ``FactoryConfig`` keyword args.

    Only keys that appear in the mapping tables are extracted.
    Unrecognised top-level sections are warned about separately.
    """
    flat: dict[str, Any] = {}

    # ── Simple 1:1 sections ────────────────────────────────────────
    for section_key, field_map in _SECTION_MAP.items():
        section = raw.get(section_key, {})
        if not isinstance(section, dict):
            continue
        for toml_key, config_field in field_map.items():
            if toml_key in section:
                flat[config_field] = section[toml_key]

    # ── [verifier] scalar keys ─────────────────────────────────────
    verifier = raw.get("verifier", {})
    if isinstance(verifier, dict):
        for toml_key, config_field in _VERIFIER_SCALAR_MAP.items():
            if toml_key in verifier:
                flat[config_field] = verifier[toml_key]

        # ── [verifier.weights] ─────────────────────────────────────
        weights = verifier.get("weights", {})
        if isinstance(weights, dict):
            for toml_key, config_field in _WEIGHT_MAP.items():
                if toml_key in weights:
                    flat[config_field] = weights[toml_key]

    # ── Type coercions ─────────────────────────────────────────────
    # TOML arrays → tuple (FactoryConfig expects tuple[str, ...])
    if "citation_check_sources" in flat:
        flat["citation_check_sources"] = tuple(
            flat["citation_check_sources"]
        )

    # checkpoint_backend string → CheckpointBackend enum
    if "checkpoint_backend" in flat:
        raw_val = flat["checkpoint_backend"]
        try:
            flat["checkpoint_backend"] = CheckpointBackend(raw_val.upper())
        except ValueError as exc:
            raise ConfigLoadError(
                f"Invalid checkpoint_backend {raw_val!r}. "
                f"Expected one of: {[e.value for e in CheckpointBackend]}"
            ) from exc

    return flat


# ===================================================================

# Warnings for unrecognised keys

# ===================================================================

_KNOWN_SECTIONS: frozenset[str] = frozenset(_SECTION_MAP) | {"verifier"}


def _warn_unknown_sections(raw: dict[str, Any]) -> None:
    """Log a warning for each top-level TOML key we do not consume."""
    for key in sorted(set(raw) - _KNOWN_SECTIONS):
        logger.warning(
            "Unknown TOML section [%s] in antiphoria.toml (ignored).",
            key,
        )


def _warn_unknown_fields(flat: dict[str, Any]) -> None:
    """Log a warning for flattened keys absent from FactoryConfig."""
    for key in sorted(set(flat) - _KNOWN_FIELDS):
        logger.warning(
            "Config key %r does not match any FactoryConfig field "
            "(ignored).",
            key,
        )


# ===================================================================

# Validation helpers

# ===================================================================

def _validate_weights(cfg: FactoryConfig) -> None:
    """D-4 §8: confidence dimension weights must sum to 1.0."""
    total = (
        cfg.weight_logical_soundness
        + cfg.weight_mathematical_rigor
        + cfg.weight_citation_accuracy
        + cfg.weight_scope_compliance
        + cfg.weight_novelty_plausibility
    )
    if abs(total - 1.0) > 1e-6:
        raise ConfigLoadError(
            f"[verifier.weights] must sum to 1.0, got {total:.6f}. "
            "Check antiphoria.toml."
        )


def _validate_provenance_gate(cfg: FactoryConfig) -> None:
    """D-5 §11 / D-1 §10: disabling provenance requires env-var.

    The error message below is verbatim from D-5 §11.
    """
    if cfg.enable_provenance:
        return

    env_val = os.environ.get(
        "ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE", "",
    ).strip().lower()

    if env_val != "true":
        raise ConfigLoadError(
            "Provenance is disabled in configuration, but the "
            "environment variable "
            "ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE is not set "
            'to "true".\n'
            "\n"
            "Disabling provenance removes all tamper-evidence and\n"
            "auditability guarantees.  The output will carry NO\n"
            "cryptographic proof of how it was generated.\n"
            "\n"
            "If you understand this and wish to proceed, set:\n"
            "\n"
            "    export ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE=true"
            "\n"
            "\n"
            "For production use, set enabled = true under "
            "[provenance] in antiphoria.toml."
        )

    logger.warning(
        "Provenance is DISABLED.  No cryptographic seals will be "
        "generated for this run.  Output is NOT auditable."
    )


# ===================================================================

# Public API

# ===================================================================

def load_config(
    toml_path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> FactoryConfig:
    """Load, merge, and validate a ``FactoryConfig``.

    Args:
        toml_path: Explicit path to a TOML file.  When ``None``,
            the default search paths are tried:
            ``./antiphoria.toml`` → ``./config/antiphoria.toml``
            → ``~/.config/antiphoria/antiphoria.toml``.
            If none is found, all ``FactoryConfig`` defaults apply.
        overrides: Field-name → value dict applied **after** TOML.
            Useful for CLI ``--flag`` arguments.

    Returns:
        A frozen ``FactoryConfig`` ready for use by the orchestrator.

    Raises:
        FileNotFoundError: *toml_path* was given but does not exist.
        ConfigLoadError: Weight-sum or provenance-gate validation
            failed, or an invalid enum value was encountered.
    """
    # ── 1. Locate & load TOML ─────────────────────────────────────
    toml_file = _find_toml(toml_path)
    flat: dict[str, Any] = {}

    if toml_file is not None:
        logger.info("Loading configuration from %s", toml_file)
        with open(toml_file, "rb") as fh:
            raw = tomllib.load(fh)
        _warn_unknown_sections(raw)
        flat = _flatten_toml(raw)
    else:
        logger.info(
            "No antiphoria.toml found; using FactoryConfig defaults."
        )

    # ── 2. Programmatic overrides ─────────────────────────────────
    if overrides:
        flat.update(overrides)

    # ── 3. Filter unknown fields ──────────────────────────────────
    _warn_unknown_fields(flat)
    clean = {k: v for k, v in flat.items() if k in _KNOWN_FIELDS}

    # ── 4. Construct frozen config ────────────────────────────────
    try:
        cfg = FactoryConfig(**clean)
    except TypeError as exc:
        raise ConfigLoadError(
            f"Invalid configuration: {exc}"
        ) from exc

    # ── 5. Validate invariants ────────────────────────────────────
    _validate_weights(cfg)
    _validate_provenance_gate(cfg)

    logger.info(
        "FactoryConfig ready — generator=%s  verifier=%s  "
        "provenance=%s  threshold=%.2f",
        cfg.generator_model,
        cfg.verifier_model,
        cfg.enable_provenance,
        cfg.verifier_confidence_threshold,
    )
    return cfg
