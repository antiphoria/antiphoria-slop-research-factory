"""High-level ``seal_step`` wrapper — implemented in the seal product layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slop_research_factory.types.enums import StepType
    from slop_research_factory.types.state import FactoryState

__all__ = ["seal_step"]


async def seal_step(
    *,
    seal_engine: object,
    state: FactoryState,
    step_type: StepType,
    content_file_paths: list[str],
    metadata: dict[str, Any],
    chain_dir: str,
) -> tuple[FactoryState, object]:
    """Append one PRE- or POST-seal step; update ``state`` with new hash.

    Real implementation is owned by the slop-seal / orchestration
    integration.  The default in this package raises so accidentally
    running an unpatched build fails loudly.
    """
    msg = (
        "seal_step is not available in the base `slop_research_factory` "
        "package; wire the seal engine from the antiphoria/slop-seal "
        "integration, or use the test suite's ``seal_step`` stub."
    )
    raise NotImplementedError(msg)
