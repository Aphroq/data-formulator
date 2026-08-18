# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite catalog for Recipe identity and RecipeVersion lifecycle metadata."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from data_formulator.recipes.artifact_store import (
    RecipeArtifactError,
    RecipeArtifactStore,
    StoredRecipeArtifact,
)
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.run_store import (
    RecipeRunArtifactError,
    RecipeRunArtifactStore,
    RecipeRunKind,
    RecipeRunReference,
    RecipeRunStatus,
)
from data_formulator.recipes.spec import RecipeSpec


class RecipeRepositoryError(ValueError):
    """Base class for durable Recipe catalog failures."""


class RecipeNotFoundError(RecipeRepositoryError):
    """No Recipe or RecipeVersion exists in the requested scope."""


class RecipeScopeError(RecipeRepositoryError):
    """A Recipe write attempts to cross identity or Workspace scope."""


class RecipeConflictError(RecipeRepositoryError):
    """An immutable catalog identifier already refers to different content."""


class RecipeIntegrityError(RecipeRepositoryError):
    """SQLite metadata and immutable Workspace artifacts diverge."""


class RecipeStateError(RecipeRepositoryError):
    """A requested RecipeVersion lifecycle transition is not allowed."""


class RecipeVersionStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class StoredRecipe:
    recipe_id: str
    identity_id: str
    workspace_id: str
    name: str
    description: str
    created_by: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StoredRecipeVersion:
    version_id: str
    recipe_id: str
    identity_id: str
    workspace_id: str
    recipe_hash: HashDigest
    status: RecipeVersionStatus
    artifact_path: str
    manifest_hash: HashDigest
    created_at: str
    validated_at: str | None
    published_at: str | None
    archived_at: str | None
    validation_run_id: str | None
    validation_manifest_hash: HashDigest | None
    validation_artifact_path: str | None
    validation_binding_hash: HashDigest | None


@dataclass(frozen=True, slots=True)
class LoadedRecipeVersion:
    version: StoredRecipeVersion
    compiled: CompiledRecipe


class RecipeRepository:
    """Own Recipe catalog state while immutable bytes remain in the Workspace."""

    SCHEMA_VERSION = 2

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = Path(database_path).resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def for_data_home(cls) -> "RecipeRepository":
        from data_formulator.datalake.workspace import get_data_formulator_home

        return cls(
            get_data_formulator_home() / "automation" / "automation.db"
        )

    @property
    def database_path(self) -> Path:
        return self._database_path

    def save_draft(
        self,
        workspace,
        compiled: CompiledRecipe,
    ) -> StoredRecipeVersion:
        spec = compiled.spec
        if (
            workspace.identity_id != spec.identity_id
            or workspace.workspace_id != spec.workspace_id
        ):
            raise RecipeScopeError(
                "Recipe scope does not match the destination Workspace"
            )

        reference = RecipeArtifactStore.for_workspace(workspace).publish(compiled)
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            recipe_row = connection.execute(
                "SELECT * FROM recipes WHERE recipe_id = ?",
                (spec.recipe_id,),
            ).fetchone()
            if recipe_row is None:
                connection.execute(
                    """
                    INSERT INTO recipes (
                        recipe_id, identity_id, workspace_id, name, description,
                        created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec.recipe_id,
                        spec.identity_id,
                        spec.workspace_id,
                        spec.name,
                        spec.description,
                        spec.created_by,
                        now,
                        now,
                    ),
                )
            else:
                self._require_row_scope(
                    recipe_row,
                    spec.identity_id,
                    spec.workspace_id,
                )

            version_row = connection.execute(
                "SELECT * FROM recipe_versions WHERE version_id = ?",
                (spec.version_id,),
            ).fetchone()
            if version_row is not None:
                self._require_row_scope(
                    version_row,
                    spec.identity_id,
                    spec.workspace_id,
                )
                stored = self._version_from_row(version_row)
                if (
                    stored.recipe_id != spec.recipe_id
                    or stored.recipe_hash != spec.recipe_hash
                    or stored.artifact_path != reference.artifact_path
                    or stored.manifest_hash != reference.manifest_hash
                ):
                    raise RecipeConflictError(
                        "RecipeVersion id is already bound to different content"
                    )
                connection.commit()
                return stored

            if recipe_row is not None:
                connection.execute(
                    """
                    UPDATE recipes
                    SET name = ?, description = ?, updated_at = ?
                    WHERE recipe_id = ? AND identity_id = ? AND workspace_id = ?
                    """,
                    (
                        spec.name,
                        spec.description,
                        now,
                        spec.recipe_id,
                        spec.identity_id,
                        spec.workspace_id,
                    ),
                )

            connection.execute(
                """
                INSERT INTO recipe_versions (
                    version_id, recipe_id, identity_id, workspace_id,
                    recipe_hash, status, artifact_path, manifest_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.version_id,
                    spec.recipe_id,
                    spec.identity_id,
                    spec.workspace_id,
                    str(spec.recipe_hash),
                    RecipeVersionStatus.DRAFT.value,
                    reference.artifact_path,
                    str(reference.manifest_hash),
                    now,
                ),
            )
            stored_row = connection.execute(
                "SELECT * FROM recipe_versions WHERE version_id = ?",
                (spec.version_id,),
            ).fetchone()
            connection.commit()
            return self._version_from_row(stored_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_version(
        self,
        identity_id: str,
        workspace_id: str,
        version_id: str,
    ) -> StoredRecipeVersion:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM recipe_versions
                WHERE version_id = ? AND identity_id = ? AND workspace_id = ?
                """,
                (version_id, identity_id, workspace_id),
            ).fetchone()
        if row is None:
            raise RecipeNotFoundError("RecipeVersion was not found in this Workspace")
        return self._version_from_row(row)

    def load_version(self, workspace, version_id: str) -> LoadedRecipeVersion:
        version = self.get_version(
            workspace.identity_id,
            workspace.workspace_id,
            version_id,
        )
        try:
            artifact = RecipeArtifactStore.for_workspace(workspace).load(
                version.recipe_id,
                version.version_id,
                expected_manifest_hash=version.manifest_hash,
            )
        except RecipeArtifactError as exc:
            raise RecipeIntegrityError(
                "RecipeVersion artifact reference failed verification"
            ) from exc
        self._verify_artifact_reference(version, artifact)
        return LoadedRecipeVersion(version=version, compiled=artifact.compiled)

    def mark_validated(
        self,
        workspace,
        version_id: str,
        validation_run: RecipeRunReference,
    ) -> StoredRecipeVersion:
        """Advance one draft using a verified, successful dry-run artifact."""
        loaded = self.load_version(workspace, version_id)
        if loaded.compiled.spec.has_unresolved_inputs:
            raise RecipeStateError(
                "RecipeVersion with unresolved inputs cannot be validated"
            )
        self._verify_validation_run(
            workspace,
            loaded.version,
            validation_run,
            loaded.compiled.spec,
        )

        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_version_row(
                connection,
                workspace.identity_id,
                workspace.workspace_id,
                version_id,
            )
            stored = self._version_from_row(row)
            if stored.status is RecipeVersionStatus.VALIDATED:
                if not self._same_validation_evidence(stored, validation_run):
                    raise RecipeConflictError(
                        "RecipeVersion already has different validation evidence"
                    )
                connection.commit()
                return stored
            if stored.status is not RecipeVersionStatus.DRAFT:
                raise RecipeStateError(
                    "Only a draft RecipeVersion can be marked validated"
                )
            connection.execute(
                """
                UPDATE recipe_versions
                SET status = ?, validated_at = ?, validation_run_id = ?,
                    validation_manifest_hash = ?, validation_artifact_path = ?,
                    validation_binding_hash = ?
                WHERE version_id = ? AND identity_id = ? AND workspace_id = ?
                    AND status = ?
                """,
                (
                    RecipeVersionStatus.VALIDATED.value,
                    now,
                    validation_run.run_id,
                    str(validation_run.manifest_hash),
                    validation_run.artifact_path,
                    str(validation_run.binding_hash),
                    version_id,
                    workspace.identity_id,
                    workspace.workspace_id,
                    RecipeVersionStatus.DRAFT.value,
                ),
            )
            updated = self._get_version_row(
                connection,
                workspace.identity_id,
                workspace.workspace_id,
                version_id,
            )
            connection.commit()
            return self._version_from_row(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def publish_version(self, workspace, version_id: str) -> StoredRecipeVersion:
        """Publish a validated immutable RecipeVersion, idempotently."""
        loaded = self.load_version(workspace, version_id)
        version = loaded.version
        if loaded.compiled.spec.has_unresolved_inputs:
            raise RecipeStateError(
                "RecipeVersion with unresolved inputs cannot be published"
            )
        if version.status is RecipeVersionStatus.DRAFT:
            raise RecipeStateError(
                "RecipeVersion must be validated before it can be published"
            )
        if version.status is RecipeVersionStatus.ARCHIVED:
            raise RecipeStateError("Archived RecipeVersion cannot be published")
        validation_run = self._validation_reference(version)
        self._verify_validation_run(
            workspace,
            version,
            validation_run,
            loaded.compiled.spec,
        )
        if version.status is RecipeVersionStatus.PUBLISHED:
            return version

        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_version_row(
                connection,
                workspace.identity_id,
                workspace.workspace_id,
                version_id,
            )
            current = self._version_from_row(row)
            if current.status is RecipeVersionStatus.PUBLISHED:
                connection.commit()
                return current
            if current.status is not RecipeVersionStatus.VALIDATED:
                raise RecipeStateError(
                    "RecipeVersion must be validated before it can be published"
                )
            if not self._same_validation_evidence(current, validation_run):
                raise RecipeIntegrityError(
                    "RecipeVersion validation evidence changed during publication"
                )
            connection.execute(
                """
                UPDATE recipe_versions
                SET status = ?, published_at = ?
                WHERE version_id = ? AND identity_id = ? AND workspace_id = ?
                    AND status = ?
                """,
                (
                    RecipeVersionStatus.PUBLISHED.value,
                    now,
                    version_id,
                    workspace.identity_id,
                    workspace.workspace_id,
                    RecipeVersionStatus.VALIDATED.value,
                ),
            )
            updated = self._get_version_row(
                connection,
                workspace.identity_id,
                workspace.workspace_id,
                version_id,
            )
            connection.commit()
            return self._version_from_row(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def archive_version(self, workspace, version_id: str) -> StoredRecipeVersion:
        """Move a published RecipeVersion into its immutable terminal state."""
        loaded = self.load_version(workspace, version_id)
        if loaded.version.status is RecipeVersionStatus.ARCHIVED:
            return loaded.version
        if loaded.version.status is not RecipeVersionStatus.PUBLISHED:
            raise RecipeStateError(
                "Only a published RecipeVersion can be archived"
            )

        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_version_row(
                connection,
                workspace.identity_id,
                workspace.workspace_id,
                version_id,
            )
            current = self._version_from_row(row)
            if current.status is RecipeVersionStatus.ARCHIVED:
                connection.commit()
                return current
            if current.status is not RecipeVersionStatus.PUBLISHED:
                raise RecipeStateError(
                    "Only a published RecipeVersion can be archived"
                )
            connection.execute(
                """
                UPDATE recipe_versions
                SET status = ?, archived_at = ?
                WHERE version_id = ? AND identity_id = ? AND workspace_id = ?
                    AND status = ?
                """,
                (
                    RecipeVersionStatus.ARCHIVED.value,
                    now,
                    version_id,
                    workspace.identity_id,
                    workspace.workspace_id,
                    RecipeVersionStatus.PUBLISHED.value,
                ),
            )
            updated = self._get_version_row(
                connection,
                workspace.identity_id,
                workspace.workspace_id,
                version_id,
            )
            connection.commit()
            return self._version_from_row(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_recipes(
        self,
        identity_id: str,
        workspace_id: str,
    ) -> tuple[StoredRecipe, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM recipes
                WHERE identity_id = ? AND workspace_id = ?
                ORDER BY updated_at DESC, recipe_id ASC
                """,
                (identity_id, workspace_id),
            ).fetchall()
        return tuple(self._recipe_from_row(row) for row in rows)

    def list_versions(
        self,
        identity_id: str,
        workspace_id: str,
        *,
        recipe_id: str | None = None,
    ) -> tuple[StoredRecipeVersion, ...]:
        """List versions visible in one explicit identity/Workspace scope."""
        query = """
            SELECT * FROM recipe_versions
            WHERE identity_id = ? AND workspace_id = ?
        """
        parameters: list[str] = [identity_id, workspace_id]
        if recipe_id is not None:
            query += " AND recipe_id = ?"
            parameters.append(recipe_id)
        query += " ORDER BY created_at DESC, version_id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._version_from_row(row) for row in rows)

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row[0]
                for row in connection.execute(
                    "SELECT version FROM automation_schema_migrations"
                )
            }
            unexpected = applied - set(range(1, self.SCHEMA_VERSION + 1))
            if unexpected:
                raise RecipeRepositoryError(
                    f"Unsupported automation database migration(s): {sorted(unexpected)}"
                )
            if 1 not in applied:
                self._apply_schema_v1(connection)
                connection.execute(
                    """
                    INSERT INTO automation_schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (1, self._now()),
                )
            if 2 not in applied:
                self._apply_schema_v2(connection)
                connection.execute(
                    """
                    INSERT INTO automation_schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (2, self._now()),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _apply_schema_v1(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE recipes (
                recipe_id TEXT PRIMARY KEY,
                identity_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (recipe_id, identity_id, workspace_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE recipe_versions (
                version_id TEXT PRIMARY KEY,
                recipe_id TEXT NOT NULL,
                identity_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                recipe_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('draft', 'validated', 'published', 'archived')
                ),
                artifact_path TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                validated_at TEXT,
                published_at TEXT,
                archived_at TEXT,
                validation_run_id TEXT,
                validation_manifest_hash TEXT,
                UNIQUE (version_id, identity_id, workspace_id),
                FOREIGN KEY (recipe_id, identity_id, workspace_id)
                    REFERENCES recipes (recipe_id, identity_id, workspace_id)
                    ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX recipe_versions_scope_status_idx
            ON recipe_versions (identity_id, workspace_id, status, created_at)
            """
        )

    @staticmethod
    def _apply_schema_v2(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE recipe_versions ADD COLUMN validation_artifact_path TEXT"
        )
        connection.execute(
            "ALTER TABLE recipe_versions ADD COLUMN validation_binding_hash TEXT"
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _require_row_scope(
        row: sqlite3.Row,
        identity_id: str,
        workspace_id: str,
    ) -> None:
        if row["identity_id"] != identity_id or row["workspace_id"] != workspace_id:
            raise RecipeScopeError("Recipe catalog identifier belongs to another scope")

    def _get_version_row(
        self,
        connection: sqlite3.Connection,
        identity_id: str,
        workspace_id: str,
        version_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM recipe_versions
            WHERE version_id = ? AND identity_id = ? AND workspace_id = ?
            """,
            (version_id, identity_id, workspace_id),
        ).fetchone()
        if row is None:
            raise RecipeNotFoundError(
                "RecipeVersion was not found in this Workspace"
            )
        return row

    @staticmethod
    def _same_validation_evidence(
        version: StoredRecipeVersion,
        reference: RecipeRunReference,
    ) -> bool:
        return (
            version.validation_run_id == reference.run_id
            and version.validation_manifest_hash == reference.manifest_hash
            and version.validation_artifact_path == reference.artifact_path
            and version.validation_binding_hash == reference.binding_hash
        )

    @staticmethod
    def _validation_reference(version: StoredRecipeVersion) -> RecipeRunReference:
        if (
            version.validation_run_id is None
            or version.validation_manifest_hash is None
            or version.validation_artifact_path is None
            or version.validation_binding_hash is None
        ):
            raise RecipeIntegrityError(
                "RecipeVersion validation evidence is incomplete"
            )
        return RecipeRunReference(
            run_id=version.validation_run_id,
            recipe_id=version.recipe_id,
            version_id=version.version_id,
            identity_id=version.identity_id,
            workspace_id=version.workspace_id,
            kind=RecipeRunKind.DRY_RUN,
            status=RecipeRunStatus.SUCCEEDED,
            binding_hash=version.validation_binding_hash,
            artifact_path=version.validation_artifact_path,
            manifest_hash=version.validation_manifest_hash,
        )

    @staticmethod
    def _verify_validation_run(
        workspace,
        version: StoredRecipeVersion,
        reference: RecipeRunReference,
        spec: RecipeSpec,
    ) -> None:
        if not isinstance(reference, RecipeRunReference):
            raise RecipeStateError(
                "Validation requires a successful dry run"
            )
        if (
            reference.kind is not RecipeRunKind.DRY_RUN
            or reference.status is not RecipeRunStatus.SUCCEEDED
        ):
            raise RecipeStateError(
                "Validation requires a successful dry run"
            )
        if (
            reference.recipe_id != version.recipe_id
            or reference.version_id != version.version_id
        ):
            raise RecipeStateError(
                "Validation run does not match the RecipeVersion"
            )
        if (
            reference.identity_id != workspace.identity_id
            or reference.workspace_id != workspace.workspace_id
            or version.identity_id != workspace.identity_id
            or version.workspace_id != workspace.workspace_id
        ):
            raise RecipeScopeError(
                "Validation run does not match the RecipeVersion scope"
            )
        try:
            stored = RecipeRunArtifactStore.for_workspace(workspace).load(reference)
        except RecipeRunArtifactError as exc:
            raise RecipeIntegrityError(
                "RecipeVersion validation run failed verification"
            ) from exc
        if stored.manifest.get("error") is not None:
            raise RecipeIntegrityError(
                "Successful validation run contains an error"
            )
        expected_events = [
            (step.id, step.kind.value, status, step)
            for step in spec.steps
            for status in ("started", "succeeded")
        ]
        if len(stored.events) != len(expected_events):
            raise RecipeIntegrityError(
                "RecipeVersion validation run has incomplete step evidence"
            )
        files = stored.manifest["files"]
        for event, (step_id, kind, status, step) in zip(
            stored.events,
            expected_events,
        ):
            if (
                event.get("step_id") != step_id
                or event.get("kind") != kind
                or event.get("status") != status
            ):
                raise RecipeIntegrityError(
                    "RecipeVersion validation run step evidence does not match"
                )
            if status != "succeeded":
                continue
            details = event.get("details")
            if (
                not isinstance(details, Mapping)
                or details.get("schema_hash") != str(step.expected_schema)
                or details.get("output_path") not in files
            ):
                raise RecipeIntegrityError(
                    "RecipeVersion validation run output evidence does not match"
                )

    @staticmethod
    def _verify_artifact_reference(
        version: StoredRecipeVersion,
        artifact: StoredRecipeArtifact,
    ) -> None:
        reference = artifact.reference
        if (
            reference.recipe_id != version.recipe_id
            or reference.version_id != version.version_id
            or reference.recipe_hash != version.recipe_hash
            or reference.artifact_path != version.artifact_path
            or reference.manifest_hash != version.manifest_hash
        ):
            raise RecipeIntegrityError(
                "RecipeVersion artifact reference does not match catalog metadata"
            )

    @staticmethod
    def _recipe_from_row(row: sqlite3.Row) -> StoredRecipe:
        return StoredRecipe(
            recipe_id=row["recipe_id"],
            identity_id=row["identity_id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row["description"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _version_from_row(row: sqlite3.Row) -> StoredRecipeVersion:
        validation_hash = row["validation_manifest_hash"]
        validation_binding_hash = row["validation_binding_hash"]
        return StoredRecipeVersion(
            version_id=row["version_id"],
            recipe_id=row["recipe_id"],
            identity_id=row["identity_id"],
            workspace_id=row["workspace_id"],
            recipe_hash=HashDigest.parse(row["recipe_hash"]),
            status=RecipeVersionStatus(row["status"]),
            artifact_path=row["artifact_path"],
            manifest_hash=HashDigest.parse(row["manifest_hash"]),
            created_at=row["created_at"],
            validated_at=row["validated_at"],
            published_at=row["published_at"],
            archived_at=row["archived_at"],
            validation_run_id=row["validation_run_id"],
            validation_manifest_hash=(
                HashDigest.parse(validation_hash)
                if validation_hash is not None
                else None
            ),
            validation_artifact_path=row["validation_artifact_path"],
            validation_binding_hash=(
                HashDigest.parse(validation_binding_hash)
                if validation_binding_hash is not None
                else None
            ),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
