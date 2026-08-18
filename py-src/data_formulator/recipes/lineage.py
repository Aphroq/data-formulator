# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Durable, workspace-scoped artifact lineage ledger."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from data_formulator.datalake.workspace_metadata import WorkspaceLock
from data_formulator.recipes.canonical import canonical_json_bytes
from data_formulator.recipes.models import ArtifactNode

if TYPE_CHECKING:
    from data_formulator.datalake.workspace import Workspace


class ArtifactLineageError(ValueError):
    """Base class for invalid or corrupt lineage state."""


class ArtifactConflictError(ArtifactLineageError):
    """A stable origin was already bound to a different artifact."""


class ArtifactScopeError(ArtifactLineageError):
    """An artifact belongs to another identity or workspace."""


class DurableArtifactStorageRequired(ArtifactLineageError):
    """The workspace backend cannot safely retain recipe provenance."""


class ArtifactLedger:
    """Append-only artifact nodes stored below a durable local workspace."""

    STORE_VERSION = 1
    STORE_FILENAME = "lineage.json"

    def __init__(self, root: Path, *, identity_id: str, workspace_id: str):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._identity_id = identity_id
        self._workspace_id = workspace_id
        self._storage_path = self._root / self.STORE_FILENAME
        self._read_unlocked()

    @classmethod
    def for_workspace(cls, workspace: "Workspace") -> "ArtifactLedger":
        capabilities = workspace.storage_capabilities
        if not capabilities.durable or not capabilities.supports_durable_artifacts:
            raise DurableArtifactStorageRequired(
                f"Workspace backend {capabilities.storage_backend!r} does not provide "
                "durable artifact storage"
            )

        root = workspace.confined_root.resolve("artifacts/lineage")
        return cls(
            root,
            identity_id=workspace.identity_id,
            workspace_id=workspace.workspace_id,
        )

    @property
    def root(self) -> Path:
        return self._root

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def list_nodes(self) -> tuple[ArtifactNode, ...]:
        return self._read_unlocked()

    def get(self, artifact_id: str) -> ArtifactNode | None:
        return next(
            (node for node in self._read_unlocked() if node.artifact_id == artifact_id),
            None,
        )

    def get_by_origin(self, origin_id: str) -> ArtifactNode | None:
        return next(
            (node for node in self._read_unlocked() if node.origin_id == origin_id),
            None,
        )

    def record(self, node: ArtifactNode) -> ArtifactNode:
        return self.record_many((node,))[0]

    def record_many(self, nodes: Iterable[ArtifactNode]) -> tuple[ArtifactNode, ...]:
        pending = tuple(nodes)
        if not pending:
            return ()
        if any(not isinstance(node, ArtifactNode) for node in pending):
            raise TypeError("ArtifactLedger only records ArtifactNode values")

        with WorkspaceLock(self._root):
            existing = list(self._read_unlocked())
            merged, recorded = self._merge(existing, pending)
            if len(merged) != len(existing):
                self._write_unlocked(merged)
            return recorded

    def _merge(
        self,
        existing: list[ArtifactNode],
        pending: tuple[ArtifactNode, ...],
    ) -> tuple[list[ArtifactNode], tuple[ArtifactNode, ...]]:
        by_id = {node.artifact_id: node for node in existing}
        by_origin = {node.origin_id: node for node in existing}
        pending_ids = {node.artifact_id for node in pending}
        merged = list(existing)
        recorded: list[ArtifactNode] = []

        for node in pending:
            self._validate_scope(node)

        for node in pending:
            stored_by_id = by_id.get(node.artifact_id)
            if stored_by_id is not None:
                if stored_by_id.identity_payload() != node.identity_payload():
                    raise ArtifactConflictError(
                        f"Artifact id {node.artifact_id!r} has conflicting content"
                    )
                recorded.append(stored_by_id)
                continue

            stored_by_origin = by_origin.get(node.origin_id)
            if stored_by_origin is not None:
                raise ArtifactConflictError(
                    f"Artifact origin {node.origin_id!r} is already bound to "
                    f"{stored_by_origin.artifact_id!r}"
                )

            missing_parents = [
                parent_id
                for parent_id in node.parent_ids
                if parent_id not in by_id and parent_id not in pending_ids
            ]
            if missing_parents:
                raise ArtifactLineageError(
                    f"Artifact {node.artifact_id!r} has missing parent(s): {missing_parents}"
                )

            merged.append(node)
            by_id[node.artifact_id] = node
            by_origin[node.origin_id] = node
            recorded.append(node)

        return merged, tuple(recorded)

    def _validate_scope(self, node: ArtifactNode) -> None:
        if node.identity_id != self._identity_id:
            raise ArtifactScopeError(
                f"Artifact identity {node.identity_id!r} does not match ledger identity "
                f"{self._identity_id!r}"
            )
        if node.workspace_id != self._workspace_id:
            raise ArtifactScopeError(
                f"Artifact workspace {node.workspace_id!r} does not match ledger workspace "
                f"{self._workspace_id!r}"
            )

    def _read_unlocked(self) -> tuple[ArtifactNode, ...]:
        if not self._storage_path.exists():
            return ()
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("root must be an object")
            if payload.get("version") != self.STORE_VERSION:
                raise ValueError(f"unsupported store version {payload.get('version')!r}")
            if payload.get("identity_id") != self._identity_id:
                raise ValueError("identity scope does not match ledger")
            if payload.get("workspace_id") != self._workspace_id:
                raise ValueError("workspace scope does not match ledger")
            serialized = payload.get("artifacts")
            if not isinstance(serialized, list):
                raise ValueError("artifacts must be an array")
            nodes = tuple(ArtifactNode.from_dict(item) for item in serialized)
            self._validate_loaded_nodes(nodes)
            return nodes
        except ArtifactLineageError:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactLineageError(
                f"Artifact ledger is corrupt: {exc}"
            ) from exc

    def _validate_loaded_nodes(self, nodes: tuple[ArtifactNode, ...]) -> None:
        by_id: dict[str, ArtifactNode] = {}
        origins: set[str] = set()
        for node in nodes:
            self._validate_scope(node)
            if node.artifact_id in by_id:
                raise ValueError(f"duplicate artifact id {node.artifact_id!r}")
            if node.origin_id in origins:
                raise ValueError(f"duplicate artifact origin {node.origin_id!r}")
            by_id[node.artifact_id] = node
            origins.add(node.origin_id)

        known_ids = set(by_id)
        for node in nodes:
            missing = set(node.parent_ids) - known_ids
            if missing:
                raise ValueError(
                    f"artifact {node.artifact_id!r} has missing parents {sorted(missing)}"
                )

    def _write_unlocked(self, nodes: list[ArtifactNode]) -> None:
        payload: dict[str, Any] = {
            "version": self.STORE_VERSION,
            "identity_id": self._identity_id,
            "workspace_id": self._workspace_id,
            "artifacts": [node.to_dict() for node in nodes],
        }
        file_descriptor, temp_path = tempfile.mkstemp(
            dir=self._root,
            prefix=".lineage_",
            suffix=".json.tmp",
        )
        try:
            with os.fdopen(file_descriptor, "wb") as file:
                file.write(canonical_json_bytes(payload))
                file.write(b"\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self._storage_path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
