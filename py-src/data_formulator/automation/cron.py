# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Small deterministic five-field Cron evaluator with explicit DST behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CronExpressionError(ValueError):
    """A five-field Cron expression cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class _CronField:
    name: str
    minimum: int
    maximum: int
    values: frozenset[int]
    wildcard: bool

    @classmethod
    def parse(
        cls,
        value: str,
        *,
        name: str,
        minimum: int,
        maximum: int,
        sunday_alias: bool = False,
    ) -> "_CronField":
        if not value:
            raise CronExpressionError(f"Cron {name} field cannot be empty")
        parsed: set[int] = set()
        for segment in value.split(","):
            if not segment:
                raise CronExpressionError(
                    f"Cron {name} field contains an empty list item"
                )
            base, separator, step_text = segment.partition("/")
            if separator and "/" in step_text:
                raise CronExpressionError(
                    f"Cron {name} field contains more than one step separator"
                )
            step = 1
            if separator:
                step = cls._parse_number(step_text, name)
                if step < 1:
                    raise CronExpressionError(
                        f"Cron {name} step must be positive"
                    )

            if base == "*":
                start, end = minimum, maximum
            elif "-" in base:
                start_text, range_separator, end_text = base.partition("-")
                if not range_separator or "-" in end_text:
                    raise CronExpressionError(
                        f"Cron {name} range is malformed"
                    )
                start = cls._parse_number(start_text, name)
                end = cls._parse_number(end_text, name)
            else:
                start = cls._parse_number(base, name)
                end = maximum if separator else start

            if start < minimum or start > maximum:
                raise CronExpressionError(
                    f"Cron {name} value {start} is outside "
                    f"{minimum}..{maximum}"
                )
            if end < minimum or end > maximum:
                raise CronExpressionError(
                    f"Cron {name} value {end} is outside "
                    f"{minimum}..{maximum}"
                )
            if end < start:
                raise CronExpressionError(
                    f"Cron {name} range must be ascending"
                )
            parsed.update(range(start, end + 1, step))

        if sunday_alias:
            parsed = {0 if item == 7 else item for item in parsed}
            full_range = set(range(0, 7))
        else:
            full_range = set(range(minimum, maximum + 1))
        if not parsed:
            raise CronExpressionError(f"Cron {name} field has no values")
        return cls(
            name=name,
            minimum=minimum,
            maximum=maximum,
            values=frozenset(parsed),
            wildcard=parsed == full_range,
        )

    @staticmethod
    def _parse_number(value: str, name: str) -> int:
        if not value or not value.isascii() or not value.isdecimal():
            raise CronExpressionError(
                f"Cron {name} field only supports numeric values"
            )
        return int(value)


@dataclass(frozen=True, slots=True)
class CronExpression:
    """Parsed numeric five-field Cron using standard DOM/DOW union semantics."""

    source: str
    minute: _CronField
    hour: _CronField
    day_of_month: _CronField
    month: _CronField
    day_of_week: _CronField

    @classmethod
    def parse(cls, value: str) -> "CronExpression":
        if not isinstance(value, str):
            raise TypeError("Cron expression must be a string")
        fields = value.split()
        if len(fields) != 5:
            raise CronExpressionError(
                "Cron expression must contain exactly five fields"
            )
        source = " ".join(fields)
        return cls(
            source=source,
            minute=_CronField.parse(
                fields[0],
                name="minute",
                minimum=0,
                maximum=59,
            ),
            hour=_CronField.parse(
                fields[1],
                name="hour",
                minimum=0,
                maximum=23,
            ),
            day_of_month=_CronField.parse(
                fields[2],
                name="day-of-month",
                minimum=1,
                maximum=31,
            ),
            month=_CronField.parse(
                fields[3],
                name="month",
                minimum=1,
                maximum=12,
            ),
            day_of_week=_CronField.parse(
                fields[4],
                name="day-of-week",
                minimum=0,
                maximum=7,
                sunday_alias=True,
            ),
        )

    def matches_local(self, value: datetime) -> bool:
        if not isinstance(value, datetime):
            raise TypeError("Cron matching requires a datetime")
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("Cron matching requires a naive local datetime")
        if value.minute not in self.minute.values:
            return False
        if value.hour not in self.hour.values:
            return False
        if value.month not in self.month.values:
            return False
        return self._day_matches(value)

    def next_after(self, after: datetime, timezone_name: str) -> datetime:
        if not isinstance(after, datetime):
            raise TypeError("Cron next occurrence requires a datetime")
        if after.tzinfo is None or after.utcoffset() is None:
            raise ValueError("Cron next occurrence requires a timezone-aware datetime")
        try:
            local_zone = ZoneInfo(timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise CronExpressionError(
                f"Cron timezone is not a recognized IANA timezone: {timezone_name!r}"
            ) from exc

        after_utc = after.astimezone(timezone.utc)
        local_after = after_utc.astimezone(local_zone)
        cursor = local_after.replace(
            second=0,
            microsecond=0,
            tzinfo=None,
        ) + timedelta(minutes=1)
        deadline_year = min(9999, local_after.year + 8)
        minimum_minute = min(self.minute.values)
        minimum_hour = min(self.hour.values)

        while cursor.year <= deadline_year:
            if cursor.month not in self.month.values:
                cursor = self._advance_month(cursor)
                continue
            if not self._day_matches(cursor):
                cursor = (cursor + timedelta(days=1)).replace(
                    hour=0,
                    minute=0,
                )
                continue
            if cursor.hour not in self.hour.values:
                later_hours = sorted(
                    item for item in self.hour.values if item > cursor.hour
                )
                if later_hours:
                    cursor = cursor.replace(
                        hour=later_hours[0],
                        minute=minimum_minute,
                    )
                else:
                    cursor = (cursor + timedelta(days=1)).replace(
                        hour=minimum_hour,
                        minute=minimum_minute,
                    )
                continue
            if cursor.minute not in self.minute.values:
                later_minutes = sorted(
                    item for item in self.minute.values if item > cursor.minute
                )
                if later_minutes:
                    cursor = cursor.replace(minute=later_minutes[0])
                else:
                    cursor = (cursor + timedelta(hours=1)).replace(
                        minute=minimum_minute,
                    )
                continue

            for candidate in self._utc_candidates(cursor, local_zone):
                if candidate > after_utc:
                    return candidate
            # A missing DST wall minute has no UTC candidate. Advancing the
            # naive wall clock also intentionally prevents a repeated fall-
            # back minute from running twice.
            cursor += timedelta(minutes=1)

        raise CronExpressionError(
            "Cron expression has no valid occurrence in the next eight years"
        )

    def _day_matches(self, value: datetime) -> bool:
        day_matches = value.day in self.day_of_month.values
        cron_weekday = (value.weekday() + 1) % 7
        weekday_matches = cron_weekday in self.day_of_week.values
        if self.day_of_month.wildcard and self.day_of_week.wildcard:
            return True
        if self.day_of_month.wildcard:
            return weekday_matches
        if self.day_of_week.wildcard:
            return day_matches
        return day_matches or weekday_matches

    def _advance_month(self, value: datetime) -> datetime:
        later_months = sorted(
            item for item in self.month.values if item > value.month
        )
        if later_months:
            return datetime(value.year, later_months[0], 1)
        if value.year >= 9999:
            raise CronExpressionError("Cron occurrence exceeds datetime range")
        return datetime(value.year + 1, min(self.month.values), 1)

    @staticmethod
    def _utc_candidates(
        local_value: datetime,
        local_zone: ZoneInfo,
    ) -> tuple[datetime, ...]:
        candidates: set[datetime] = set()
        for fold in (0, 1):
            aware = local_value.replace(tzinfo=local_zone, fold=fold)
            as_utc = aware.astimezone(timezone.utc)
            round_trip = as_utc.astimezone(local_zone)
            if round_trip.replace(tzinfo=None) == local_value:
                candidates.add(as_utc)
        if not candidates:
            return ()
        # An ambiguous fall-back wall minute represents one Schedule
        # occurrence. Always choose its first fold, even when ``after`` falls
        # between the two UTC instants, so the same wall minute cannot be
        # selected twice across restarts or recalculations.
        return (min(candidates),)


def next_cron_occurrence(
    expression: str,
    timezone_name: str,
    after: datetime,
) -> datetime:
    return CronExpression.parse(expression).next_after(after, timezone_name)
