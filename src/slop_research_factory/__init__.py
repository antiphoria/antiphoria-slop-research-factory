"""Research factory package; implementation layout per D-9 §3."""

from slop_research_factory.types import (
    FactoryConfig,
    FactoryState,
    ResearchBrief,
    RunStatus,
    Verdict,
    VerifierOutput,
)

__version__ = "0.1.0"

__all__ = [
    "FactoryConfig",
    "FactoryState",
    "ResearchBrief",
    "RunStatus",
    "Verdict",
    "VerifierOutput",
    "__version__",
]
