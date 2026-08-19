# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared SQLite connection and migration ownership for Recipe automation."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AutomationDatabaseError(RuntimeError):
    """The shared automation catalog could not be opened or migrated safely."""


class AutomationDatabase:
    """Own the one SQLite schema used by Recipe and Automation repositories."""

    SCHEMA_VERSION = 3

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = Path(database_path).resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def for_data_home(cls) -> "AutomationDatabase":
        from data_formulator.datalake.workspace import get_data_formulator_home

        return cls(
            get_data_formulator_home() / "automation" / "automation.db"
        )

    @property
    def database_path(self) -> Path:
        return self._database_path

    def connect(self) -> sqlite3.Connection:
        """Open one consistently configured connection to the shared catalog."""
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        connection = self.connect()
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
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM automation_schema_migrations"
                )
            }
            supported = set(range(1, self.SCHEMA_VERSION + 1))
            unexpected = applied - supported
            if unexpected:
                raise AutomationDatabaseError(
                    "Unsupported automation database migration(s): "
                    f"{sorted(unexpected)}"
                )

            highest_applied = max(applied, default=0)
            expected_history = set(range(1, highest_applied + 1))
            if applied != expected_history:
                raise AutomationDatabaseError(
                    "Automation database migration history is not contiguous: "
                    f"{sorted(applied)}"
                )

            migrations = {
                1: self._apply_schema_v1,
                2: self._apply_schema_v2,
                3: self._apply_schema_v3,
            }
            for version in range(highest_applied + 1, self.SCHEMA_VERSION + 1):
                migrations[version](connection)
                connection.execute(
                    """
                    INSERT INTO automation_schema_migrations (version, applied_at)
                    VALUES (?, ?)
                    """,
                    (version, self._now()),
                )
            connection.commit()
        except AutomationDatabaseError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise AutomationDatabaseError(
                "Failed to initialize the automation database"
            ) from exc
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

    @staticmethod
    def _apply_schema_v3(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE schedules (
                schedule_id TEXT PRIMARY KEY,
                identity_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                name TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                timezone TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                next_run_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (schedule_id, identity_id, workspace_id),
                UNIQUE (
                    schedule_id, version_id, identity_id, workspace_id
                ),
                FOREIGN KEY (version_id, identity_id, workspace_id)
                    REFERENCES recipe_versions (
                        version_id, identity_id, workspace_id
                    )
                    ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                identity_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                schedule_id TEXT,
                trigger TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
                scheduled_for TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'queued', 'running', 'succeeded', 'failed',
                        'needs_review', 'cancelled'
                    )
                ),
                attempt_count INTEGER NOT NULL DEFAULT 0
                    CHECK (attempt_count >= 0),
                available_at TEXT NOT NULL,
                lease_owner TEXT,
                lease_token TEXT,
                lease_expires_at TEXT,
                cancel_requested_at TEXT,
                artifact_run_id TEXT,
                artifact_path TEXT,
                manifest_hash TEXT,
                binding_hash TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (run_id, identity_id, workspace_id),
                UNIQUE (schedule_id, scheduled_for),
                CHECK (
                    (trigger = 'scheduled' AND schedule_id IS NOT NULL)
                    OR (trigger = 'manual' AND schedule_id IS NULL)
                ),
                FOREIGN KEY (version_id, identity_id, workspace_id)
                    REFERENCES recipe_versions (
                        version_id, identity_id, workspace_id
                    )
                    ON DELETE RESTRICT,
                FOREIGN KEY (
                    schedule_id, version_id, identity_id, workspace_id
                ) REFERENCES schedules (
                    schedule_id, version_id, identity_id, workspace_id
                ) ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX schedules_due_idx
            ON schedules (enabled, next_run_at, schedule_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX schedules_scope_idx
            ON schedules (identity_id, workspace_id, created_at, schedule_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX runs_claim_idx
            ON runs (status, available_at, lease_expires_at, created_at, run_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX runs_scope_idx
            ON runs (identity_id, workspace_id, created_at, run_id)
            """
        )
        connection.execute(
            """
            CREATE TRIGGER schedules_version_scope_immutable
            BEFORE UPDATE OF version_id, identity_id, workspace_id ON schedules
            WHEN NEW.version_id <> OLD.version_id
                OR NEW.identity_id <> OLD.identity_id
                OR NEW.workspace_id <> OLD.workspace_id
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Schedule version and scope are immutable'
                );
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER schedules_require_published_insert
            BEFORE INSERT ON schedules
            WHEN NOT EXISTS (
                SELECT 1
                FROM recipe_versions
                WHERE version_id = NEW.version_id
                    AND identity_id = NEW.identity_id
                    AND workspace_id = NEW.workspace_id
                    AND status = 'published'
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Schedule requires a published RecipeVersion in the same scope'
                );
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER schedules_require_published_enable
            BEFORE UPDATE OF enabled ON schedules
            WHEN NEW.enabled = 1 AND NOT EXISTS (
                SELECT 1
                FROM recipe_versions
                WHERE version_id = NEW.version_id
                    AND identity_id = NEW.identity_id
                    AND workspace_id = NEW.workspace_id
                    AND status = 'published'
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Schedule requires a published RecipeVersion in the same scope'
                );
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER recipe_versions_block_enabled_schedule_archive
            BEFORE UPDATE OF status ON recipe_versions
            WHEN NEW.status = 'archived'
                AND OLD.status <> 'archived'
                AND EXISTS (
                    SELECT 1
                    FROM schedules
                    WHERE version_id = OLD.version_id
                        AND identity_id = OLD.identity_id
                        AND workspace_id = OLD.workspace_id
                        AND enabled = 1
                )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Enabled Schedule must be disabled before archiving RecipeVersion'
                );
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER runs_schedule_binding_immutable
            BEFORE UPDATE OF schedule_id, version_id, identity_id, workspace_id,
                trigger, scheduled_for ON runs
            WHEN NEW.schedule_id IS NOT OLD.schedule_id
                OR NEW.version_id <> OLD.version_id
                OR NEW.identity_id <> OLD.identity_id
                OR NEW.workspace_id <> OLD.workspace_id
                OR NEW.trigger <> OLD.trigger
                OR NEW.scheduled_for <> OLD.scheduled_for
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Run scheduling identity is immutable'
                );
            END
            """
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
