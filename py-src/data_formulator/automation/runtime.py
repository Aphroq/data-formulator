# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resident, single-process lifecycle for Automation Scheduler and Worker."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from data_formulator.automation.models import StoredAutomationRun
from data_formulator.automation.repository import AutomationRepository
from data_formulator.automation.scheduler import (
    AutomationScheduler,
    SchedulerTickResult,
)
from data_formulator.automation.worker import (
    AttemptIdFactory,
    AutomationWorker,
    AutomationWorkerDisabledError,
    AutomationWorkerLeaseLostError,
    Clock,
    EnabledCheck,
    automation_enabled_from_environment,
)
from data_formulator.recipes.openers import (
    ExplicitConnectorOpener,
    LocalWorkspaceOpener,
    WorkspaceOpenError,
)
from data_formulator.recipes.repository import RecipeRepository
from data_formulator.security.code_signing import require_stable_code_signing


Wait = Callable[[float], bool]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AutomationCycleResult:
    scheduler: SchedulerTickResult
    run: StoredAutomationRun | None


class AutomationRuntime:
    """Repeatedly tick Schedules and execute one queued Run per cycle."""

    DEFAULT_POLL_INTERVAL = timedelta(seconds=1)

    def __init__(
        self,
        scheduler: AutomationScheduler,
        worker: AutomationWorker,
        *,
        enabled: bool | EnabledCheck = False,
        poll_interval: timedelta = DEFAULT_POLL_INTERVAL,
        stop_event: threading.Event | None = None,
        wait: Wait | None = None,
    ) -> None:
        if (
            not isinstance(poll_interval, timedelta)
            or poll_interval <= timedelta(0)
        ):
            raise ValueError("poll_interval must be a positive timedelta")
        if isinstance(enabled, bool):
            enabled_check: EnabledCheck = lambda: enabled
        elif callable(enabled):
            enabled_check = enabled
        else:
            raise TypeError("enabled must be a bool or callable")

        self._scheduler = scheduler
        self._worker = worker
        self._enabled = enabled_check
        self._poll_interval = poll_interval
        self._stop_event = stop_event or threading.Event()
        self._wait = wait or self._stop_event.wait

    @classmethod
    def for_data_home(
        cls,
        data_home: Path | str,
        *,
        worker_id: str,
        enabled: bool | EnabledCheck = False,
        storage_backend: str = "local",
        connector_opener: ExplicitConnectorOpener | None = None,
        clock: Clock | None = None,
        lease_duration: timedelta = AutomationWorker.DEFAULT_LEASE_DURATION,
        heartbeat_interval: timedelta | None = None,
        retry_delays: Sequence[timedelta] = AutomationWorker.DEFAULT_RETRY_DELAYS,
        attempt_id_factory: AttemptIdFactory | None = None,
        poll_interval: timedelta = DEFAULT_POLL_INTERVAL,
        stop_event: threading.Event | None = None,
        wait: Wait | None = None,
    ) -> "AutomationRuntime":
        resolved_home = Path(data_home).resolve()
        database_path = resolved_home / "automation" / "automation.db"
        repository = AutomationRepository(database_path, clock=clock)
        recipes = RecipeRepository(database_path)
        workspace_opener = LocalWorkspaceOpener(
            resolved_home,
            storage_backend=storage_backend,
        )
        worker = AutomationWorker(
            repository,
            recipes,
            workspace_opener,
            (
                connector_opener
                if connector_opener is not None
                else ExplicitConnectorOpener()
            ),
            worker_id=worker_id,
            enabled=enabled,
            clock=clock,
            lease_duration=lease_duration,
            heartbeat_interval=heartbeat_interval,
            retry_delays=retry_delays,
            attempt_id_factory=attempt_id_factory,
        )
        scheduler = AutomationScheduler(repository, clock=clock)
        return cls(
            scheduler,
            worker,
            enabled=enabled,
            poll_interval=poll_interval,
            stop_event=stop_event,
            wait=wait,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        worker_id: str,
        **kwargs: Any,
    ) -> "AutomationRuntime":
        from data_formulator.datalake.workspace import get_data_formulator_home

        if not automation_enabled_from_environment():
            raise AutomationWorkerDisabledError(
                "Automation Worker is disabled by AUTOMATION_ENABLED."
            )
        # Both checks deliberately precede repository/connector construction.
        require_stable_code_signing()
        storage_backend = os.getenv("WORKSPACE_BACKEND", "local")
        if storage_backend != "local":
            raise WorkspaceOpenError(
                "Automation requires a durable local Workspace backend"
            )
        return cls.for_data_home(
            get_data_formulator_home(),
            worker_id=worker_id,
            enabled=True,
            storage_backend=storage_backend,
            **kwargs,
        )

    @property
    def data_home(self) -> Path:
        return self._worker.data_home

    @property
    def database_path(self) -> Path:
        return self._worker.database_path

    def stop(self) -> None:
        """Request graceful shutdown after the current synchronous cycle."""
        self._stop_event.set()

    def run_cycle(self) -> AutomationCycleResult:
        """Tick due Schedules, then claim and execute at most one Run."""
        self._preflight()
        scheduled = self._scheduler.tick()
        run = self._worker.run_once()
        return AutomationCycleResult(scheduler=scheduled, run=run)

    def run_forever(self) -> int:
        """Run interruptible cycles until ``stop`` is requested."""
        cycles = 0
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except AutomationWorkerLeaseLostError:
                # One fenced-out attempt is isolated; the next claim performs
                # normal expiry recovery without allowing the stale attempt to
                # mutate logical terminal state.
                logger.warning(
                    "Automation Worker lost a Run lease; the attempt was not "
                    "finalized."
                )
            except sqlite3.OperationalError as exc:
                if not _is_sqlite_contention(exc):
                    raise
                logger.warning(
                    "Automation storage is temporarily busy; the next cycle "
                    "will retry."
                )
            cycles += 1
            if self._stop_event.is_set():
                break
            if self._wait(self._poll_interval.total_seconds()):
                break
        return cycles

    def _preflight(self) -> None:
        if self._enabled() is not True:
            raise AutomationWorkerDisabledError(
                "Automation Worker is disabled."
            )
        require_stable_code_signing()


def _is_sqlite_contention(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return "locked" in message or "busy" in message
