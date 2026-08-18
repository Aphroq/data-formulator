# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Immutable RecipeSpec and Workflow artifacts in a durable Workspace."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_formulator.datalake.workspace_metadata import WorkspaceLock
from data_formulator.recipes.canonical import canonical_json_bytes
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.lineage import DurableArtifactStorageRequired
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.spec import RecipeSpec
from data_formulator.security.path_safety import ConfinedDir


_RECIPE_ID_PATTERN = re.compile(r"^rcp_[0-9a-f]{64}$")
_VERSION_ID_PATTERN = re.compile(r"^rv_[0-9a-f]{64}$")


class RecipeArtifactError(ValueError):
    """Base class for immutable Recipe artifact failures."""


class RecipeArtifactConflictError(RecipeArtifactError):
    """A content-addressed RecipeVersion already has different bytes."""


class RecipeArtifactCorruptError(RecipeArtifactError):
    """A persisted RecipeVersion cannot be verified."""


@dataclass(frozen=True, slots=True)
class RecipeArtifactReference:
    recipe_id: str
    version_id: str
    recipe_hash: HashDigest
    artifact_path: str
    manifest_hash: HashDigest


@dataclass(frozen=True, slots=True)
class StoredRecipeArtifact:
    compiled: CompiledRecipe
    reference: RecipeArtifactReference


def _write_file(path: Path, content: bytes) -> None:
    with path.open("wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


class RecipeArtifactStore:
    """Publish and verify immutable RecipeVersion directories."""

    STORE_VERSION = 1
    RECIPE_FILENAME = "recipe.json"
    WORKFLOW_FILENAME = "workflow.md"
    MANIFEST_FILENAME = "manifest.json"

    def __init__(
        self,
        root: Path,
        *,
        workspace_root: Path,
        identity_id: str,
        workspace_id: str,
    ) -> None:
        self._workspace_jail = ConfinedDir(workspace_root, mkdir=False)
        try:
            root_relative = os.path.relpath(
                Path(root).resolve(),
                self._workspace_jail.root,
            )
            self._root = self._workspace_jail.resolve(root_relative)
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Recipe artifact root must be inside its Workspace"
            ) from exc
        self._root_relative = Path(root_relative).as_posix()
        self._root_jail = ConfinedDir(self._root)
        self._identity_id = identity_id
        self._workspace_id = workspace_id

    @classmethod
    def for_workspace(cls, workspace) -> "RecipeArtifactStore":
        capabilities = workspace.storage_capabilities
        if not capabilities.durable or not capabilities.supports_durable_artifacts:
            raise DurableArtifactStorageRequired(
                f"Workspace backend {capabilities.storage_backend!r} does not provide "
                "durable Recipe artifact storage"
            )
        workspace_root = workspace.confined_root.root
        root = workspace.confined_root.resolve("artifacts/recipes")
        return cls(
            root,
            workspace_root=workspace_root,
            identity_id=workspace.identity_id,
            workspace_id=workspace.workspace_id,
        )

    @property
    def root(self) -> Path:
        return self._root

    def publish(self, compiled: CompiledRecipe) -> RecipeArtifactReference:
        if not isinstance(compiled, CompiledRecipe):
            raise TypeError("RecipeArtifactStore.publish requires CompiledRecipe")
        self._validate_spec_scope(compiled.spec)

        spec_bytes = compiled.spec.canonical_bytes()
        workflow_bytes = compiled.workflow_markdown.encode("utf-8")
        manifest = self._manifest(compiled.spec, spec_bytes, workflow_bytes)
        manifest_bytes = canonical_json_bytes(manifest)
        desired_reference = self._reference(
            compiled.spec,
            HashDigest.sha256(manifest_bytes),
        )
        version_dir = self._version_dir(
            compiled.spec.recipe_id,
            compiled.spec.version_id,
        )

        with WorkspaceLock(self._root):
            if version_dir.exists():
                stored = self.load(
                    compiled.spec.recipe_id,
                    compiled.spec.version_id,
                )
                if (
                    stored.compiled != compiled
                    or stored.reference != desired_reference
                ):
                    raise RecipeArtifactConflictError(
                        "RecipeVersion artifact is immutable and already differs"
                    )
                return stored.reference

            versions_root = version_dir.parent
            versions_root.mkdir(parents=True, exist_ok=True)
            versions_jail = ConfinedDir(versions_root, mkdir=False)
            temporary_name = Path(
                tempfile.mkdtemp(prefix=".recipe_", dir=versions_root)
            ).name
            temporary = versions_jail.resolve(temporary_name)
            try:
                _write_file(temporary / self.RECIPE_FILENAME, spec_bytes)
                _write_file(temporary / self.WORKFLOW_FILENAME, workflow_bytes)
                _write_file(temporary / self.MANIFEST_FILENAME, manifest_bytes)
                os.replace(temporary, version_dir)
            except Exception:
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)
                raise
        return desired_reference

    def load(
        self,
        recipe_id: str,
        version_id: str,
        *,
        expected_manifest_hash: HashDigest | None = None,
    ) -> StoredRecipeArtifact:
        version_dir = self._version_dir(recipe_id, version_id)
        try:
            if not version_dir.is_dir() or version_dir.is_symlink():
                raise ValueError("RecipeVersion directory is missing or unsafe")
            manifest_bytes = self._safe_read(
                version_dir,
                self.MANIFEST_FILENAME,
            )
            manifest_hash = HashDigest.sha256(manifest_bytes)
            if (
                expected_manifest_hash is not None
                and manifest_hash != expected_manifest_hash
            ):
                raise ValueError("Recipe artifact manifest hash does not match")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            self._verify_manifest_header(manifest, recipe_id, version_id)

            recipe_bytes = self._safe_read(version_dir, self.RECIPE_FILENAME)
            workflow_bytes = self._safe_read(version_dir, self.WORKFLOW_FILENAME)
            self._verify_file(manifest, self.RECIPE_FILENAME, recipe_bytes)
            self._verify_file(manifest, self.WORKFLOW_FILENAME, workflow_bytes)

            spec_payload = json.loads(recipe_bytes.decode("utf-8"))
            spec = RecipeSpec.from_dict(spec_payload)
            self._validate_spec_scope(spec)
            if spec.recipe_id != recipe_id or spec.version_id != version_id:
                raise ValueError("Recipe artifact identifiers do not match its path")
            if manifest["recipe_hash"] != str(spec.recipe_hash):
                raise ValueError("Recipe artifact recipe_hash does not match")
            workflow = workflow_bytes.decode("utf-8")
            compiled = CompiledRecipe(spec=spec, workflow_markdown=workflow)
            reference = self._reference(spec, manifest_hash)
            return StoredRecipeArtifact(compiled=compiled, reference=reference)
        except RecipeArtifactCorruptError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecipeArtifactCorruptError(
                f"RecipeVersion artifact is corrupt: {exc}"
            ) from exc

    def _version_dir(self, recipe_id: str, version_id: str) -> Path:
        if not isinstance(recipe_id, str) or not _RECIPE_ID_PATTERN.fullmatch(recipe_id):
            raise ValueError("recipe_id is invalid")
        if not isinstance(version_id, str) or not _VERSION_ID_PATTERN.fullmatch(version_id):
            raise ValueError("version_id is invalid")
        return self._root_jail.resolve(
            f"{recipe_id}/versions/{version_id}"
        )

    def _reference(
        self,
        spec: RecipeSpec,
        manifest_hash: HashDigest,
    ) -> RecipeArtifactReference:
        artifact_path = (
            f"{self._root_relative}/{spec.recipe_id}/versions/{spec.version_id}"
        )
        return RecipeArtifactReference(
            recipe_id=spec.recipe_id,
            version_id=spec.version_id,
            recipe_hash=spec.recipe_hash,
            artifact_path=artifact_path,
            manifest_hash=manifest_hash,
        )

    def _validate_spec_scope(self, spec: RecipeSpec) -> None:
        if spec.identity_id != self._identity_id:
            raise RecipeArtifactConflictError(
                "Recipe identity does not match artifact store identity"
            )
        if spec.workspace_id != self._workspace_id:
            raise RecipeArtifactConflictError(
                "Recipe workspace does not match artifact store workspace"
            )

    def _manifest(
        self,
        spec: RecipeSpec,
        recipe_bytes: bytes,
        workflow_bytes: bytes,
    ) -> dict[str, Any]:
        return {
            "store_version": self.STORE_VERSION,
            "recipe_id": spec.recipe_id,
            "version_id": spec.version_id,
            "recipe_hash": str(spec.recipe_hash),
            "identity_id": spec.identity_id,
            "workspace_id": spec.workspace_id,
            "files": {
                self.RECIPE_FILENAME: {
                    "hash": str(HashDigest.sha256(recipe_bytes)),
                    "size": len(recipe_bytes),
                },
                self.WORKFLOW_FILENAME: {
                    "hash": str(HashDigest.sha256(workflow_bytes)),
                    "size": len(workflow_bytes),
                },
            },
        }

    def _verify_manifest_header(
        self,
        manifest: Any,
        recipe_id: str,
        version_id: str,
    ) -> None:
        if not isinstance(manifest, Mapping):
            raise ValueError("Recipe artifact manifest must be an object")
        expected_fields = {
            "store_version",
            "recipe_id",
            "version_id",
            "recipe_hash",
            "identity_id",
            "workspace_id",
            "files",
        }
        if set(manifest) != expected_fields:
            raise ValueError("Recipe artifact manifest fields are invalid")
        expected = {
            "store_version": self.STORE_VERSION,
            "recipe_id": recipe_id,
            "version_id": version_id,
            "identity_id": self._identity_id,
            "workspace_id": self._workspace_id,
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise ValueError("Recipe artifact manifest scope does not match")
        files = manifest.get("files")
        if not isinstance(files, Mapping) or set(files) != {
            self.RECIPE_FILENAME,
            self.WORKFLOW_FILENAME,
        }:
            raise ValueError("Recipe artifact manifest files are invalid")

    @staticmethod
    def _verify_file(
        manifest: Mapping[str, Any],
        filename: str,
        content: bytes,
    ) -> None:
        entry = manifest["files"].get(filename)
        if not isinstance(entry, Mapping) or set(entry) != {"hash", "size"}:
            raise ValueError(f"Recipe artifact entry is invalid: {filename}")
        if entry["hash"] != str(HashDigest.sha256(content)):
            raise ValueError(f"Recipe artifact file hash changed: {filename}")
        if entry["size"] != len(content):
            raise ValueError(f"Recipe artifact file size changed: {filename}")

    @staticmethod
    def _safe_read(version_dir: Path, filename: str) -> bytes:
        unresolved = version_dir / filename
        if unresolved.is_symlink():
            raise ValueError(f"Recipe artifact file is unsafe: {filename}")
        path = ConfinedDir(version_dir, mkdir=False).resolve(filename)
        if not path.is_file():
            raise ValueError(f"Recipe artifact file is unsafe: {filename}")
        return path.read_bytes()
