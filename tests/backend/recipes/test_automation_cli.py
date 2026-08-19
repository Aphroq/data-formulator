from __future__ import annotations

import signal
import tomllib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from data_formulator.automation.cli import main, parse_args
from data_formulator.automation.runtime import AutomationCycleResult
from data_formulator.automation.scheduler import SchedulerTickResult
from data_formulator.automation.worker import AutomationWorkerDisabledError


pytestmark = [pytest.mark.backend]


def _cycle_result() -> AutomationCycleResult:
    return AutomationCycleResult(
        scheduler=SchedulerTickResult(
            checked_at="2026-08-20T09:00:00.000000Z",
            runs=(),
        ),
        run=None,
    )


def test_worker_console_script_is_packaged() -> None:
    project = tomllib.loads(
        Path("pyproject.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["scripts"]["data_formulator_worker"] == (
        "data_formulator.automation.cli:main"
    )


def test_cli_once_builds_runtime_and_executes_one_cycle() -> None:
    runtime = Mock()
    runtime.data_home = Path.cwd()
    runtime.run_cycle.return_value = _cycle_result()

    with patch(
        "data_formulator.automation.cli.AutomationRuntime.from_environment",
        return_value=runtime,
    ) as factory:
        exit_code = main(
            [
                "--once",
                "--worker-id",
                "worker-test",
                "--poll-interval-seconds",
                "0.25",
                "--lease-seconds",
                "45",
                "--heartbeat-seconds",
                "5",
            ]
        )

    assert exit_code == 0
    runtime.run_cycle.assert_called_once_with()
    runtime.run_forever.assert_not_called()
    factory.assert_called_once()
    kwargs = factory.call_args.kwargs
    assert kwargs["worker_id"] == "worker-test"
    assert kwargs["poll_interval"].total_seconds() == 0.25
    assert kwargs["lease_duration"].total_seconds() == 45
    assert kwargs["heartbeat_interval"].total_seconds() == 5


def test_resident_cli_installs_and_restores_graceful_stop_signals() -> None:
    runtime = Mock()
    runtime.data_home = Path.cwd()
    captured_stop_event = None
    previous = signal.getsignal(signal.SIGTERM)

    def factory(**kwargs):
        nonlocal captured_stop_event
        captured_stop_event = kwargs["stop_event"]
        return runtime

    def request_stop_from_handler():
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        assert captured_stop_event is not None
        assert captured_stop_event.is_set()
        return 1

    runtime.run_forever.side_effect = request_stop_from_handler
    with patch(
        "data_formulator.automation.cli.AutomationRuntime.from_environment",
        side_effect=factory,
    ):
        assert main(["--worker-id", "worker-test"]) == 0

    assert signal.getsignal(signal.SIGTERM) is previous
    runtime.run_forever.assert_called_once_with()


def test_cli_returns_safe_errors_without_echoing_exception_details(
    capsys,
) -> None:
    with patch(
        "data_formulator.automation.cli.AutomationRuntime.from_environment",
        side_effect=AutomationWorkerDisabledError("token=do-not-print"),
    ):
        assert main(["--once"]) == 2
    disabled_error = capsys.readouterr().err
    assert "disabled" in disabled_error.lower()
    assert "do-not-print" not in disabled_error

    with patch(
        "data_formulator.automation.cli.AutomationRuntime.from_environment",
        side_effect=RuntimeError("password=do-not-print"),
    ):
        assert main(["--once"]) == 1
    unexpected_error = capsys.readouterr().err
    assert "unexpectedly" in unexpected_error.lower()
    assert "do-not-print" not in unexpected_error


def test_cli_rejects_heartbeat_not_shorter_than_lease_before_factory(
    capsys,
) -> None:
    with patch(
        "data_formulator.automation.cli.AutomationRuntime.from_environment"
    ) as factory:
        assert main(
            ["--lease-seconds", "10", "--heartbeat-seconds", "10"]
        ) == 2

    factory.assert_not_called()
    assert "shorter" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--poll-interval-seconds", "0"],
        ["--lease-seconds", "-1"],
        ["--heartbeat-seconds", "not-a-number"],
        ["--worker-id", "   "],
    ],
)
def test_cli_rejects_invalid_numeric_and_identity_arguments(arguments) -> None:
    with pytest.raises(SystemExit) as error:
        parse_args(arguments)
    assert error.value.code == 2
