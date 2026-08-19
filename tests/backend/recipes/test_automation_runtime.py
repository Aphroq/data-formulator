from __future__ import annotations

import sqlite3
import threading
from datetime import timedelta
from unittest.mock import Mock

import pytest

from data_formulator.automation.runtime import AutomationRuntime
from data_formulator.automation.scheduler import SchedulerTickResult
from data_formulator.automation.worker import AutomationWorkerDisabledError
from data_formulator.recipes.openers import WorkspaceOpenError
from data_formulator.security.code_signing import CodeSigningConfigurationError


pytestmark = [pytest.mark.backend]


def _tick_result() -> SchedulerTickResult:
    return SchedulerTickResult(
        checked_at="2026-08-20T09:00:00.000000Z",
        runs=(),
    )


def test_runtime_cycle_ticks_scheduler_before_claiming_one_run() -> None:
    order: list[str] = []
    scheduler = Mock()
    scheduler.tick.side_effect = lambda: (order.append("scheduler"), _tick_result())[1]
    worker = Mock()
    worker.run_once.side_effect = lambda: (order.append("worker"), None)[1]
    runtime = AutomationRuntime(
        scheduler,
        worker,
        enabled=True,
        poll_interval=timedelta(seconds=1),
    )

    result = runtime.run_cycle()

    assert order == ["scheduler", "worker"]
    assert result.scheduler == _tick_result()
    assert result.run is None


def test_runtime_stops_after_the_current_cycle_without_waiting() -> None:
    stop_event = threading.Event()
    scheduler = Mock()
    scheduler.tick.return_value = _tick_result()
    worker = Mock()
    worker.run_once.side_effect = lambda: stop_event.set()
    wait = Mock(side_effect=AssertionError("stop must avoid another wait"))
    runtime = AutomationRuntime(
        scheduler,
        worker,
        enabled=True,
        stop_event=stop_event,
        wait=wait,
    )

    assert runtime.run_forever() == 1
    scheduler.tick.assert_called_once_with()
    worker.run_once.assert_called_once_with()
    wait.assert_not_called()


def test_runtime_uses_interruptible_polling_between_idle_cycles() -> None:
    stop_event = threading.Event()
    scheduler = Mock()
    scheduler.tick.return_value = _tick_result()
    worker = Mock()
    worker.run_once.return_value = None

    def stop_during_wait(seconds: float) -> bool:
        assert seconds == 0.25
        stop_event.set()
        return True

    runtime = AutomationRuntime(
        scheduler,
        worker,
        enabled=True,
        stop_event=stop_event,
        poll_interval=timedelta(milliseconds=250),
        wait=stop_during_wait,
    )

    assert runtime.run_forever() == 1


def test_runtime_retries_only_explicit_sqlite_contention() -> None:
    stop_event = threading.Event()
    scheduler = Mock()
    scheduler.tick.side_effect = [
        sqlite3.OperationalError("database is locked"),
        _tick_result(),
    ]
    worker = Mock()
    worker.run_once.side_effect = lambda: stop_event.set()
    waits: list[float] = []

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        return False

    runtime = AutomationRuntime(
        scheduler,
        worker,
        enabled=True,
        stop_event=stop_event,
        poll_interval=timedelta(milliseconds=100),
        wait=wait,
    )

    assert runtime.run_forever() == 2
    assert waits == [0.1]
    worker.run_once.assert_called_once_with()

    scheduler.tick.side_effect = sqlite3.OperationalError("disk I/O error")
    stop_event.clear()
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        runtime.run_forever()


def test_environment_factory_fails_closed_before_creating_storage(
    tmp_path,
    monkeypatch,
) -> None:
    data_home = tmp_path / "must-not-be-created"
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(data_home))
    monkeypatch.setenv("AUTOMATION_ENABLED", "false")

    with pytest.raises(AutomationWorkerDisabledError, match="disabled"):
        AutomationRuntime.from_environment(worker_id="worker-a")
    assert not data_home.exists()

    monkeypatch.setenv("AUTOMATION_ENABLED", "true")
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    with pytest.raises(CodeSigningConfigurationError, match="stable"):
        AutomationRuntime.from_environment(worker_id="worker-a")
    assert not data_home.exists()

    monkeypatch.setenv("DF_CODE_SIGNING_SECRET", "stable-test-secret")
    monkeypatch.setenv("WORKSPACE_BACKEND", "ephemeral")
    with pytest.raises(WorkspaceOpenError, match="durable local"):
        AutomationRuntime.from_environment(worker_id="worker-a")
    assert not data_home.exists()


def test_data_home_factory_shares_one_absolute_catalog_and_workspace_root(
    tmp_path,
) -> None:
    data_home = tmp_path / "runtime-home"
    runtime = AutomationRuntime.for_data_home(
        data_home,
        worker_id="worker-a",
        enabled=True,
        connector_opener=Mock(),
    )

    assert runtime.data_home == data_home.resolve()
    assert runtime.database_path == (
        data_home.resolve() / "automation" / "automation.db"
    )


def test_runtime_rejects_non_positive_polling() -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        AutomationRuntime(
            Mock(),
            Mock(),
            enabled=True,
            poll_interval=timedelta(0),
        )
