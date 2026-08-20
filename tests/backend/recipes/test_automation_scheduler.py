from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from data_formulator.automation.repository import AutomationRepository
from data_formulator.automation.scheduler import AutomationScheduler


pytestmark = [pytest.mark.backend]


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def _seed_published_version(
    repository: AutomationRepository,
    *,
    identity_id: str = "user:alice",
    workspace_id: str = "ws-1",
    version_id: str = "rv_" + "1" * 64,
) -> None:
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO recipes (
                recipe_id, identity_id, workspace_id, name, description,
                created_by, created_at, updated_at
            ) VALUES ('recipe-1', ?, ?, 'Recipe', '', ?, ?, ?)
            """,
            (
                identity_id,
                workspace_id,
                identity_id,
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
            ) VALUES (?, 'recipe-1', ?, ?, ?, 'published', ?, ?, ?, ?)
            """,
            (
                version_id,
                identity_id,
                workspace_id,
                "sha256:" + "1" * 64,
                "recipes/recipe-1/version.json",
                "sha256:" + "2" * 64,
                "2026-08-19T00:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
            ),
        )


def _create_schedule(
    repository: AutomationRepository,
    *,
    schedule_id: str,
    next_run_at: datetime,
    cron_expression: str = "0 9 * * *",
):
    return repository.create_schedule(
        identity_id="user:alice",
        workspace_id="ws-1",
        version_id="rv_" + "1" * 64,
        name="Daily recipe",
        cron_expression=cron_expression,
        timezone_name="UTC",
        next_run_at=next_run_at,
        schedule_id=schedule_id,
    )


def test_tick_coalesces_missed_intervals_and_advances_strictly_after_now(
    tmp_path,
) -> None:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clock = _MutableClock(now)
    repository = AutomationRepository(tmp_path / "automation.db", clock=clock)
    _seed_published_version(repository)
    schedule = _create_schedule(
        repository,
        schedule_id="sch_" + "1" * 32,
        next_run_at=datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
    )
    scheduler = AutomationScheduler(repository, clock=clock)

    first = scheduler.tick()
    second = scheduler.tick()

    assert first.checked_at == "2026-08-20T12:00:00.000000Z"
    assert len(first.runs) == 1
    assert first.runs[0].schedule_id == schedule.schedule_id
    assert first.runs[0].scheduled_for == "2026-08-17T09:00:00.000000Z"
    assert second.runs == ()
    updated = repository.get_schedule(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
    )
    assert updated.next_run_at == "2026-08-21T09:00:00.000000Z"
    with sqlite3.connect(repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_tick_ignores_disabled_or_future_schedules(tmp_path) -> None:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clock = _MutableClock(now)
    repository = AutomationRepository(tmp_path / "automation.db", clock=clock)
    _seed_published_version(repository)
    disabled = _create_schedule(
        repository,
        schedule_id="sch_" + "2" * 32,
        next_run_at=now - timedelta(hours=1),
    )
    _create_schedule(
        repository,
        schedule_id="sch_" + "3" * 32,
        next_run_at=now + timedelta(hours=21),
    )
    repository.set_schedule_enabled(
        "user:alice",
        "ws-1",
        disabled.schedule_id,
        enabled=False,
    )

    result = AutomationScheduler(repository, clock=clock).tick()

    assert result.runs == ()


def test_schedule_update_recalculates_next_run_without_changing_version(
    tmp_path,
) -> None:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clock = _MutableClock(now)
    repository = AutomationRepository(tmp_path / "automation.db", clock=clock)
    _seed_published_version(repository)
    schedule = _create_schedule(
        repository,
        schedule_id="sch_" + "6" * 32,
        next_run_at=now + timedelta(days=1),
    )

    updated = repository.update_schedule(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
        name="  Weekday recipe  ",
        cron_expression="30 8 * * 1-5",
        timezone_name="America/New_York",
    )

    assert updated.version_id == schedule.version_id
    assert updated.name == "Weekday recipe"
    assert updated.cron_expression == "30 8 * * 1-5"
    assert updated.timezone == "America/New_York"
    assert updated.next_run_at == "2026-08-20T12:30:00.000000Z"
    assert repository.list_schedules("user:alice", "ws-1") == (updated,)
    assert repository.list_schedules("user:mallory", "ws-1") == ()


def test_reenabling_a_schedule_starts_after_the_enable_time(tmp_path) -> None:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clock = _MutableClock(now)
    repository = AutomationRepository(tmp_path / "automation.db", clock=clock)
    _seed_published_version(repository)
    schedule = _create_schedule(
        repository,
        schedule_id="sch_" + "7" * 32,
        next_run_at=now - timedelta(days=1),
    )
    repository.set_schedule_enabled(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
        enabled=False,
    )
    clock.current = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)

    enabled = repository.set_schedule_enabled(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
        enabled=True,
    )

    assert enabled.next_run_at == "2026-08-23T09:00:00.000000Z"
    assert AutomationScheduler(repository, clock=clock).tick().runs == ()


def test_tick_rolls_back_all_schedules_when_next_time_calculation_fails(
    tmp_path,
) -> None:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clock = _MutableClock(now)
    repository = AutomationRepository(tmp_path / "automation.db", clock=clock)
    _seed_published_version(repository)
    first = _create_schedule(
        repository,
        schedule_id="sch_" + "4" * 32,
        next_run_at=now - timedelta(hours=3),
    )
    second = _create_schedule(
        repository,
        schedule_id="sch_" + "5" * 32,
        next_run_at=now - timedelta(hours=2),
    )

    def fail_on_second(schedule, _after):
        if schedule.schedule_id == second.schedule_id:
            raise RuntimeError("simulated Cron failure")
        return now + timedelta(days=1)

    scheduler = AutomationScheduler(
        repository,
        clock=clock,
        next_run_calculator=fail_on_second,
    )

    with pytest.raises(RuntimeError, match="Cron failure"):
        scheduler.tick()

    assert repository.get_schedule(
        "user:alice",
        "ws-1",
        first.schedule_id,
    ).next_run_at == "2026-08-20T09:00:00.000000Z"
    assert repository.get_schedule(
        "user:alice",
        "ws-1",
        second.schedule_id,
    ).next_run_at == "2026-08-20T10:00:00.000000Z"
    with sqlite3.connect(repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_two_scheduler_connections_contending_for_one_due_schedule_enqueue_once(
    tmp_path,
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    clock = _MutableClock(now)
    database_path = tmp_path / "automation.db"
    setup_repository = AutomationRepository(database_path, clock=clock)
    _seed_published_version(setup_repository)
    schedule = _create_schedule(
        setup_repository,
        schedule_id="sch_" + "8" * 32,
        next_run_at=now - timedelta(hours=3),
    )

    first_has_write_lock = threading.Event()
    release_first = threading.Event()
    second_begin_attempted = threading.Event()
    second_finished = threading.Event()
    results: list[object | None] = [None, None]
    failures: list[BaseException] = []

    def hold_first_transaction(current_schedule, after):
        first_has_write_lock.set()
        if not release_first.wait(timeout=5):
            raise AssertionError("Concurrent Scheduler was not released")
        return AutomationScheduler._calculate_next_run(current_schedule, after)

    first_scheduler = AutomationScheduler(
        AutomationRepository(database_path, clock=clock),
        clock=clock,
        next_run_calculator=hold_first_transaction,
    )
    second_repository = AutomationRepository(database_path, clock=clock)

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=(), /):
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                second_begin_attempted.set()
            return super().execute(sql, parameters)

    def connect_second_repository() -> sqlite3.Connection:
        connection = sqlite3.connect(
            database_path,
            timeout=5.0,
            factory=ObservedConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    monkeypatch.setattr(
        second_repository._database,
        "connect",
        connect_second_repository,
    )
    second_scheduler = AutomationScheduler(second_repository, clock=clock)

    def run_first() -> None:
        try:
            results[0] = first_scheduler.tick()
        except BaseException as exc:  # make thread failures visible to pytest
            failures.append(exc)

    def run_second() -> None:
        try:
            results[1] = second_scheduler.tick()
        except BaseException as exc:  # make thread failures visible to pytest
            failures.append(exc)
        finally:
            second_finished.set()

    first_thread = threading.Thread(target=run_first)
    second_thread = threading.Thread(target=run_second)
    first_thread.start()
    assert first_has_write_lock.wait(timeout=5)
    second_thread.start()
    assert second_begin_attempted.wait(timeout=5)
    # The observed second connection has called BEGIN IMMEDIATE and cannot
    # finish while the first connection holds the write lock.
    assert not second_finished.wait(timeout=0.1)
    release_first.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert failures == []
    run_counts = sorted(len(result.runs) for result in results if result is not None)
    assert run_counts == [0, 1]

    verifier = AutomationRepository(database_path, clock=clock)
    runs = verifier.list_runs("user:alice", "ws-1")
    assert len(runs) == 1
    assert runs[0].schedule_id == schedule.schedule_id
    assert runs[0].scheduled_for == "2026-08-20T09:00:00.000000Z"
    assert verifier.get_schedule(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
    ).next_run_at == "2026-08-21T09:00:00.000000Z"
