# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite repository for fixed-version Schedules and durable queued Runs."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from data_formulator.automation.db import AutomationDatabase
from data_formulator.automation.models import (
    AutomationRunStatus,
    AutomationRunTrigger,
    StoredAutomationRun,
    StoredSchedule,
    normalize_cron_expression,
    normalize_timezone_name,
    normalize_utc_datetime,
    validate_run_id,
    validate_schedule_id,
)
from data_formulator.recipes.models import HashDigest


class AutomationRepositoryError(ValueError):
    """Base class for durable Schedule and Run catalog failures."""


class AutomationNotFoundError(AutomationRepositoryError):
    """The requested Schedule, Run, or RecipeVersion does not exist."""


class AutomationScopeError(AutomationRepositoryError):
    """An Automation operation crossed an identity or Workspace scope."""


class AutomationConflictError(AutomationRepositoryError):
    """An immutable Automation identifier is already in use."""


class AutomationStateError(AutomationRepositoryError):
    """An Automation state transition is not allowed."""


class AutomationRepository:
    """Persist Schedules and logical Runs in the shared automation database."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._database = AutomationDatabase(database_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid4

    @classmethod
    def for_data_home(cls) -> "AutomationRepository":
        from data_formulator.datalake.workspace import get_data_formulator_home

        return cls(
            get_data_formulator_home() / "automation" / "automation.db"
        )

    @property
    def database_path(self) -> Path:
        return self._database.database_path

    def create_schedule(
        self,
        *,
        identity_id: str,
        workspace_id: str,
        version_id: str,
        name: str,
        cron_expression: str,
        timezone_name: str,
        next_run_at: datetime,
        schedule_id: str | None = None,
    ) -> StoredSchedule:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        version_id = self._require_identifier(version_id, "version_id")
        normalized_name = self._require_name(name)
        normalized_cron = normalize_cron_expression(cron_expression)
        normalized_timezone = normalize_timezone_name(timezone_name)
        normalized_next_run = normalize_utc_datetime(
            next_run_at,
            field_name="next_run_at",
        )
        normalized_schedule_id = validate_schedule_id(
            schedule_id or f"sch_{self._id_factory().hex}"
        )
        now = self._now()

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_published_version(
                connection,
                identity_id,
                workspace_id,
                version_id,
            )
            try:
                connection.execute(
                    """
                    INSERT INTO schedules (
                        schedule_id, identity_id, workspace_id, version_id,
                        name, cron_expression, timezone, enabled,
                        next_run_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        normalized_schedule_id,
                        identity_id,
                        workspace_id,
                        version_id,
                        normalized_name,
                        normalized_cron,
                        normalized_timezone,
                        normalized_next_run,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if connection.execute(
                    "SELECT 1 FROM schedules WHERE schedule_id = ?",
                    (normalized_schedule_id,),
                ).fetchone() is not None:
                    raise AutomationConflictError(
                        "schedule_id is already bound to another Schedule"
                    ) from exc
                raise AutomationRepositoryError(
                    "Schedule could not be persisted safely"
                ) from exc
            row = connection.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (normalized_schedule_id,),
            ).fetchone()
            connection.commit()
            return self._schedule_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_schedule_enabled(
        self,
        identity_id: str,
        workspace_id: str,
        schedule_id: str,
        *,
        enabled: bool,
    ) -> StoredSchedule:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        schedule_id = validate_schedule_id(schedule_id)
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool")

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_schedule_row(
                connection,
                identity_id,
                workspace_id,
                schedule_id,
            )
            current = self._schedule_from_row(row)
            if current.enabled is enabled:
                connection.commit()
                return current
            if enabled:
                self._require_published_version(
                    connection,
                    identity_id,
                    workspace_id,
                    current.version_id,
                )
            connection.execute(
                """
                UPDATE schedules
                SET enabled = ?, updated_at = ?
                WHERE schedule_id = ?
                    AND identity_id = ? AND workspace_id = ?
                """,
                (
                    int(enabled),
                    self._now(),
                    schedule_id,
                    identity_id,
                    workspace_id,
                ),
            )
            updated = self._get_schedule_row(
                connection,
                identity_id,
                workspace_id,
                schedule_id,
            )
            connection.commit()
            return self._schedule_from_row(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enqueue_scheduled_run(
        self,
        identity_id: str,
        workspace_id: str,
        schedule_id: str,
        *,
        scheduled_for: datetime,
    ) -> StoredAutomationRun:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        schedule_id = validate_schedule_id(schedule_id)
        normalized_scheduled_for = normalize_utc_datetime(
            scheduled_for,
            field_name="scheduled_for",
        )

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            schedule_row = self._get_schedule_row(
                connection,
                identity_id,
                workspace_id,
                schedule_id,
            )
            existing = connection.execute(
                """
                SELECT * FROM runs
                WHERE schedule_id = ? AND scheduled_for = ?
                    AND identity_id = ? AND workspace_id = ?
                """,
                (
                    schedule_id,
                    normalized_scheduled_for,
                    identity_id,
                    workspace_id,
                ),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return self._run_from_row(existing)

            schedule = self._schedule_from_row(schedule_row)
            if not schedule.enabled:
                raise AutomationStateError(
                    "A disabled Schedule cannot enqueue a new Run"
                )
            self._require_published_version(
                connection,
                identity_id,
                workspace_id,
                schedule.version_id,
            )
            run_id = validate_run_id(f"run_{self._id_factory().hex}")
            now = self._now()
            try:
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, identity_id, workspace_id, version_id,
                        schedule_id, trigger, scheduled_for, status,
                        attempt_count, available_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                    ON CONFLICT(schedule_id, scheduled_for) DO NOTHING
                    """,
                    (
                        run_id,
                        identity_id,
                        workspace_id,
                        schedule.version_id,
                        schedule_id,
                        AutomationRunTrigger.SCHEDULED.value,
                        normalized_scheduled_for,
                        AutomationRunStatus.QUEUED.value,
                        now,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AutomationConflictError(
                    "run_id is already bound to another Run"
                ) from exc
            row = connection.execute(
                """
                SELECT * FROM runs
                WHERE schedule_id = ? AND scheduled_for = ?
                """,
                (schedule_id, normalized_scheduled_for),
            ).fetchone()
            if row is None:
                raise AutomationRepositoryError(
                    "Scheduled Run enqueue did not produce a durable row"
                )
            connection.commit()
            return self._run_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _require_identifier(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")
        return value

    @staticmethod
    def _require_name(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("name must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be empty")
        return normalized

    @staticmethod
    def _require_published_version(
        connection: sqlite3.Connection,
        identity_id: str,
        workspace_id: str,
        version_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM recipe_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise AutomationNotFoundError("RecipeVersion was not found")
        if (
            row["identity_id"] != identity_id
            or row["workspace_id"] != workspace_id
        ):
            raise AutomationScopeError(
                "RecipeVersion belongs to another identity or Workspace scope"
            )
        if row["status"] != "published":
            if row["status"] == "archived":
                raise AutomationStateError(
                    "Schedule cannot be enabled because its RecipeVersion is archived"
                )
            raise AutomationStateError(
                "Schedule requires a published RecipeVersion"
            )
        return row

    @staticmethod
    def _get_schedule_row(
        connection: sqlite3.Connection,
        identity_id: str,
        workspace_id: str,
        schedule_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM schedules WHERE schedule_id = ?",
            (schedule_id,),
        ).fetchone()
        if row is None:
            raise AutomationNotFoundError("Schedule was not found")
        if (
            row["identity_id"] != identity_id
            or row["workspace_id"] != workspace_id
        ):
            raise AutomationScopeError(
                "Schedule belongs to another identity or Workspace scope"
            )
        return row

    @staticmethod
    def _schedule_from_row(row: sqlite3.Row) -> StoredSchedule:
        return StoredSchedule(
            schedule_id=row["schedule_id"],
            identity_id=row["identity_id"],
            workspace_id=row["workspace_id"],
            version_id=row["version_id"],
            name=row["name"],
            cron_expression=row["cron_expression"],
            timezone=row["timezone"],
            enabled=bool(row["enabled"]),
            next_run_at=row["next_run_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> StoredAutomationRun:
        manifest_hash = row["manifest_hash"]
        binding_hash = row["binding_hash"]
        return StoredAutomationRun(
            run_id=row["run_id"],
            identity_id=row["identity_id"],
            workspace_id=row["workspace_id"],
            version_id=row["version_id"],
            schedule_id=row["schedule_id"],
            trigger=AutomationRunTrigger(row["trigger"]),
            scheduled_for=row["scheduled_for"],
            status=AutomationRunStatus(row["status"]),
            attempt_count=row["attempt_count"],
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            cancel_requested_at=row["cancel_requested_at"],
            artifact_run_id=row["artifact_run_id"],
            artifact_path=row["artifact_path"],
            manifest_hash=(
                HashDigest.parse(manifest_hash)
                if manifest_hash is not None
                else None
            ),
            binding_hash=(
                HashDigest.parse(binding_hash)
                if binding_hash is not None
                else None
            ),
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _now(self) -> str:
        return normalize_utc_datetime(self._clock(), field_name="clock")
