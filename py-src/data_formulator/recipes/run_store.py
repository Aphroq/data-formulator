# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Auditable, immutable artifacts for deterministic Recipe executions."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from data_formulator.datalake.workspace import Workspace
from data_formulator.datalake.workspace_metadata import WorkspaceLock
from data_formulator.recipes.binding import BoundRecipe
from data_formulator.recipes.canonical import canonical_json_bytes
from data_formulator.recipes.lineage import DurableArtifactStorageRequired
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.spec import RecipeSpec, RecipeStepKind
from data_formulator.security.path_safety import ConfinedDir


_RUN_ID_PATTERN = re.compile(r"^run_[0-9a-f]{32}$")


class RecipeRunKind(StrEnum):
    DRY_RUN = "dry_run"
    MANUAL = "manual"
    AUTOMATION = "automation"


class RecipeRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


class RecipeRunArtifactError(ValueError):
    """Base class for Recipe run artifact failures."""


class RecipeRunConflictError(RecipeRunArtifactError):
    """A requested run identifier is already in use."""


class RecipeRunCorruptError(RecipeRunArtifactError):
    """A persisted Recipe run cannot be verified."""


@dataclass(frozen=True, slots=True)
class RecipeRunReference:
    run_id: str
    recipe_id: str
    version_id: str
    identity_id: str
    workspace_id: str
    kind: RecipeRunKind
    status: RecipeRunStatus
    binding_hash: HashDigest
    artifact_path: str
    manifest_hash: HashDigest


@dataclass(frozen=True, slots=True)
class StoredRecipeRun:
    reference: RecipeRunReference
    events: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def _write_file(path: Path, content: bytes) -> None:
    with path.open("wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def _write_atomic(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


class RecipeRunWriter:
    """Own one reserved run directory until its final manifest is committed."""

    DESCRIPTOR_FILENAME = "run.json"
    EVENTS_FILENAME = "events.jsonl"
    MANIFEST_FILENAME = "manifest.json"

    def __init__(
        self,
        store: "RecipeRunArtifactStore",
        *,
        run_id: str,
        spec: RecipeSpec,
        bound: BoundRecipe,
        kind: RecipeRunKind,
        run_dir: Path,
    ) -> None:
        self._store = store
        self.run_id = run_id
        self.spec = spec
        self.bound = bound
        self.kind = RecipeRunKind(kind)
        self._run_dir = run_dir
        self._run_jail = ConfinedDir(run_dir, mkdir=False)
        self._finalized = False
        outputs = self._run_jail.resolve("outputs")
        outputs.mkdir()
        self._output_jail = ConfinedDir(outputs, mkdir=False)
        self.workspace = Workspace(
            spec.identity_id,
            workspace_path=self._run_jail.resolve("workspace"),
            workspace_id=spec.workspace_id,
            storage_backend="recipe_run",
            durable=True,
            supports_durable_artifacts=False,
        )
        descriptor = {
            "store_version": store.STORE_VERSION,
            "run_id": run_id,
            "recipe_id": spec.recipe_id,
            "version_id": spec.version_id,
            "identity_id": spec.identity_id,
            "workspace_id": spec.workspace_id,
            "kind": self.kind.value,
            "binding_hash": str(bound.binding_hash),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_file(
            self._run_jail.resolve(self.DESCRIPTOR_FILENAME),
            canonical_json_bytes(descriptor),
        )
        _write_file(self._run_jail.resolve(self.EVENTS_FILENAME), b"")

    @property
    def root(self) -> Path:
        return self._run_dir

    def output_path(self, filename: str) -> Path:
        return self._output_jail.resolve(filename, mkdir_parents=True)

    def append_event(
        self,
        *,
        step_id: str,
        kind: RecipeStepKind,
        status: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if self._finalized:
            raise RecipeRunArtifactError("Recipe run is already finalized")
        event: dict[str, Any] = {
            "sequence": self._event_count(),
            "step_id": step_id,
            "kind": RecipeStepKind(kind).value,
            "status": status,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if details:
            event["details"] = dict(details)
        encoded = canonical_json_bytes(event) + b"\n"
        with self._run_jail.resolve(self.EVENTS_FILENAME).open("ab") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())

    def finalize(
        self,
        status: RecipeRunStatus,
        *,
        error: Mapping[str, str] | None = None,
    ) -> RecipeRunReference:
        if self._finalized:
            raise RecipeRunArtifactError("Recipe run is already finalized")
        status = RecipeRunStatus(status)
        manifest = {
            "store_version": self._store.STORE_VERSION,
            "run_id": self.run_id,
            "recipe_id": self.spec.recipe_id,
            "version_id": self.spec.version_id,
            "identity_id": self.spec.identity_id,
            "workspace_id": self.spec.workspace_id,
            "kind": self.kind.value,
            "status": status.value,
            "binding_hash": str(self.bound.binding_hash),
            "error": dict(error) if error is not None else None,
            "files": self._store._file_manifest(self._run_dir),
        }
        manifest_bytes = canonical_json_bytes(manifest)
        _write_atomic(
            self._run_jail.resolve(self.MANIFEST_FILENAME),
            manifest_bytes,
        )
        manifest_hash = HashDigest.sha256(manifest_bytes)
        self._finalized = True
        return self._store._reference(
            self.spec,
            run_id=self.run_id,
            kind=self.kind,
            status=status,
            binding_hash=self.bound.binding_hash,
            manifest_hash=manifest_hash,
        )

    def _event_count(self) -> int:
        path = self._run_jail.resolve(self.EVENTS_FILENAME)
        with path.open("rb") as file:
            return sum(1 for line in file if line.strip())


class RecipeRunArtifactStore:
    """Create and verify immutable run directories inside a Workspace."""

    STORE_VERSION = 1
    DESCRIPTOR_FILENAME = RecipeRunWriter.DESCRIPTOR_FILENAME
    EVENTS_FILENAME = RecipeRunWriter.EVENTS_FILENAME
    MANIFEST_FILENAME = RecipeRunWriter.MANIFEST_FILENAME

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
            raise ValueError("Recipe run root must be inside its Workspace") from exc
        self._root_relative = Path(root_relative).as_posix()
        self._root_jail = ConfinedDir(self._root)
        self._identity_id = identity_id
        self._workspace_id = workspace_id

    @classmethod
    def for_workspace(cls, workspace) -> "RecipeRunArtifactStore":
        capabilities = workspace.storage_capabilities
        if not capabilities.durable or not capabilities.supports_durable_artifacts:
            raise DurableArtifactStorageRequired(
                f"Workspace backend {capabilities.storage_backend!r} does not provide "
                "durable Recipe run storage"
            )
        workspace_root = workspace.confined_root.root
        return cls(
            workspace.confined_root.resolve("artifacts/recipe-runs"),
            workspace_root=workspace_root,
            identity_id=workspace.identity_id,
            workspace_id=workspace.workspace_id,
        )

    @property
    def root(self) -> Path:
        return self._root

    def begin(
        self,
        spec: RecipeSpec,
        bound: BoundRecipe,
        kind: RecipeRunKind,
        *,
        run_id: str | None = None,
    ) -> RecipeRunWriter:
        self._validate_spec_scope(spec)
        if bound.version_id != spec.version_id:
            raise RecipeRunConflictError("Bound RecipeVersion does not match the run")
        resolved_run_id = run_id or f"run_{uuid.uuid4().hex}"
        self._validate_run_id(resolved_run_id)
        run_dir = self._run_dir(resolved_run_id)
        with WorkspaceLock(self._root):
            try:
                run_dir.mkdir()
            except FileExistsError as exc:
                raise RecipeRunConflictError(
                    f"Recipe run already exists: {resolved_run_id}"
                ) from exc
        try:
            return RecipeRunWriter(
                self,
                run_id=resolved_run_id,
                spec=spec,
                bound=bound,
                kind=RecipeRunKind(kind),
                run_dir=run_dir,
            )
        except Exception:
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
            raise

    def load(self, reference: RecipeRunReference) -> StoredRecipeRun:
        if not isinstance(reference, RecipeRunReference):
            raise TypeError("RecipeRunArtifactStore.load requires a run reference")
        run_dir = self._run_dir(reference.run_id)
        try:
            expected_path = f"{self._root_relative}/{reference.run_id}"
            if reference.artifact_path != expected_path:
                raise ValueError("Recipe run artifact path does not match its id")
            if reference.identity_id != self._identity_id:
                raise ValueError("Recipe run identity scope does not match")
            if reference.workspace_id != self._workspace_id:
                raise ValueError("Recipe run workspace scope does not match")
            if not run_dir.is_dir() or run_dir.is_symlink():
                raise ValueError("Recipe run directory is missing or unsafe")

            manifest_bytes = self._safe_read(run_dir, self.MANIFEST_FILENAME)
            manifest_hash = HashDigest.sha256(manifest_bytes)
            if manifest_hash != reference.manifest_hash:
                raise ValueError("Recipe run manifest hash does not match")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            self._verify_manifest_header(manifest, reference)
            self._verify_files(run_dir, manifest)
            self._verify_descriptor(run_dir, reference)
            events = self._read_events(run_dir)
            return StoredRecipeRun(
                reference=reference,
                events=events,
                manifest=dict(manifest),
            )
        except RecipeRunCorruptError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecipeRunCorruptError(f"Recipe run artifact is corrupt: {exc}") from exc

    def _reference(
        self,
        spec: RecipeSpec,
        *,
        run_id: str,
        kind: RecipeRunKind,
        status: RecipeRunStatus,
        binding_hash: HashDigest,
        manifest_hash: HashDigest,
    ) -> RecipeRunReference:
        return RecipeRunReference(
            run_id=run_id,
            recipe_id=spec.recipe_id,
            version_id=spec.version_id,
            identity_id=spec.identity_id,
            workspace_id=spec.workspace_id,
            kind=kind,
            status=status,
            binding_hash=binding_hash,
            artifact_path=f"{self._root_relative}/{run_id}",
            manifest_hash=manifest_hash,
        )

    def _run_dir(self, run_id: str) -> Path:
        self._validate_run_id(run_id)
        return self._root_jail.resolve(run_id)

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id is invalid")

    def _validate_spec_scope(self, spec: RecipeSpec) -> None:
        if spec.identity_id != self._identity_id:
            raise RecipeRunConflictError(
                "Recipe identity does not match run store identity"
            )
        if spec.workspace_id != self._workspace_id:
            raise RecipeRunConflictError(
                "Recipe workspace does not match run store workspace"
            )

    def _file_manifest(self, run_dir: Path) -> dict[str, dict[str, Any]]:
        files: dict[str, dict[str, Any]] = {}
        for path in sorted(run_dir.rglob("*")):
            if path.is_symlink():
                raise RecipeRunArtifactError("Recipe run contains an unsafe symlink")
            if (
                not path.is_file()
                or path == run_dir / self.MANIFEST_FILENAME
            ):
                continue
            relative = path.relative_to(run_dir).as_posix()
            files[relative] = {
                "hash": str(HashDigest.sha256_file(path)),
                "size": path.stat().st_size,
            }
        return files

    def _verify_manifest_header(
        self,
        manifest: Any,
        reference: RecipeRunReference,
    ) -> None:
        if not isinstance(manifest, Mapping):
            raise ValueError("Recipe run manifest must be an object")
        expected_fields = {
            "store_version",
            "run_id",
            "recipe_id",
            "version_id",
            "identity_id",
            "workspace_id",
            "kind",
            "status",
            "binding_hash",
            "error",
            "files",
        }
        if set(manifest) != expected_fields:
            raise ValueError("Recipe run manifest fields are invalid")
        expected = {
            "store_version": self.STORE_VERSION,
            "run_id": reference.run_id,
            "recipe_id": reference.recipe_id,
            "version_id": reference.version_id,
            "identity_id": reference.identity_id,
            "workspace_id": reference.workspace_id,
            "kind": reference.kind.value,
            "status": reference.status.value,
            "binding_hash": str(reference.binding_hash),
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise ValueError("Recipe run manifest scope does not match")
        if not isinstance(manifest.get("files"), Mapping):
            raise ValueError("Recipe run manifest files are invalid")
        error = manifest.get("error")
        if reference.status in {
            RecipeRunStatus.SUCCEEDED,
            RecipeRunStatus.CANCELLED,
        }:
            if error is not None:
                raise ValueError(
                    "Successful or cancelled Recipe run cannot contain an error"
                )
        elif (
            not isinstance(error, Mapping)
            or set(error) != {"code", "exception_type", "message"}
            or any(not isinstance(value, str) for value in error.values())
        ):
            raise ValueError("Failed Recipe run error is invalid")

    def _verify_files(self, run_dir: Path, manifest: Mapping[str, Any]) -> None:
        actual = self._file_manifest(run_dir)
        declared = manifest["files"]
        if set(actual) != set(declared):
            raise ValueError("Recipe run manifest file set changed")
        for filename, actual_entry in actual.items():
            entry = declared.get(filename)
            if not isinstance(entry, Mapping) or set(entry) != {"hash", "size"}:
                raise ValueError(f"Recipe run file entry is invalid: {filename}")
            if entry["hash"] != actual_entry["hash"]:
                raise ValueError(f"Recipe run file hash changed: {filename}")
            if entry["size"] != actual_entry["size"]:
                raise ValueError(f"Recipe run file size changed: {filename}")

    def _verify_descriptor(
        self,
        run_dir: Path,
        reference: RecipeRunReference,
    ) -> None:
        descriptor = json.loads(
            self._safe_read(run_dir, self.DESCRIPTOR_FILENAME).decode("utf-8")
        )
        expected_fields = {
            "store_version",
            "run_id",
            "recipe_id",
            "version_id",
            "identity_id",
            "workspace_id",
            "kind",
            "binding_hash",
            "created_at",
        }
        if not isinstance(descriptor, Mapping) or set(descriptor) != expected_fields:
            raise ValueError("Recipe run descriptor fields are invalid")
        expected = {
            "store_version": self.STORE_VERSION,
            "run_id": reference.run_id,
            "recipe_id": reference.recipe_id,
            "version_id": reference.version_id,
            "identity_id": reference.identity_id,
            "workspace_id": reference.workspace_id,
            "kind": reference.kind.value,
            "binding_hash": str(reference.binding_hash),
        }
        if any(descriptor.get(key) != value for key, value in expected.items()):
            raise ValueError("Recipe run descriptor scope does not match")
        created_at = datetime.fromisoformat(str(descriptor["created_at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Recipe run descriptor timestamp must include timezone")

    def _read_events(self, run_dir: Path) -> tuple[dict[str, Any], ...]:
        events: list[dict[str, Any]] = []
        content = self._safe_read(run_dir, self.EVENTS_FILENAME)
        for index, line in enumerate(content.splitlines()):
            if not line:
                continue
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict) or event.get("sequence") != index:
                raise ValueError("Recipe run event sequence is invalid")
            events.append(event)
        return tuple(events)

    @staticmethod
    def _safe_read(run_dir: Path, relative: str) -> bytes:
        unresolved = run_dir / relative
        if unresolved.is_symlink():
            raise ValueError(f"Recipe run file is unsafe: {relative}")
        path = ConfinedDir(run_dir, mkdir=False).resolve(relative)
        if not path.is_file():
            raise ValueError(f"Recipe run file is unsafe: {relative}")
        return path.read_bytes()
