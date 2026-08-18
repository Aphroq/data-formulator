# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite catalog for Recipe identity and RecipeVersion lifecycle metadata."""

from __future__ import annotations

import sqlite3
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


@dataclass(frozen=True, slots=True)
class LoadedRecipeVersion:
    version: StoredRecipeVersion
    compiled: CompiledRecipe


class RecipeRepository:
    """Own Recipe catalog state while immutable bytes remain in the Workspace."""

    SCHEMA_VERSION = 1

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
            if 1 not in applied:
                self._apply_schema_v1(connection)
                connection.execute(
                    """
                    INSERT INTO automation_schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (1, self._now()),
                )
            unexpected = applied - set(range(1, self.SCHEMA_VERSION + 1))
            if unexpected:
                raise RecipeRepositoryError(
                    f"Unsupported automation database migration(s): {sorted(unexpected)}"
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
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
