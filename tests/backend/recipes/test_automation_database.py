from __future__ import annotations

import sqlite3

import pytest

from data_formulator.automation.db import (
    AutomationDatabase,
    AutomationDatabaseError,
)
from data_formulator.automation.repository import AutomationRepository
from data_formulator.recipes.repository import RecipeRepository


pytestmark = [pytest.mark.backend]


def _create_schema_v2(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE automation_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        AutomationDatabase._apply_schema_v1(connection)
        AutomationDatabase._apply_schema_v2(connection)
        connection.executemany(
            """
            INSERT INTO automation_schema_migrations (version, applied_at)
            VALUES (?, '2026-08-19T00:00:00Z')
            """,
            [(1,), (2,)],
        )


def _create_schema_v3_with_scheduled_run(database_path) -> None:
    _create_schema_v2(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        AutomationDatabase._apply_schema_v3(connection)
        connection.execute(
            """
            INSERT INTO automation_schema_migrations (version, applied_at)
            VALUES (3, '2026-08-19T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO recipes (
                recipe_id, identity_id, workspace_id, name, description,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '', ?, ?, ?)
            """,
            (
                "recipe-existing",
                "user:alice",
                "ws-1",
                "Existing Recipe",
                "user:alice",
                "2026-08-19T00:00:00.000000Z",
                "2026-08-19T00:00:00.000000Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO recipe_versions (
                version_id, recipe_id, identity_id, workspace_id,
                recipe_hash, status, artifact_path, manifest_hash,
                created_at, published_at
            ) VALUES (?, ?, ?, ?, ?, 'published', ?, ?, ?, ?)
            """,
            (
                "rv_" + "1" * 64,
                "recipe-existing",
                "user:alice",
                "ws-1",
                "sha256:" + "2" * 64,
                "recipes/recipe-existing/version.json",
                "sha256:" + "3" * 64,
                "2026-08-19T00:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO schedules (
                schedule_id, identity_id, workspace_id, version_id, name,
                cron_expression, timezone, enabled, next_run_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                "sch_" + "4" * 32,
                "user:alice",
                "ws-1",
                "rv_" + "1" * 64,
                "Existing daily schedule",
                "0 9 * * *",
                "UTC",
                "2026-08-20T09:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO runs (
                run_id, identity_id, workspace_id, version_id, schedule_id,
                trigger, scheduled_for, status, attempt_count, available_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'scheduled', ?, 'queued', 0, ?, ?, ?)
            """,
            (
                "run_" + "5" * 32,
                "user:alice",
                "ws-1",
                "rv_" + "1" * 64,
                "sch_" + "4" * 32,
                "2026-08-20T09:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
            ),
        )


def test_schema_v2_upgrades_once_and_both_repositories_reopen_it(tmp_path) -> None:
    database_path = tmp_path / "automation" / "automation.db"
    database_path.parent.mkdir(parents=True)
    _create_schema_v2(database_path)

    automation = AutomationRepository(database_path)
    recipe = RecipeRepository(database_path)
    reopened = AutomationRepository(database_path)

    assert automation.database_path == database_path.resolve()
    assert recipe.database_path == database_path.resolve()
    assert reopened.database_path == database_path.resolve()
    assert RecipeRepository.SCHEMA_VERSION == AutomationDatabase.SCHEMA_VERSION == 5

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version FROM automation_schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"recipes", "recipe_versions", "schedules", "runs"}.issubset(tables)
        run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(runs)")
        }
        assert {
            "active_attempt_run_id",
            "cleanup_attempt_run_id",
            "parameter_values_json",
        }.issubset(run_columns)
        schedule_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(schedules)")
        }
        assert "parameter_policy_json" in schedule_columns


def test_schema_v3_upgrade_preserves_existing_schedule_and_run(tmp_path) -> None:
    database_path = tmp_path / "automation" / "automation.db"
    database_path.parent.mkdir(parents=True)
    _create_schema_v3_with_scheduled_run(database_path)

    automation = AutomationRepository(database_path)

    schedule = automation.get_schedule(
        "user:alice",
        "ws-1",
        "sch_" + "4" * 32,
    )
    run = automation.get_run(
        "user:alice",
        "ws-1",
        "run_" + "5" * 32,
    )
    assert schedule.name == "Existing daily schedule"
    assert schedule.next_run_at == "2026-08-20T09:00:00.000000Z"
    assert schedule.parameter_policy == {}
    assert run.status.value == "queued"
    assert run.attempt_count == 0
    assert run.active_attempt_run_id is None
    assert run.cleanup_attempt_run_id is None
    assert run.parameter_values == {}

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version FROM automation_schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]
        schedule_count = connection.execute(
            "SELECT COUNT(*) FROM schedules"
        ).fetchone()[0]
        run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        recipe = connection.execute(
            "SELECT name FROM recipes WHERE recipe_id = 'recipe-existing'"
        ).fetchone()
        version = connection.execute(
            "SELECT status FROM recipe_versions WHERE version_id = ?",
            ("rv_" + "1" * 64,),
        ).fetchone()
        assert recipe == ("Existing Recipe",)
        assert version == ("published",)
        assert schedule_count == 1
        assert run_count == 1


def test_database_rejects_unknown_future_migration_without_partial_upgrade(
    tmp_path,
) -> None:
    database_path = tmp_path / "automation.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE automation_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO automation_schema_migrations (version, applied_at)
            VALUES (6, '2026-08-19T00:00:00Z')
            """
        )

    with pytest.raises(AutomationDatabaseError, match=r"Unsupported.*\[6\]"):
        AutomationDatabase(database_path)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "schedules" not in tables
        assert "runs" not in tables


def test_failed_schema_v3_migration_rolls_back_every_partial_change(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "automation.db"
    _create_schema_v2(database_path)

    def fail_after_first_statement(connection) -> None:
        connection.execute("CREATE TABLE partial_schedule_table (id TEXT)")
        raise sqlite3.OperationalError("simulated migration failure")

    monkeypatch.setattr(
        AutomationDatabase,
        "_apply_schema_v3",
        staticmethod(fail_after_first_statement),
    )

    with pytest.raises(
        AutomationDatabaseError,
        match="Failed to initialize",
    ):
        AutomationDatabase(database_path)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version FROM automation_schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]
        assert connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'partial_schedule_table'
            """
        ).fetchone() is None


def test_shared_connections_enable_required_sqlite_pragmas(tmp_path) -> None:
    database = AutomationDatabase(tmp_path / "automation.db")

    with database.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
