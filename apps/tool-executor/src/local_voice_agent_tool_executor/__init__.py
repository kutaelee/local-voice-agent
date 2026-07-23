"""Least-privilege tool executor."""

from .executor import ReadOnlyToolExecutor
from .workspaces import Workspace, WorkspaceAccess, WorkspacePlatform, WorkspaceRegistry

__all__ = [
    "ReadOnlyToolExecutor",
    "Workspace",
    "WorkspaceAccess",
    "WorkspacePlatform",
    "WorkspaceRegistry",
]

__version__ = "0.1.0"
