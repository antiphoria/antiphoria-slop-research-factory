# src/slop_research_factory/workspace/__init__.py

"""Workspace management — directory layout and atomic I/O."""

from slop_research_factory.workspace.manager import (
    WorkspaceError,
    WorkspaceManager,
    WorkspaceNotInitializedError,
)

__all__ = [
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceNotInitializedError",
]
