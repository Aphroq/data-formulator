# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SQLite repository for fixed-version Schedules and durable queued Runs."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID, uuid4

from data_formulator.automation.cron import CronExpression, next_cron_occurrence
from data_formulator.automation.db import AutomationDatabase
from data_formulator.automation.models import (
    AutomationRunStatus,
    AutomationRunTrigger,
    StoredAutomationRun,
    StoredSchedule,
    normalize_cron_expression,
    normalize_timezone_name,
    normalize_utc_datetime,
    parse_utc_datetime,
    validate_run_id,
    validate_schedule_id,
)
from data_formulator.automation.parameters import (
    deserialize_parameter_mapping,
    resolve_schedule_parameter_policy,
    serialize_parameter_mapping,
)
from data_formulator.recipes.models import HashDigest
from data_formulator.security.sanitize import sanitize_error_message


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


class AutomationLeaseError(AutomationStateError):
    """A Worker lease is expired or fails its fencing checks."""


class AutomationRepository:
    """Persist Schedules and logical Runs in the shared automation database."""

    MAX_ATTEMPTS = 3

    def __init__(
        self,
        database_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._database = AutomationDatabase(database_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid4
        self._token_factory = token_factory or (
            lambda: secrets.token_urlsafe(32)
        )

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
        parameter_policy: Mapping[str, object] | None = None,
        next_run_at: datetime | None = None,
        schedule_id: str | None = None,
    ) -> StoredSchedule:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        version_id = self._require_identifier(version_id, "version_id")
        normalized_name = self._require_name(name)
        normalized_cron = normalize_cron_expression(cron_expression)
        CronExpression.parse(normalized_cron)
        normalized_timezone = normalize_timezone_name(timezone_name)
        normalized_parameter_policy = serialize_parameter_mapping(
            parameter_policy or {},
            field_name="parameter_policy",
        )
        if next_run_at is None:
            next_run_at = next_cron_occurrence(
                normalized_cron,
                normalized_timezone,
                self._clock_datetime(),
            )
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
                        name, cron_expression, timezone, parameter_policy_json,
                        enabled,
                        next_run_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        normalized_schedule_id,
                        identity_id,
                        workspace_id,
                        version_id,
                        normalized_name,
                        normalized_cron,
                        normalized_timezone,
                        normalized_parameter_policy,
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
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            next_run_at = current.next_run_at
            if enabled:
                self._require_published_version(
                    connection,
                    identity_id,
                    workspace_id,
                    current.version_id,
                )
                next_run_at = normalize_utc_datetime(
                    next_cron_occurrence(
                        current.cron_expression,
                        current.timezone,
                        now_utc,
                    ),
                    field_name="next_run_at",
                )
            connection.execute(
                """
                UPDATE schedules
                SET enabled = ?, next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                    AND identity_id = ? AND workspace_id = ?
                """,
                (
                    int(enabled),
                    next_run_at,
                    now,
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

    def get_schedule(
        self,
        identity_id: str,
        workspace_id: str,
        schedule_id: str,
    ) -> StoredSchedule:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        schedule_id = validate_schedule_id(schedule_id)
        with self._database.connect() as connection:
            row = self._get_schedule_row(
                connection,
                identity_id,
                workspace_id,
                schedule_id,
            )
        return self._schedule_from_row(row)

    def list_schedules(
        self,
        identity_id: str,
        workspace_id: str,
    ) -> tuple[StoredSchedule, ...]:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM schedules
                WHERE identity_id = ? AND workspace_id = ?
                ORDER BY created_at DESC, schedule_id ASC
                """,
                (identity_id, workspace_id),
            ).fetchall()
        return tuple(self._schedule_from_row(row) for row in rows)

    def update_schedule(
        self,
        identity_id: str,
        workspace_id: str,
        schedule_id: str,
        *,
        name: str | None = None,
        cron_expression: str | None = None,
        timezone_name: str | None = None,
        parameter_policy: Mapping[str, object] | None = None,
    ) -> StoredSchedule:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        schedule_id = validate_schedule_id(schedule_id)
        if (
            name is None
            and cron_expression is None
            and timezone_name is None
            and parameter_policy is None
        ):
            raise ValueError("Schedule update requires at least one field")

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            row = self._get_schedule_row(
                connection,
                identity_id,
                workspace_id,
                schedule_id,
            )
            current = self._schedule_from_row(row)
            updated_name = (
                self._require_name(name) if name is not None else current.name
            )
            updated_cron = current.cron_expression
            if cron_expression is not None:
                updated_cron = normalize_cron_expression(cron_expression)
                CronExpression.parse(updated_cron)
            updated_timezone = (
                normalize_timezone_name(timezone_name)
                if timezone_name is not None
                else current.timezone
            )
            updated_parameter_policy = (
                serialize_parameter_mapping(
                    parameter_policy,
                    field_name="parameter_policy",
                )
                if parameter_policy is not None
                else serialize_parameter_mapping(
                    current.parameter_policy,
                    field_name="parameter_policy",
                )
            )
            if cron_expression is not None or timezone_name is not None:
                updated_next_run = normalize_utc_datetime(
                    next_cron_occurrence(
                        updated_cron,
                        updated_timezone,
                        now_utc,
                    ),
                    field_name="next_run_at",
                )
            else:
                updated_next_run = current.next_run_at

            connection.execute(
                """
                UPDATE schedules
                SET name = ?, cron_expression = ?, timezone = ?,
                    parameter_policy_json = ?,
                    next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                    AND identity_id = ? AND workspace_id = ?
                """,
                (
                    updated_name,
                    updated_cron,
                    updated_timezone,
                    updated_parameter_policy,
                    updated_next_run,
                    now,
                    schedule_id,
                    identity_id,
                    workspace_id,
                ),
            )
            updated_row = self._get_schedule_row(
                connection,
                identity_id,
                workspace_id,
                schedule_id,
            )
            connection.commit()
            return self._schedule_from_row(updated_row)
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
            schedule = self._schedule_from_row(schedule_row)
            existing = self._find_scheduled_run(
                connection,
                schedule,
                normalized_scheduled_for,
            )
            if existing is not None:
                connection.commit()
                return self._run_from_row(existing)
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
            now = self._now()
            row = self._insert_scheduled_run(
                connection,
                schedule,
                scheduled_for=normalized_scheduled_for,
                available_at=now,
                now=now,
            )
            connection.commit()
            return self._run_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _tick_due_schedules(
        self,
        *,
        now: datetime,
        next_run_calculator: Callable[[StoredSchedule, datetime], datetime],
    ) -> tuple[StoredAutomationRun, ...]:
        """Atomically enqueue one compensation Run and advance every due Schedule."""
        normalized_now = normalize_utc_datetime(now, field_name="scheduler clock")
        now_utc = parse_utc_datetime(
            normalized_now,
            field_name="scheduler clock",
        )
        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM schedules
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC, schedule_id ASC
                """,
                (normalized_now,),
            ).fetchall()
            runs: list[StoredAutomationRun] = []
            for row in rows:
                schedule = self._schedule_from_row(row)
                self._require_published_version(
                    connection,
                    schedule.identity_id,
                    schedule.workspace_id,
                    schedule.version_id,
                )
                run_row = self._find_scheduled_run(
                    connection,
                    schedule,
                    schedule.next_run_at,
                )
                if run_row is None:
                    run_row = self._insert_scheduled_run(
                        connection,
                        schedule,
                        scheduled_for=schedule.next_run_at,
                        available_at=normalized_now,
                        now=normalized_now,
                    )

                next_run = next_run_calculator(schedule, now_utc)
                normalized_next_run = normalize_utc_datetime(
                    next_run,
                    field_name="next_run_at",
                )
                if parse_utc_datetime(
                    normalized_next_run,
                    field_name="next_run_at",
                ) <= now_utc:
                    raise AutomationStateError(
                        "Scheduler next_run_at must be strictly after its clock"
                    )
                updated = connection.execute(
                    """
                    UPDATE schedules
                    SET next_run_at = ?, updated_at = ?
                    WHERE schedule_id = ?
                        AND identity_id = ? AND workspace_id = ?
                        AND enabled = 1 AND next_run_at = ?
                    """,
                    (
                        normalized_next_run,
                        normalized_now,
                        schedule.schedule_id,
                        schedule.identity_id,
                        schedule.workspace_id,
                        schedule.next_run_at,
                    ),
                )
                if updated.rowcount != 1:
                    raise AutomationConflictError(
                        "Schedule changed while the Scheduler tick was running"
                    )
                runs.append(self._run_from_row(run_row))
            connection.commit()
            return tuple(runs)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_run(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
    ) -> StoredAutomationRun:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        with self._database.connect() as connection:
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
        return self._run_from_row(row)

    def list_runs(
        self,
        identity_id: str,
        workspace_id: str,
        *,
        limit: int = 50,
        status: AutomationRunStatus | str | None = None,
    ) -> tuple[StoredAutomationRun, ...]:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        normalized_status = (
            AutomationRunStatus(status) if status is not None else None
        )
        with self._database.connect() as connection:
            if normalized_status is None:
                rows = connection.execute(
                    """
                    SELECT * FROM runs
                    WHERE identity_id = ? AND workspace_id = ?
                    ORDER BY created_at DESC, run_id DESC
                    LIMIT ?
                    """,
                    (identity_id, workspace_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM runs
                    WHERE identity_id = ? AND workspace_id = ?
                        AND status = ?
                    ORDER BY created_at DESC, run_id DESC
                    LIMIT ?
                    """,
                    (
                        identity_id,
                        workspace_id,
                        normalized_status.value,
                        limit,
                    ),
                ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def list_runs_pending_attempt_cleanup(
        self,
        *,
        limit: int = 100,
    ) -> tuple[StoredAutomationRun, ...]:
        """List exact abandoned attempts that must be resolved before reclaim."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runs
                WHERE cleanup_attempt_run_id IS NOT NULL
                ORDER BY updated_at ASC, run_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def enqueue_manual_run(
        self,
        identity_id: str,
        workspace_id: str,
        version_id: str,
        *,
        parameter_values: Mapping[str, object] | None = None,
        run_id: str | None = None,
    ) -> StoredAutomationRun:
        """Persist one typed Run without accepting client timing data."""
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        version_id = self._require_identifier(version_id, "version_id")
        normalized_run_id = validate_run_id(
            run_id or f"run_{self._id_factory().hex}"
        )
        normalized_parameter_values = serialize_parameter_mapping(
            parameter_values or {},
            field_name="parameters",
        )

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_published_version(
                connection,
                identity_id,
                workspace_id,
                version_id,
            )
            now = self._now()
            try:
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, identity_id, workspace_id, version_id,
                        schedule_id, trigger, scheduled_for, status,
                        parameter_values_json, attempt_count, available_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        normalized_run_id,
                        identity_id,
                        workspace_id,
                        version_id,
                        AutomationRunTrigger.MANUAL.value,
                        now,
                        AutomationRunStatus.QUEUED.value,
                        normalized_parameter_values,
                        now,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (normalized_run_id,),
                ).fetchone() is not None:
                    raise AutomationConflictError(
                        "run_id is already bound to another Run"
                    ) from exc
                raise AutomationRepositoryError(
                    "Manual Run could not be persisted safely"
                ) from exc
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                normalized_run_id,
            )
            connection.commit()
            return self._run_from_row(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_next_run(
        self,
        *,
        worker_id: str,
        lease_duration: timedelta,
    ) -> StoredAutomationRun | None:
        worker_id = self._require_identifier(worker_id, "worker_id")
        lease_duration = self._require_lease_duration(lease_duration)

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            lease_expires_at = normalize_utc_datetime(
                now_utc + lease_duration,
                field_name="lease_expires_at",
            )
            self._recover_expired_rows(connection, now)
            row = connection.execute(
                """
                SELECT * FROM runs
                WHERE status = ? AND available_at <= ?
                    AND attempt_count < ?
                    AND cancel_requested_at IS NULL
                    AND active_attempt_run_id IS NULL
                    AND cleanup_attempt_run_id IS NULL
                ORDER BY available_at ASC, created_at ASC, run_id ASC
                LIMIT 1
                """,
                (
                    AutomationRunStatus.QUEUED.value,
                    now,
                    self.MAX_ATTEMPTS,
                ),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            current = self._run_from_row(row)
            lease_token = self._new_lease_token()
            updated = connection.execute(
                """
                UPDATE runs
                SET status = ?, attempt_count = attempt_count + 1,
                    lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                    updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND status = ? AND attempt_count = ?
                """,
                (
                    AutomationRunStatus.RUNNING.value,
                    worker_id,
                    lease_token,
                    lease_expires_at,
                    now,
                    current.run_id,
                    current.identity_id,
                    current.workspace_id,
                    AutomationRunStatus.QUEUED.value,
                    current.attempt_count,
                ),
            )
            if updated.rowcount != 1:
                raise AutomationConflictError(
                    "Run changed while a Worker was claiming it"
                )
            claimed_row = self._get_run_row(
                connection,
                current.identity_id,
                current.workspace_id,
                current.run_id,
            )
            connection.commit()
            return self._run_from_row(claimed_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def start_run_attempt(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
        *,
        worker_id: str,
        lease_token: str,
        attempt_run_id: str,
    ) -> StoredAutomationRun:
        """Bind one physical attempt id to the currently fenced logical Run."""
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        worker_id = self._require_identifier(worker_id, "worker_id")
        lease_token = self._require_lease_token(lease_token)
        attempt_run_id = validate_run_id(attempt_run_id)
        if attempt_run_id == run_id:
            raise ValueError(
                "Artifact attempt run id must differ from the logical Run id"
            )

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            current = self._run_from_row(row)
            self._require_active_lease(
                current,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now_utc,
            )
            if current.active_attempt_run_id is not None:
                raise AutomationStateError(
                    "Run already has an active physical attempt"
                )
            if current.cleanup_attempt_run_id is not None:
                raise AutomationStateError(
                    "Run has an abandoned attempt awaiting cleanup"
                )
            updated = connection.execute(
                """
                UPDATE runs
                SET active_attempt_run_id = ?, updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND status = ? AND lease_owner = ? AND lease_token = ?
                    AND active_attempt_run_id IS NULL
                    AND cleanup_attempt_run_id IS NULL
                """,
                (
                    attempt_run_id,
                    now,
                    run_id,
                    identity_id,
                    workspace_id,
                    AutomationRunStatus.RUNNING.value,
                    worker_id,
                    lease_token,
                ),
            )
            if updated.rowcount != 1:
                raise AutomationLeaseError(
                    "Worker lease fencing check failed while starting an attempt"
                )
            started = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            connection.commit()
            return self._run_from_row(started)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_run_attempt_cleanup(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
        *,
        attempt_run_id: str,
    ) -> StoredAutomationRun:
        """Clear one exact cleanup marker without touching a newer attempt."""
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        attempt_run_id = validate_run_id(attempt_run_id)

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            current = self._run_from_row(row)
            if current.cleanup_attempt_run_id is None:
                connection.commit()
                return current
            if current.cleanup_attempt_run_id != attempt_run_id:
                connection.commit()
                return current
            if (
                current.status is AutomationRunStatus.RUNNING
                or current.active_attempt_run_id is not None
            ):
                raise AutomationStateError(
                    "Active Run state cannot complete abandoned-attempt cleanup"
                )
            now = self._now()
            updated = connection.execute(
                """
                UPDATE runs
                SET cleanup_attempt_run_id = NULL, updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND cleanup_attempt_run_id = ?
                """,
                (
                    now,
                    run_id,
                    identity_id,
                    workspace_id,
                    attempt_run_id,
                ),
            )
            if updated.rowcount != 1:
                latest = self._get_run_row(
                    connection,
                    identity_id,
                    workspace_id,
                    run_id,
                )
                current = self._run_from_row(latest)
                if current.cleanup_attempt_run_id is not None:
                    raise AutomationConflictError(
                        "Run cleanup marker changed during completion"
                    )
                connection.commit()
                return current
            cleaned = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            connection.commit()
            return self._run_from_row(cleaned)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def renew_run_lease(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_duration: timedelta,
    ) -> StoredAutomationRun:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        worker_id = self._require_identifier(worker_id, "worker_id")
        lease_token = self._require_lease_token(lease_token)
        lease_duration = self._require_lease_duration(lease_duration)

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            lease_expires_at = normalize_utc_datetime(
                now_utc + lease_duration,
                field_name="lease_expires_at",
            )
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            current = self._run_from_row(row)
            self._require_active_lease(
                current,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now_utc,
            )
            updated = connection.execute(
                """
                UPDATE runs
                SET lease_expires_at = ?, updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND status = ? AND lease_owner = ? AND lease_token = ?
                """,
                (
                    lease_expires_at,
                    now,
                    run_id,
                    identity_id,
                    workspace_id,
                    AutomationRunStatus.RUNNING.value,
                    worker_id,
                    lease_token,
                ),
            )
            if updated.rowcount != 1:
                raise AutomationLeaseError(
                    "Worker lease fencing check failed during renewal"
                )
            renewed = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            connection.commit()
            return self._run_from_row(renewed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def request_run_cancel(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
    ) -> StoredAutomationRun:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = self._now()
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            current = self._run_from_row(row)
            if current.status is AutomationRunStatus.CANCELLED:
                connection.commit()
                return current
            if current.status not in {
                AutomationRunStatus.QUEUED,
                AutomationRunStatus.RUNNING,
            }:
                raise AutomationStateError(
                    "A terminal Run cannot be cancelled or reopened"
                )
            if current.cancel_requested_at is not None:
                connection.commit()
                return current

            if current.status is AutomationRunStatus.QUEUED:
                connection.execute(
                    """
                    UPDATE runs
                    SET status = ?, cancel_requested_at = ?, updated_at = ?
                    WHERE run_id = ?
                        AND identity_id = ? AND workspace_id = ?
                        AND status = ?
                    """,
                    (
                        AutomationRunStatus.CANCELLED.value,
                        now,
                        now,
                        run_id,
                        identity_id,
                        workspace_id,
                        AutomationRunStatus.QUEUED.value,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE runs
                    SET cancel_requested_at = ?, updated_at = ?
                    WHERE run_id = ?
                        AND identity_id = ? AND workspace_id = ?
                        AND status = ? AND cancel_requested_at IS NULL
                    """,
                    (
                        now,
                        now,
                        run_id,
                        identity_id,
                        workspace_id,
                        AutomationRunStatus.RUNNING.value,
                    ),
                )
            updated_row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            connection.commit()
            return self._run_from_row(updated_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_run(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
        *,
        worker_id: str,
        lease_token: str,
        status: AutomationRunStatus,
        artifact_run_id: str | None = None,
        artifact_path: str | None = None,
        manifest_hash: HashDigest | None = None,
        binding_hash: HashDigest | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> StoredAutomationRun:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        worker_id = self._require_identifier(worker_id, "worker_id")
        lease_token = self._require_lease_token(lease_token)
        try:
            final_status = AutomationRunStatus(status)
        except ValueError as exc:
            raise AutomationStateError("Unknown Automation Run status") from exc
        if final_status in {
            AutomationRunStatus.QUEUED,
            AutomationRunStatus.RUNNING,
        }:
            raise AutomationStateError(
                "finish_run requires a terminal Run status"
            )
        (
            artifact_run_id,
            artifact_path,
            stored_manifest_hash,
            stored_binding_hash,
        ) = self._validate_artifact_reference(
            final_status,
            artifact_run_id=artifact_run_id,
            artifact_path=artifact_path,
            manifest_hash=manifest_hash,
            binding_hash=binding_hash,
        )
        if artifact_run_id == run_id:
            raise ValueError(
                "Artifact attempt run id must differ from the logical Run id"
            )
        stored_error_code, stored_error_message = (
            self._validate_terminal_error(
                final_status,
                error_code=error_code,
                error_message=error_message,
            )
        )

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            current = self._run_from_row(row)
            self._require_active_lease(
                current,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now_utc,
            )
            if (
                current.cancel_requested_at is not None
                and final_status is not AutomationRunStatus.CANCELLED
            ):
                raise AutomationStateError(
                    "Run has a cancellation request and must finish cancelled"
                )
            if (
                final_status is AutomationRunStatus.CANCELLED
                and current.cancel_requested_at is None
            ):
                raise AutomationStateError(
                    "Run cannot finish cancelled without a cancellation request"
                )
            if current.cleanup_attempt_run_id is not None:
                raise AutomationStateError(
                    "Run cannot finish while attempt cleanup is pending"
                )
            if (
                current.active_attempt_run_id is not None
                and current.active_attempt_run_id != artifact_run_id
            ):
                raise AutomationStateError(
                    "Terminal artifact does not match the active physical attempt"
                )
            updated = connection.execute(
                """
                UPDATE runs
                SET status = ?, lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, active_attempt_run_id = NULL,
                    cleanup_attempt_run_id = NULL, artifact_run_id = ?,
                    artifact_path = ?, manifest_hash = ?, binding_hash = ?,
                    error_code = ?, error_message = ?, updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND status = ? AND lease_owner = ? AND lease_token = ?
                    AND active_attempt_run_id IS ?
                """,
                (
                    final_status.value,
                    artifact_run_id,
                    artifact_path,
                    stored_manifest_hash,
                    stored_binding_hash,
                    stored_error_code,
                    stored_error_message,
                    now,
                    run_id,
                    identity_id,
                    workspace_id,
                    AutomationRunStatus.RUNNING.value,
                    worker_id,
                    lease_token,
                    current.active_attempt_run_id,
                ),
            )
            if updated.rowcount != 1:
                raise AutomationLeaseError(
                    "Worker lease fencing check failed during completion"
                )
            finished = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            connection.commit()
            return self._run_from_row(finished)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail_run(
        self,
        identity_id: str,
        workspace_id: str,
        run_id: str,
        *,
        worker_id: str,
        lease_token: str,
        retryable: bool,
        error_code: str,
        error_message: str,
        retry_at: datetime | None = None,
    ) -> StoredAutomationRun:
        identity_id = self._require_identifier(identity_id, "identity_id")
        workspace_id = self._require_identifier(workspace_id, "workspace_id")
        run_id = validate_run_id(run_id)
        worker_id = self._require_identifier(worker_id, "worker_id")
        lease_token = self._require_lease_token(lease_token)
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a bool")
        stored_error_code = self._normalize_error_code(error_code)
        stored_error_message = self._normalize_error_message(error_message)
        if stored_error_code is None or stored_error_message is None:
            raise ValueError("Run failure requires a safe error code and message")
        normalized_retry_at = None
        if retry_at is not None:
            normalized_retry_at = normalize_utc_datetime(
                retry_at,
                field_name="retry_at",
            )

        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now_utc = self._clock_datetime()
            now = normalize_utc_datetime(now_utc, field_name="clock")
            if normalized_retry_at is None:
                available_at = now
            else:
                available_at = normalized_retry_at
                if parse_utc_datetime(
                    available_at,
                    field_name="retry_at",
                ) < now_utc:
                    available_at = now
            row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            current = self._run_from_row(row)
            self._require_active_lease(
                current,
                worker_id=worker_id,
                lease_token=lease_token,
                now=now_utc,
            )
            if current.cleanup_attempt_run_id is not None:
                raise AutomationStateError(
                    "Run cannot fail while attempt cleanup is already pending"
                )
            if current.cancel_requested_at is not None:
                target_status = AutomationRunStatus.CANCELLED
                stored_error_code = None
                stored_error_message = None
            elif retryable and current.attempt_count < self.MAX_ATTEMPTS:
                target_status = AutomationRunStatus.QUEUED
            else:
                target_status = AutomationRunStatus.FAILED

            updated = connection.execute(
                """
                UPDATE runs
                SET status = ?, available_at = ?, lease_owner = NULL,
                    lease_token = NULL, lease_expires_at = NULL,
                    cleanup_attempt_run_id = active_attempt_run_id,
                    active_attempt_run_id = NULL,
                    artifact_run_id = NULL, artifact_path = NULL,
                    manifest_hash = NULL, binding_hash = NULL,
                    error_code = ?, error_message = ?, updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND status = ? AND lease_owner = ? AND lease_token = ?
                    AND active_attempt_run_id IS ?
                    AND cleanup_attempt_run_id IS NULL
                """,
                (
                    target_status.value,
                    available_at,
                    stored_error_code,
                    stored_error_message,
                    now,
                    run_id,
                    identity_id,
                    workspace_id,
                    AutomationRunStatus.RUNNING.value,
                    worker_id,
                    lease_token,
                    current.active_attempt_run_id,
                ),
            )
            if updated.rowcount != 1:
                raise AutomationLeaseError(
                    "Worker lease fencing check failed while recording failure"
                )
            failed_row = self._get_run_row(
                connection,
                identity_id,
                workspace_id,
                run_id,
            )
            connection.commit()
            return self._run_from_row(failed_row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recover_expired_runs(self) -> tuple[StoredAutomationRun, ...]:
        connection = self._database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = self._now()
            rows = self._recover_expired_rows(connection, now)
            connection.commit()
            return tuple(self._run_from_row(row) for row in rows)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _insert_scheduled_run(
        self,
        connection: sqlite3.Connection,
        schedule: StoredSchedule,
        *,
        scheduled_for: str,
        available_at: str,
        now: str,
    ) -> sqlite3.Row:
        run_id = validate_run_id(f"run_{self._id_factory().hex}")
        parameter_values = resolve_schedule_parameter_policy(
            schedule.parameter_policy,
            scheduled_for=scheduled_for,
            timezone_name=schedule.timezone,
        )
        parameter_values_json = serialize_parameter_mapping(
            parameter_values,
            field_name="parameters",
        )
        try:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, identity_id, workspace_id, version_id,
                    schedule_id, trigger, scheduled_for, status,
                    parameter_values_json, attempt_count, available_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(schedule_id, scheduled_for) DO NOTHING
                """,
                (
                    run_id,
                    schedule.identity_id,
                    schedule.workspace_id,
                    schedule.version_id,
                    schedule.schedule_id,
                    AutomationRunTrigger.SCHEDULED.value,
                    scheduled_for,
                    AutomationRunStatus.QUEUED.value,
                    parameter_values_json,
                    available_at,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AutomationConflictError(
                "run_id is already bound to another Run"
            ) from exc
        row = self._find_scheduled_run(
            connection,
            schedule,
            scheduled_for,
        )
        if row is None:
            raise AutomationRepositoryError(
                "Scheduled Run enqueue did not produce a durable row"
            )
        return row

    @staticmethod
    def _find_scheduled_run(
        connection: sqlite3.Connection,
        schedule: StoredSchedule,
        scheduled_for: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM runs
            WHERE schedule_id = ? AND scheduled_for = ?
                AND identity_id = ? AND workspace_id = ?
            """,
            (
                schedule.schedule_id,
                scheduled_for,
                schedule.identity_id,
                schedule.workspace_id,
            ),
        ).fetchone()

    def _recover_expired_rows(
        self,
        connection: sqlite3.Connection,
        now: str,
    ) -> tuple[sqlite3.Row, ...]:
        rows = connection.execute(
            """
            SELECT * FROM runs
            WHERE status = ? AND lease_expires_at IS NOT NULL
                AND lease_expires_at <= ?
            ORDER BY lease_expires_at ASC, run_id ASC
            """,
            (AutomationRunStatus.RUNNING.value, now),
        ).fetchall()
        recovered: list[sqlite3.Row] = []
        for row in rows:
            current = self._run_from_row(row)
            if current.cleanup_attempt_run_id is not None:
                raise AutomationStateError(
                    "Running Run already has an attempt cleanup marker"
                )
            if current.cancel_requested_at is not None:
                target_status = AutomationRunStatus.CANCELLED
                error_code = None
                error_message = None
            elif current.attempt_count >= self.MAX_ATTEMPTS:
                target_status = AutomationRunStatus.FAILED
                error_code = "attempts_exhausted"
                error_message = "Run failed after the maximum number of attempts."
            else:
                target_status = AutomationRunStatus.QUEUED
                error_code = "lease_expired"
                error_message = "The previous Worker lease expired."
            updated = connection.execute(
                """
                UPDATE runs
                SET status = ?, available_at = ?, lease_owner = NULL,
                    lease_token = NULL, lease_expires_at = NULL,
                    cleanup_attempt_run_id = active_attempt_run_id,
                    active_attempt_run_id = NULL,
                    artifact_run_id = NULL, artifact_path = NULL,
                    manifest_hash = NULL, binding_hash = NULL,
                    error_code = ?, error_message = ?, updated_at = ?
                WHERE run_id = ?
                    AND identity_id = ? AND workspace_id = ?
                    AND status = ? AND lease_expires_at <= ?
                """,
                (
                    target_status.value,
                    now,
                    error_code,
                    error_message,
                    now,
                    current.run_id,
                    current.identity_id,
                    current.workspace_id,
                    AutomationRunStatus.RUNNING.value,
                    now,
                ),
            )
            if updated.rowcount != 1:
                raise AutomationConflictError(
                    "Run changed while its expired lease was being recovered"
                )
            recovered.append(
                self._get_run_row(
                    connection,
                    current.identity_id,
                    current.workspace_id,
                    current.run_id,
                )
            )
        return tuple(recovered)

    @staticmethod
    def _require_lease_duration(value: timedelta) -> timedelta:
        if not isinstance(value, timedelta):
            raise TypeError("lease_duration must be a timedelta")
        if value <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        return value

    @staticmethod
    def _require_lease_token(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("lease_token must be a string")
        if not value or value != value.strip() or len(value) > 256:
            raise ValueError("lease_token is invalid")
        return value

    def _new_lease_token(self) -> str:
        return self._require_lease_token(self._token_factory())

    @staticmethod
    def _require_active_lease(
        run: StoredAutomationRun,
        *,
        worker_id: str,
        lease_token: str,
        now: datetime,
    ) -> None:
        if run.status is not AutomationRunStatus.RUNNING:
            raise AutomationStateError(
                "Only a running Run can be changed by a Worker"
            )
        if run.lease_owner != worker_id or run.lease_token != lease_token:
            raise AutomationLeaseError(
                "Worker lease fencing token does not match the active lease"
            )
        if run.lease_expires_at is None or parse_utc_datetime(
            run.lease_expires_at,
            field_name="lease_expires_at",
        ) <= now:
            raise AutomationLeaseError(
                "Worker lease fencing failed because the lease expired"
            )

    @staticmethod
    def _validate_artifact_reference(
        status: AutomationRunStatus,
        *,
        artifact_run_id: str | None,
        artifact_path: str | None,
        manifest_hash: HashDigest | None,
        binding_hash: HashDigest | None,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        values = (
            artifact_run_id,
            artifact_path,
            manifest_hash,
            binding_hash,
        )
        provided = tuple(value is not None for value in values)
        if any(provided) and not all(provided):
            raise ValueError(
                "Artifact reference fields must be provided together"
            )
        if status in {
            AutomationRunStatus.SUCCEEDED,
            AutomationRunStatus.NEEDS_REVIEW,
        } and not all(provided):
            raise ValueError(
                "Successful and needs-review Runs require an artifact reference"
            )
        if not any(provided):
            return None, None, None, None

        artifact_run_id = validate_run_id(artifact_run_id)
        if not isinstance(artifact_path, str) or not artifact_path:
            raise ValueError("artifact_path must be a non-empty relative path")
        raw_parts = artifact_path.split("/")
        parsed_path = PurePosixPath(artifact_path)
        if (
            parsed_path.is_absolute()
            or "\\" in artifact_path
            or PureWindowsPath(artifact_path).drive
            or any(part in {"", ".", ".."} for part in raw_parts)
            or any(ord(character) < 32 for character in artifact_path)
        ):
            raise ValueError("artifact_path must be a safe relative path")
        if not isinstance(manifest_hash, HashDigest):
            raise TypeError("manifest_hash must be a HashDigest")
        if not isinstance(binding_hash, HashDigest):
            raise TypeError("binding_hash must be a HashDigest")
        return (
            artifact_run_id,
            parsed_path.as_posix(),
            str(manifest_hash),
            str(binding_hash),
        )

    @classmethod
    def _validate_terminal_error(
        cls,
        status: AutomationRunStatus,
        *,
        error_code: str | None,
        error_message: str | None,
    ) -> tuple[str | None, str | None]:
        stored_code = cls._normalize_error_code(error_code)
        stored_message = cls._normalize_error_message(error_message)
        has_code = stored_code is not None
        has_message = stored_message is not None
        if has_code != has_message:
            raise ValueError(
                "Terminal error code and message must be provided together"
            )
        if status in {
            AutomationRunStatus.FAILED,
            AutomationRunStatus.NEEDS_REVIEW,
        }:
            if not has_code:
                raise ValueError(
                    "Failed and needs-review Runs require a safe error"
                )
        elif has_code:
            raise ValueError(
                "Succeeded and cancelled Runs cannot store an error"
            )
        return stored_code, stored_message

    @staticmethod
    def _normalize_error_code(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("error_code must be a string")
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 128
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError("error_code is invalid")
        return normalized

    @staticmethod
    def _normalize_error_message(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("error_message must be a string")
        return sanitize_error_message(value) or "Automation run failed."

    def _clock_datetime(self) -> datetime:
        normalized = normalize_utc_datetime(self._clock(), field_name="clock")
        return parse_utc_datetime(normalized, field_name="clock")

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
        if len(normalized) > 200:
            raise ValueError("name cannot exceed 200 characters")
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
    def _get_run_row(
        connection: sqlite3.Connection,
        identity_id: str,
        workspace_id: str,
        run_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise AutomationNotFoundError("Run was not found")
        if (
            row["identity_id"] != identity_id
            or row["workspace_id"] != workspace_id
        ):
            raise AutomationScopeError(
                "Run belongs to another identity or Workspace scope"
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
            parameter_policy=deserialize_parameter_mapping(
                row["parameter_policy_json"],
                field_name="parameter_policy",
            ),
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
            parameter_values=deserialize_parameter_mapping(
                row["parameter_values_json"],
                field_name="parameters",
            ),
            status=AutomationRunStatus(row["status"]),
            attempt_count=row["attempt_count"],
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            cancel_requested_at=row["cancel_requested_at"],
            active_attempt_run_id=row["active_attempt_run_id"],
            cleanup_attempt_run_id=row["cleanup_attempt_run_id"],
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
        return normalize_utc_datetime(
            self._clock_datetime(),
            field_name="clock",
        )
