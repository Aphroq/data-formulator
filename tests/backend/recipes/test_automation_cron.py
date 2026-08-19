from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data_formulator.automation.cron import (
    CronExpression,
    CronExpressionError,
    next_cron_occurrence,
)


pytestmark = [pytest.mark.backend]


def test_cron_parser_supports_lists_ranges_steps_and_standard_day_union() -> None:
    business_hours = CronExpression.parse("*/15 9-17 * * 1-5")

    assert business_hours.matches_local(datetime(2026, 8, 17, 9, 0)) is True
    assert business_hours.matches_local(datetime(2026, 8, 17, 9, 7)) is False
    assert business_hours.matches_local(datetime(2026, 8, 16, 9, 0)) is False

    first_or_monday = CronExpression.parse("0 9 1 * 1")
    assert first_or_monday.matches_local(datetime(2026, 9, 1, 9, 0)) is True
    assert first_or_monday.matches_local(datetime(2026, 9, 7, 9, 0)) is True
    assert first_or_monday.matches_local(datetime(2026, 9, 8, 9, 0)) is False


@pytest.mark.parametrize(
    "expression",
    [
        "61 9 * * *",
        "0 24 * * *",
        "0 9 0 * *",
        "0 9 * 13 *",
        "0 9 * * 8",
        "*/0 9 * * *",
        "10-5 9 * * *",
        "0 9 JAN * *",
    ],
)
def test_cron_parser_rejects_values_outside_the_v1_numeric_contract(
    expression,
) -> None:
    with pytest.raises(CronExpressionError):
        CronExpression.parse(expression)


def test_next_occurrence_uses_the_schedule_timezone() -> None:
    result = next_cron_occurrence(
        "0 9 * * *",
        "America/New_York",
        datetime(2026, 8, 19, 13, tzinfo=timezone.utc),
    )

    assert result == datetime(2026, 8, 20, 13, tzinfo=timezone.utc)


def test_spring_forward_nonexistent_wall_time_is_skipped() -> None:
    result = next_cron_occurrence(
        "30 2 * * *",
        "America/New_York",
        datetime(2026, 3, 7, 7, 30, tzinfo=timezone.utc),
    )

    assert result == datetime(2026, 3, 9, 6, 30, tzinfo=timezone.utc)


def test_fall_back_repeated_wall_time_runs_only_once() -> None:
    result = next_cron_occurrence(
        "30 1 * * *",
        "America/New_York",
        datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc),
    )

    assert result == datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)


def test_fall_back_does_not_select_the_second_fold_when_called_between_folds(
) -> None:
    result = next_cron_occurrence(
        "30 1 * * *",
        "America/New_York",
        datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc),
    )

    assert result == datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)
