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
    assert RecipeRepository.SCHEMA_VERSION == AutomationDatabase.SCHEMA_VERSION == 3

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version FROM automation_schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,)]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"recipes", "recipe_versions", "schedules", "runs"}.issubset(tables)


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
            VALUES (4, '2026-08-19T00:00:00Z')
            """
        )

    with pytest.raises(AutomationDatabaseError, match=r"Unsupported.*\[4\]"):
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
