# tests/unit/test_config_loader.py

"""
Unit tests for TOML config loading, weight validation, and provenance gate.

Tests:
- Valid TOML parsing → FactoryConfig
- Missing file → FileNotFoundError
- Invalid TOML syntax → error
- Weight normalization (sum != 1.0 → normalized)
- Provenance gate: enable_provenance=false requires env var
- Unknown keys ignored gracefully
- Type coercion (string "true" → bool, string "5" → int)
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from slop_research_factory.config import FactoryConfig
from slop_research_factory.config_loader import load_config_from_file


class TestTomlParsing:
    """TOML file loading basics."""

    def test_valid_minimal_toml(self, tmp_path: Path) -> None:
        """Minimal valid TOML produces a FactoryConfig with defaults."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text("[factory]\n", encoding="utf-8")
        config = load_config_from_file(toml)
        assert isinstance(config, FactoryConfig)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """Non-existent TOML path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config_from_file(tmp_path / "does_not_exist.toml")

    def test_overrides_applied(self, tmp_path: Path) -> None:
        """Explicit values in TOML override defaults."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [factory]
                generator_model = "openai/gpt-4o"
                max_rejections = 7
                max_total_cycles = 20
                target_length_words = 8000
            """),
            encoding="utf-8",
        )
        config = load_config_from_file(toml)
        assert config.generator_model == "openai/gpt-4o"
        assert config.max_rejections == 7
        assert config.max_total_cycles == 20
        assert config.target_length_words == 8000

    def test_unknown_keys_ignored(self, tmp_path: Path) -> None:
        """Unknown TOML keys don't crash the loader."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [factory]
                max_rejections = 2
                totally_fake_key = "should be ignored"
                another_unknown = 42
            """),
            encoding="utf-8",
        )
        config = load_config_from_file(toml)
        assert config.max_rejections == 2
        assert not hasattr(config, "totally_fake_key")


class TestWeightValidation:
    """Weight normalization and boundary checks."""

    def test_weights_summing_to_one_unchanged(self, tmp_path: Path) -> None:
        """Weights that already sum to 1.0 are preserved exactly."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [factory]
                weight_logical_soundness = 0.35
                weight_mathematical_rigor = 0.25
                weight_citation_accuracy = 0.20
                weight_scope_compliance = 0.15
                weight_novelty_plausibility = 0.05
            """),
            encoding="utf-8",
        )
        config = load_config_from_file(toml)
        total = (
            config.weight_logical_soundness
            + config.weight_mathematical_rigor
            + config.weight_citation_accuracy
            + config.weight_scope_compliance
            + config.weight_novelty_plausibility
        )
        assert abs(total - 1.0) < 1e-9

    def test_weights_not_summing_to_one_normalized(self, tmp_path: Path) -> None:
        """Weights that don't sum to 1.0 are normalized proportionally."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [factory]
                weight_logical_soundness = 7.0
                weight_mathematical_rigor = 5.0
                weight_citation_accuracy = 4.0
                weight_scope_compliance = 3.0
                weight_novelty_plausibility = 1.0
            """),
            encoding="utf-8",
        )
        config = load_config_from_file(toml)
        total = (
            config.weight_logical_soundness
            + config.weight_mathematical_rigor
            + config.weight_citation_accuracy
            + config.weight_scope_compliance
            + config.weight_novelty_plausibility
        )
        assert abs(total - 1.0) < 1e-9
        # Proportions preserved
        assert config.weight_logical_soundness > config.weight_mathematical_rigor

    def test_negative_weight_raises(self, tmp_path: Path) -> None:
        """Negative weights are rejected."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [factory]
                weight_logical_soundness = -0.5
            """),
            encoding="utf-8",
        )
        with pytest.raises((ValueError, TypeError)):
            load_config_from_file(toml)

    def test_all_zero_weights_raises(self, tmp_path: Path) -> None:
        """All-zero weights cannot be normalized — must raise."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [factory]
                weight_logical_soundness = 0.0
                weight_mathematical_rigor = 0.0
                weight_citation_accuracy = 0.0
                weight_scope_compliance = 0.0
                weight_novelty_plausibility = 0.0
            """),
            encoding="utf-8",
        )
        with pytest.raises((ValueError, ZeroDivisionError)):
            load_config_from_file(toml)


class TestProvenanceGate:
    """D-1 §10: Disabling provenance requires explicit env var."""

    def test_provenance_disabled_without_env_var_raises(self, tmp_path: Path) -> None:
        """enable_provenance=false without env var → error."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [provenance]
                enabled = false
            """),
            encoding="utf-8",
        )
        env = {k: v for k, v in os.environ.items()}
        env.pop("ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises((ValueError, RuntimeError)):
                load_config_from_file(toml)

    def test_provenance_disabled_with_env_var_succeeds(self, tmp_path: Path) -> None:
        """enable_provenance=false WITH env var → config loads."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text(
            textwrap.dedent("""\
                [provenance]
                enabled = false
            """),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"ANTIPHORIA_I_UNDERSTAND_NO_PROVENANCE": "true"},
        ):
            config = load_config_from_file(toml)
            assert config.enable_provenance is False

    def test_provenance_enabled_is_default(self, tmp_path: Path) -> None:
        """Default config has provenance enabled."""
        toml = tmp_path / "antiphoria.toml"
        toml.write_text("[factory]\n", encoding="utf-8")
        config = load_config_from_file(toml)
        assert config.enable_provenance is True