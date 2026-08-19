# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""One-shot, transaction-backed Scheduler orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from data_formulator.automation.cron import next_cron_occurrence
from data_formulator.automation.models import (
    StoredAutomationRun,
    StoredSchedule,
    normalize_utc_datetime,
)
from data_formulator.automation.repository import AutomationRepository


NextRunCalculator = Callable[[StoredSchedule, datetime], datetime]


@dataclass(frozen=True, slots=True)
class SchedulerTickResult:
    checked_at: str
    runs: tuple[StoredAutomationRun, ...]


class AutomationScheduler:
    """Evaluate all due Schedules once without owning a background thread."""

    def __init__(
        self,
        repository: AutomationRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        next_run_calculator: NextRunCalculator | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._next_run_calculator = (
            next_run_calculator or self._calculate_next_run
        )

    def tick(self) -> SchedulerTickResult:
        now = self._clock()
        checked_at = normalize_utc_datetime(now, field_name="scheduler clock")
        runs = self._repository._tick_due_schedules(
            now=now,
            next_run_calculator=self._next_run_calculator,
        )
        return SchedulerTickResult(checked_at=checked_at, runs=runs)

    @staticmethod
    def _calculate_next_run(
        schedule: StoredSchedule,
        after: datetime,
    ) -> datetime:
        return next_cron_occurrence(
            schedule.cron_expression,
            schedule.timezone,
            after,
        )
