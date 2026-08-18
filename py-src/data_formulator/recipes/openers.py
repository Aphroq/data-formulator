# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Request-independent Workspace and connector openers for Recipe execution."""

from __future__ import annotations

from pathlib import Path

from data_formulator.datalake.workspace import sanitize_identity_dirname
from data_formulator.datalake.workspace_manager import WorkspaceManager


class WorkspaceOpenError(ValueError):
    """An explicitly scoped Workspace cannot be safely opened."""


class ConnectorOpenError(ValueError):
    """An explicitly scoped connector cannot restore a usable loader."""


class LocalWorkspaceOpener:
    """Open an existing durable local Workspace without Flask or lazy create."""

    def __init__(
        self,
        data_home: Path | str,
        *,
        storage_backend: str = "local",
    ) -> None:
        if storage_backend != "local":
            raise WorkspaceOpenError(
                "Recipe execution currently supports only durable local Workspaces"
            )
        self._data_home = Path(data_home).resolve()

    @classmethod
    def from_environment(cls) -> "LocalWorkspaceOpener":
        import os

        from data_formulator.datalake.workspace import get_data_formulator_home

        return cls(
            get_data_formulator_home(),
            storage_backend=os.getenv("WORKSPACE_BACKEND", "local"),
        )

    def open(self, identity_id: str, workspace_id: str):
        try:
            safe_identity = sanitize_identity_dirname(identity_id)
        except (TypeError, ValueError) as exc:
            raise WorkspaceOpenError("identity_id is invalid") from exc
        if (
            not isinstance(workspace_id, str)
            or not workspace_id.strip()
            or WorkspaceManager._safe_id(workspace_id) != workspace_id
        ):
            raise WorkspaceOpenError("workspace_id is invalid")

        workspaces_root = (
            self._data_home / "users" / safe_identity / "workspaces"
        )
        workspace_path = workspaces_root / workspace_id
        if (
            not workspace_path.is_dir()
            or workspace_path.is_symlink()
            or not workspace_path.resolve().is_relative_to(workspaces_root.resolve())
        ):
            raise WorkspaceOpenError("Workspace does not exist")

        manager = WorkspaceManager(workspaces_root)
        workspace = manager.open_workspace(workspace_id, identity_id)
        capabilities = workspace.storage_capabilities
        if (
            capabilities.storage_backend != "local"
            or not capabilities.durable
            or not capabilities.supports_durable_artifacts
        ):
            raise WorkspaceOpenError("Workspace is not durable local storage")
        return workspace


class ExplicitConnectorOpener:
    """Resolve identity-scoped loaders without request headers or sessions."""

    def __init__(
        self,
        *,
        initialize_registry: bool = True,
        disable_data_connectors: bool = False,
    ) -> None:
        if initialize_registry:
            from data_formulator.data_connector import initialize_data_connectors

            initialize_data_connectors(
                disable_data_connectors=disable_data_connectors
            )

    def open(self, identity_id: str, source_id: str):
        from data_formulator.data_connector import resolve_loader_for_identity

        try:
            return resolve_loader_for_identity(identity_id, source_id)
        except ValueError as exc:
            if "not available" in str(exc):
                raise ConnectorOpenError(
                    "Connector is not available for the requested identity"
                ) from exc
            raise ConnectorOpenError(
                "Connector is not connected with recoverable credentials"
            ) from exc
