# tests/test_types_init.py


"""
Step 11: Verify all re-exports from ``types/__init__.py`` resolve.

Confirms:
  - every name in ``__all__`` is importable from the package,
  - ``__all__`` is complete, duplicate-free, and matches the
    authoritative reference table below,
  - each re-export is identity-equal (``is``) to its source
    sub-module object,
  - each name has the expected kind (enum / BaseModel / dataclass),
  - ``FactoryConfig`` is correctly NOT in ``types/`` (it lives
    in ``slop_research_factory.config``).
"""
from __future__ import annotations

import dataclasses
import enum
import importlib
import unittest

from pydantic import BaseModel


# ====================================================================
# Authoritative reference table
# ====================================================================
# One entry per re-exported name → source sub-module.
# An auditor can diff this against types/__init__.py and D-2
# to confirm nothing is missing or extraneous.
# ====================================================================

_ENUM_SOURCE: dict[str, str] = {
    "CheckpointBackend": "enums",
    "CitationCheckResult": "enums",
    "ConfidenceTier": "enums",
    "RunStatus": "enums",
    "StepType": "enums",
    "Verdict": "enums",
}  # 6

_PYDANTIC_SOURCE: dict[str, str] = {
    "CitationCheckEntry": "verifier_output",
    "CitationEntry": "verifier_output",
    "CritiqueEntry": "verifier_output",
    "ResearchBrief": "brief",
    "VerifierOutput": "verifier_output",
}  # 5

_DATACLASS_SOURCE: dict[str, str] = {
    "CrossrefQuery": "tool_types",
    "CrossrefResult": "tool_types",
    "FactoryState": "state",
    "HAICardData": "provenance",
    "HumanRescueRequest": "tool_types",
    "HumanRescueResponse": "tool_types",
    "InferenceRecord": "inference",
    "ProvenanceManifest": "provenance",
    "SealPayload": "provenance",
    "SealedStepReceipt": "provenance",
    "SemanticScholarQuery": "tool_types",
    "SemanticScholarResult": "tool_types",
    "TavilyQuery": "tool_types",
    "TavilyResult": "tool_types",
}  # 14

_OTHER_SOURCE: dict[str, str] = {
    "AppendOnlyList": "state",
    "IllegalTransitionError": "enums",
    "validate_status_transition": "enums",
}  # 3

_ALL_SOURCE: dict[str, str] = {
    **_ENUM_SOURCE,
    **_PYDANTIC_SOURCE,
    **_DATACLASS_SOURCE,
    **_OTHER_SOURCE,
}
assert len(_ALL_SOURCE) == 28, (  # structural self-check
    f"Reference table has {len(_ALL_SOURCE)} entries, expected 28"
)

_SUBMODULES: tuple[str, ...] = (
    "brief",
    "enums",
    "inference",
    "provenance",
    "state",
    "tool_types",
    "verifier_output",
)

_TYPES_PKG = "slop_research_factory.types"


# ====================================================================
# Test classes
# ====================================================================


class TestAllImportsResolve(unittest.TestCase):
    """Smoke test: every name is importable from the package."""

    def test_import_all_28_names(self) -> None:
        """Single bulk import of every public name succeeds."""
        from slop_research_factory.types import (
            # Enums (6)
            CheckpointBackend,
            CitationCheckResult,
            ConfidenceTier,
            RunStatus,
            StepType,
            Verdict,
            # Enum helpers (2)
            IllegalTransitionError,
            validate_status_transition,
            # Input (1)
            ResearchBrief,
            # State (2)
            AppendOnlyList,
            FactoryState,
            # Verifier output (4)
            CitationCheckEntry,
            CitationEntry,
            CritiqueEntry,
            VerifierOutput,
            # Provenance (4)
            HAICardData,
            ProvenanceManifest,
            SealPayload,
            SealedStepReceipt,
            # Inference (1)
            InferenceRecord,
            # Tools & human gate (8)
            CrossrefQuery,
            CrossrefResult,
            HumanRescueRequest,
            HumanRescueResponse,
            SemanticScholarQuery,
            SemanticScholarResult,
            TavilyQuery,
            TavilyResult,
        )
        # Reference every name so linters see them as used.
        imported = [
            CheckpointBackend,
            CitationCheckResult,
            ConfidenceTier,
            RunStatus,
            StepType,
            Verdict,
            IllegalTransitionError,
            validate_status_transition,
            ResearchBrief,
            AppendOnlyList,
            FactoryState,
            CitationCheckEntry,
            CitationEntry,
            CritiqueEntry,
            VerifierOutput,
            HAICardData,
            ProvenanceManifest,
            SealPayload,
            SealedStepReceipt,
            InferenceRecord,
            CrossrefQuery,
            CrossrefResult,
            HumanRescueRequest,
            HumanRescueResponse,
            SemanticScholarQuery,
            SemanticScholarResult,
            TavilyQuery,
            TavilyResult,
        ]
        self.assertEqual(len(imported), 28)


class TestDunderAll(unittest.TestCase):
    """``__all__`` is complete, duplicate-free, and consistent."""

    def test_length_is_28(self) -> None:
        """Exactly 28 names are declared."""
        mod = importlib.import_module(_TYPES_PKG)
        self.assertEqual(len(mod.__all__), 28)

    def test_no_duplicates(self) -> None:
        """No name appears twice."""
        mod = importlib.import_module(_TYPES_PKG)
        self.assertEqual(
            len(mod.__all__),
            len(set(mod.__all__)),
        )

    def test_matches_reference_table(self) -> None:
        """__all__ contains exactly the 28 expected names."""
        mod = importlib.import_module(_TYPES_PKG)
        self.assertEqual(
            set(mod.__all__),
            set(_ALL_SOURCE),
        )

    def test_every_name_is_a_module_attribute(self) -> None:
        """``getattr(types, name)`` works for every entry."""
        mod = importlib.import_module(_TYPES_PKG)
        for name in mod.__all__:
            with self.subTest(name=name):
                self.assertTrue(
                    hasattr(mod, name),
                    f"{name!r} in __all__ but not "
                    f"an attribute of the module",
                )

    def test_no_public_type_missing_from_all(self) -> None:
        """No un-underscored class in the namespace is absent."""
        mod = importlib.import_module(_TYPES_PKG)
        public_types = {
            n for n in dir(mod)
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
    """All six enums are real ``enum.Enum`` subclasses."""

    def test_are_enum_subclasses(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _ENUM_SOURCE:
            with self.subTest(name=name):
                cls = getattr(mod, name)
                self.assertTrue(
                    issubclass(cls, enum.Enum),
                    f"{name} is not an Enum subclass",
                )

    def test_identity_matches_source(self) -> None:
        """Re-export ``is`` the same object as the source."""
        mod = importlib.import_module(_TYPES_PKG)
        src = importlib.import_module(f"{_TYPES_PKG}.enums")
        for name in _ENUM_SOURCE:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(mod, name),
                    getattr(src, name),
                )


class TestPydanticReExports(unittest.TestCase):
    """All five Pydantic models are ``BaseModel`` subclasses."""

    def test_are_basemodel_subclasses(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _PYDANTIC_SOURCE:
            with self.subTest(name=name):
                cls = getattr(mod, name)
                self.assertTrue(
                    issubclass(cls, BaseModel),
                    f"{name} is not a BaseModel subclass",
                )

    def test_identity_matches_source(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name, sub in _PYDANTIC_SOURCE.items():
            with self.subTest(name=name, source=sub):
                src = importlib.import_module(
                    f"{_TYPES_PKG}.{sub}"
                )
                self.assertIs(
                    getattr(mod, name),
                    getattr(src, name),
                )


class TestDataclassReExports(unittest.TestCase):
    """All 14 dataclasses pass ``dataclasses.is_dataclass``."""

    def test_are_dataclasses(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name in _DATACLASS_SOURCE:
            with self.subTest(name=name):
                cls = getattr(mod, name)
                self.assertTrue(
                    dataclasses.is_dataclass(cls),
                    f"{name} is not a dataclass",
                )

    def test_identity_matches_source(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        for name, sub in _DATACLASS_SOURCE.items():
            with self.subTest(name=name, source=sub):
                src = importlib.import_module(
                    f"{_TYPES_PKG}.{sub}"
                )
                self.assertIs(
                    getattr(mod, name),
                    getattr(src, name),
                )


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
    """Each of the seven sub-modules is directly importable."""

    def test_all_seven_submodules(self) -> None:
        for mod_name in _SUBMODULES:
            with self.subTest(module=mod_name):
                mod = importlib.import_module(
                    f"{_TYPES_PKG}.{mod_name}"
                )
                self.assertIsNotNone(mod)


class TestConfigSeparation(unittest.TestCase):
    """``FactoryConfig`` lives in ``config.py``, NOT in ``types/``.

    D-2 §4 defines FactoryConfig as a frozen dataclass in
    ``slop_research_factory.config``.  It must never leak into
    the ``types`` namespace so the two concerns stay separated.
    """

    def test_factory_config_not_in_types_namespace(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertNotIn("FactoryConfig", dir(mod))

    def test_factory_config_not_in_types_all(self) -> None:
        mod = importlib.import_module(_TYPES_PKG)
        self.assertNotIn("FactoryConfig", mod.__all__)

    def test_factory_config_importable_from_config(self) -> None:
        from slop_research_factory.config import FactoryConfig
        self.assertTrue(
            dataclasses.is_dataclass(FactoryConfig),
        )


if __name__ == "__main__":
    unittest.main()
