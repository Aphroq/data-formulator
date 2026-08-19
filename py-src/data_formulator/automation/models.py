# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed Schedule and durable Automation Run records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from data_formulator.recipes.models import HashDigest


_SCHEDULE_ID_PATTERN = re.compile(r"^sch_[0-9a-f]{32}$")
_RUN_ID_PATTERN = re.compile(r"^run_[0-9a-f]{32}$")


class AutomationRunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class AutomationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class StoredSchedule:
    schedule_id: str
    identity_id: str
    workspace_id: str
    version_id: str
    name: str
    cron_expression: str
    timezone: str
    enabled: bool
    next_run_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StoredAutomationRun:
    run_id: str
    identity_id: str
    workspace_id: str
    version_id: str
    schedule_id: str | None
    trigger: AutomationRunTrigger
    scheduled_for: str
    status: AutomationRunStatus
    attempt_count: int
    available_at: str
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: str | None
    cancel_requested_at: str | None
    artifact_run_id: str | None
    artifact_path: str | None
    manifest_hash: HashDigest | None
    binding_hash: HashDigest | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str


def validate_schedule_id(value: str) -> str:
    if not isinstance(value, str) or not _SCHEDULE_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "schedule_id must use the sch_ prefix followed by 32 lowercase "
            "hexadecimal characters"
        )
    return value


def validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not _RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "run_id must use the run_ prefix followed by 32 lowercase "
            "hexadecimal characters"
        )
    return value


def normalize_cron_expression(value: str) -> str:
    """Normalize whitespace while keeping v1 Cron parsing deliberately narrow."""
    if not isinstance(value, str):
        raise TypeError("cron_expression must be a string")
    fields = value.split()
    if len(fields) != 5:
        raise ValueError("cron_expression must contain exactly five fields")
    return " ".join(fields)


def normalize_timezone_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("timezone_name must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("timezone_name cannot be empty")
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"timezone_name must be a recognized IANA timezone: {normalized!r}"
        ) from exc
    return normalized


def normalize_utc_datetime(value: datetime, *, field_name: str) -> str:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
