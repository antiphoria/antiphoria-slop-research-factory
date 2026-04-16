# tests/unit/test_types_init.py

"""
Verify public re-exports from ``slop_research_factory.types`` resolve.

Confirms:
  - every name in ``__all__`` is importable from the package,
  - ``__all__`` is duplicate-free and matches the reference table,
  - re-exports are identity-equal (``is``) to the source submodule,
  - kinds match (enum / BaseModel / dataclass / exception / function / str const).

``FactoryConfig`` stays in ``slop_research_factory.config``, not ``types``.
"""
from __future__ import annotations

import dataclasses
import enum
import importlib
import inspect
import unittest

from pydantic import BaseModel

# ====================================================================
# Authoritative reference: name → source sub-module (for ``is`` checks)
# Must match ``slop_research_factory.types.__init__.__all__`` (38 names).
# ====================================================================

_ALL_SOURCE: dict[str, str] = {
    # enums (11) — all ``str, Enum`` except CheckpointBackend (defined in config)
    "CheckpointBackend": "enums",
    "CitationCheckResult": "enums",
    "ConfidenceTier": "enums",
    "HumanRescueAction": "enums",
    "HumanReviewStatus": "enums",
    "NodeName": "enums",
    "RunStatus": "enums",
    "SealType": "enums",
    "StepType": "enums",
    "Verdict": "enums",
    # exception + callable from enums
    "IllegalTransitionError": "enums",
    "validate_status_transition": "enums",
    # brief / inference / verifier output (Pydantic + dataclass)
    "ResearchBrief": "brief",
    "InferenceRecord": "inference",
    "CitationCheckEntry": "verifier_output",
    "CitationEntry": "verifier_output",
    "CritiqueEntry": "verifier_output",
    "VerifierOutput": "verifier_output",
    # HAI card
    "DEFAULT_DISCLAIMER": "hai_card",
    "HaiCard": "hai_card",
    "ModelUsageRecord": "hai_card",
    "ProcessSummary": "hai_card",
    "SECURITY_GUARANTEE": "hai_card",
    "VerificationSummary": "hai_card",
    # human rescue
    "HumanRescueRequest": "human_rescue",
    "HumanRescueResolution": "human_rescue",
    # provenance
    "ProvenanceChain": "provenance",
    "ProvenanceChainError": "provenance",
    "ProvenanceMetadata": "provenance",
    "SealRecord": "provenance",
    # state
    "AppendOnlyList": "state",
    "FactoryState": "state",
    # tool types
    "CrossrefQuery": "tool_types",
    "CrossrefResult": "tool_types",
    "SemanticScholarQuery": "tool_types",
    "SemanticScholarResult": "tool_types",
    "TavilyQuery": "tool_types",
    "TavilyResult": "tool_types",
}

_EXPECTED_ALL_LEN = 38

assert len(_ALL_SOURCE) == _EXPECTED_ALL_LEN, (
    f"Reference table has {len(_ALL_SOURCE)} entries, expected {_EXPECTED_ALL_LEN}"
)

_ENUM_NAMES: frozenset[str] = frozenset({
    "CheckpointBackend",
    "CitationCheckResult",
    "ConfidenceTier",
    "HumanRescueAction",
    "HumanReviewStatus",
    "NodeName",
    "RunStatus",
    "SealType",
    "StepType",
    "Verdict",
})

_PYDANTIC_NAMES: frozenset[str] = frozenset({
    "ResearchBrief",
    "CitationCheckEntry",
    "CitationEntry",
    "CritiqueEntry",
    "VerifierOutput",
})

_DATACLASS_NAMES: frozenset[str] = frozenset({
    "InferenceRecord",
    "ModelUsageRecord",
    "ProcessSummary",
    "VerificationSummary",
    "HaiCard",
    "HumanRescueRequest",
    "HumanRescueResolution",
    "ProvenanceMetadata",
    "SealRecord",
    "FactoryState",
    "CrossrefQuery",
    "CrossrefResult",
    "SemanticScholarQuery",
    "SemanticScholarResult",
    "TavilyQuery",
    "TavilyResult",
})

_STR_CONST_NAMES: frozenset[str] = frozenset({
    "DEFAULT_DISCLAIMER",
    "SECURITY_GUARANTEE",
})

_SUBMODULES: tuple[str, ...] = (
    "brief",
    "enums",
    "hai_card",
    "human_rescue",
    "inference",
    "provenance",
    "state",
    "tool_types",
    "verifier_output",
)

_TYPES_PKG = "slop_research_factory.types"


# ====================================================================
# Tests
# ====================================================================


class TestAllImportsResolve(unittest.TestCase):
    """Smoke test: every name is importable from the package."""

    def test_import_all_public_names(self) -> None:
        """Bulk import of every ``__all__`` name succeeds."""
        mod = importlib.import_module(_TYPES_PKG)
        imported = []
        for name in mod.__all__:
            imported.append(getattr(mod, name))
        self.assertEqual(len(imported), _EXPECTED_ALL_LEN)


class TestDunderAll(unittest.TestCase):
    """``__all__`` is complete, duplicate-free, and consistent."""

    def test_length_matches_reference(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertEqual(len(mod.__all__), _EXPECTED_ALL_LEN)

    def test_no_duplicates(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertEqual(len(mod.__all__), len(set(mod.__all__)))

    def test_matches_reference_table(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertEqual(set(mod.__all__), set(_ALL_SOURCE))

    def test_every_name_is_a_module_attribute(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in mod.__all__:
            with self.subTest(name=name):
                self.assertTrue(
                    hasattr(mod, name),
                    f"{name!r} in __all__ but not an attribute of the module",
                )

    def test_no_public_type_missing_from_all(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        public_types = {
            n
            for n in dir(mod)
            if not n.startswith("_")
            and isinstance(getattr(mod, n), type)
        }
        declared = set(mod.__all__)
        missing = public_types - declared
        self.assertEqual(
            missing,
            set(),
            f"Public types not in __all__: {missing}",
        )


class TestEnumReExports(unittest.TestCase):
    """Enum members re-exported from ``types.enums``."""

    def test_are_enum_subclasses(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _ENUM_NAMES:
            with self.subTest(name=name):
                cls = getattr(mod, name)
                self.assertTrue(
                    issubclass(cls, enum.Enum),
                    f"{name} is not an Enum subclass",
                )

    def test_identity_matches_source(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        src = importlib.import_module(f"{_TYPES_PKG}.enums")
        for name in _ENUM_NAMES:
            with self.subTest(name=name):
                self.assertIs(getattr(mod, name), getattr(src, name))


class TestPydanticReExports(unittest.TestCase):
    """Pydantic ``BaseModel`` re-exports."""

    def test_are_basemodel_subclasses(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _PYDANTIC_NAMES:
            with self.subTest(name=name):
                cls = getattr(mod, name)
                self.assertTrue(
                    issubclass(cls, BaseModel),
                    f"{name} is not a BaseModel subclass",
                )

    def test_identity_matches_source(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _PYDANTIC_NAMES:
            sub = _ALL_SOURCE[name]
            with self.subTest(name=name, source=sub):
                src = importlib.import_module(f"{_TYPES_PKG}.{sub}")
                self.assertIs(getattr(mod, name), getattr(src, name))


class TestDataclassReExports(unittest.TestCase):
    """Frozen / plain dataclasses."""

    def test_are_dataclasses(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _DATACLASS_NAMES:
            with self.subTest(name=name):
                cls = getattr(mod, name)
                self.assertTrue(
                    dataclasses.is_dataclass(cls),
                    f"{name} is not a dataclass",
                )

    def test_identity_matches_source(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _DATACLASS_NAMES:
            sub = _ALL_SOURCE[name]
            with self.subTest(name=name, source=sub):
                src = importlib.import_module(f"{_TYPES_PKG}.{sub}")
                self.assertIs(getattr(mod, name), getattr(src, name))


class TestExceptionReExports(unittest.TestCase):
    """Exceptions."""

    def test_provenance_chain_error(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        src = importlib.import_module(f"{_TYPES_PKG}.provenance")
        self.assertTrue(issubclass(mod.ProvenanceChainError, Exception))
        self.assertIs(mod.ProvenanceChainError, src.ProvenanceChainError)

    def test_illegal_transition_error(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        src = importlib.import_module(f"{_TYPES_PKG}.enums")
        self.assertTrue(issubclass(mod.IllegalTransitionError, Exception))
        self.assertIs(mod.IllegalTransitionError, src.IllegalTransitionError)


class TestFunctionReExport(unittest.TestCase):
    """``validate_status_transition``."""

    def test_is_same_object(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        src = importlib.import_module(f"{_TYPES_PKG}.enums")
        self.assertTrue(
            inspect.isfunction(mod.validate_status_transition),
        )
        self.assertIs(
            mod.validate_status_transition,
            src.validate_status_transition,
        )


class TestStringConstants(unittest.TestCase):
    """``DEFAULT_DISCLAIMER`` and ``SECURITY_GUARANTEE``."""

    def test_are_non_empty_strings(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _STR_CONST_NAMES:
            with self.subTest(name=name):
                val = getattr(mod, name)
                self.assertIsInstance(val, str)
                self.assertGreater(len(val), 0)

    def test_identity_matches_hai_card(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        src = importlib.import_module(f"{_TYPES_PKG}.hai_card")
        self.assertIs(mod.DEFAULT_DISCLAIMER, src.DEFAULT_DISCLAIMER)
        self.assertIs(mod.SECURITY_GUARANTEE, src.SECURITY_GUARANTEE)


class TestProvenanceChainReExport(unittest.TestCase):
    """``ProvenanceChain`` is a plain class (not a dataclass)."""

    def test_is_not_dataclass(self) -> None:
        from slop_research_factory.types import ProvenanceChain

        self.assertFalse(dataclasses.is_dataclass(ProvenanceChain))

    def test_identity_matches_provenance_module(self) -> None:
        from slop_research_factory.types import ProvenanceChain
        from slop_research_factory.types.provenance import (
            ProvenanceChain as Src,
        )

        self.assertIs(ProvenanceChain, Src)


class TestAppendOnlyListReExport(unittest.TestCase):
    """``AppendOnlyList`` is a ``list`` subclass (not a dataclass)."""

    def test_is_list_subclass(self) -> None:
        from slop_research_factory.types import AppendOnlyList

        self.assertTrue(issubclass(AppendOnlyList, list))

    def test_is_not_dataclass(self) -> None:
        from slop_research_factory.types import AppendOnlyList

        self.assertFalse(dataclasses.is_dataclass(AppendOnlyList))

    def test_identity_matches_state_module(self) -> None:
        from slop_research_factory.types import AppendOnlyList
        from slop_research_factory.types.state import (
            AppendOnlyList as Src,
        )

        self.assertIs(AppendOnlyList, Src)


class TestSubmodulesImportable(unittest.TestCase):
    """Each sub-module used by re-exports is importable."""

    def test_all_submodules(self) -> None:
        for mod_name in _SUBMODULES:
            with self.subTest(module=mod_name):
                mod = importlib.import_module(f"{_TYPES_PKG}.{mod_name}")
                self.assertIsNotNone(mod)


class TestConfigSeparation(unittest.TestCase):
    """``FactoryConfig`` lives in ``config``, not ``types`` (D-2 §4)."""

    def test_factory_config_not_in_types_namespace(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertNotIn("FactoryConfig", dir(mod))

    def test_factory_config_not_in_types_all(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertNotIn("FactoryConfig", mod.__all__)

    def test_factory_config_importable_from_config(self) -> None:
        from slop_research_factory.config import FactoryConfig

        self.assertTrue(dataclasses.is_dataclass(FactoryConfig))


if __name__ == "__main__":
    unittest.main()
