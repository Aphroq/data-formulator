# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed Automation parameter policies and immutable Run value snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from data_formulator.automation.models import (
    normalize_timezone_name,
    parse_utc_datetime,
)
from data_formulator.recipes.binding import bind_recipe_parameters
from data_formulator.recipes.canonical import (
    FrozenJsonValue,
    canonical_json_bytes,
    freeze_json,
    thaw_json,
)
from data_formulator.recipes.spec import ParameterType, RecipeSpec


MAX_PARAMETER_COUNT = 100
MAX_PARAMETER_JSON_BYTES = 64 * 1024
MAX_SCHEDULE_OFFSET_DAYS = 3660


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a JSON object")
    if len(value) > MAX_PARAMETER_COUNT:
        raise ValueError(
            f"{field_name} cannot contain more than {MAX_PARAMETER_COUNT} entries"
        )
    if any(type(key) is not str for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    field_name: str,
) -> None:
    if set(value) != expected:
        raise ValueError(
            f"{field_name} must contain exactly {sorted(expected)}"
        )


def normalize_manual_parameter_values(
    spec: RecipeSpec,
    provided: Mapping[str, Any],
) -> Mapping[str, FrozenJsonValue]:
    """Resolve defaults and validate values against a Recipe's typed slots."""
    values = _require_mapping(provided, "parameters")
    resolved = bind_recipe_parameters(spec, values).parameter_values
    frozen = freeze_json(thaw_json(resolved))
    if not isinstance(frozen, Mapping):  # pragma: no cover - object built above
        raise TypeError("parameters must resolve to a JSON object")
    return frozen


def normalize_schedule_parameter_policy(
    spec: RecipeSpec,
    provided: Mapping[str, Any],
) -> Mapping[str, FrozenJsonValue]:
    """Validate and complete a fixed-version Schedule parameter policy."""
    policy = _require_mapping(provided, "parameter_policy")
    parameters = {item.id: item for item in spec.parameters}
    unknown = sorted(set(policy) - set(parameters))
    if unknown:
        raise ValueError(f"Unknown parameter value(s): {unknown}")

    normalized: dict[str, Any] = {}
    for parameter in spec.parameters:
        entry = policy.get(parameter.id)
        if entry is None:
            if parameter.has_default:
                normalized[parameter.id] = {
                    "source": "literal",
                    "value": thaw_json(parameter.default_value),
                }
                continue
            if parameter.required:
                raise ValueError(f"Missing required parameter: {parameter.id}")
            continue

        entry = _require_mapping(
            entry,
            f"parameter_policy.{parameter.id}",
        )
        source = entry.get("source")
        if source == "literal":
            _require_exact_fields(
                entry,
                {"source", "value"},
                field_name=f"parameter_policy.{parameter.id}",
            )
            value = entry["value"]
            parameter.validate_value(value)
            normalized[parameter.id] = {
                "source": "literal",
                "value": value,
            }
            continue

        expected_type = {
            "scheduled_date": ParameterType.DATE,
            "scheduled_datetime": ParameterType.DATETIME,
        }.get(source)
        if expected_type is None:
            raise ValueError(
                f"parameter_policy.{parameter.id}.source is unsupported"
            )
        _require_exact_fields(
            entry,
            {"source", "offset_days"},
            field_name=f"parameter_policy.{parameter.id}",
        )
        if parameter.value_type is not expected_type:
            raise TypeError(
                f"Parameter {parameter.id!r} cannot use {source}"
            )
        offset_days = entry["offset_days"]
        if (
            type(offset_days) is not int
            or abs(offset_days) > MAX_SCHEDULE_OFFSET_DAYS
        ):
            raise ValueError(
                f"parameter_policy.{parameter.id}.offset_days must be an integer "
                f"between {-MAX_SCHEDULE_OFFSET_DAYS} and "
                f"{MAX_SCHEDULE_OFFSET_DAYS}"
            )
        normalized[parameter.id] = {
            "source": source,
            "offset_days": offset_days,
        }

    frozen = freeze_json(normalized)
    if not isinstance(frozen, Mapping):  # pragma: no cover - object built above
        raise TypeError("parameter_policy must resolve to a JSON object")
    serialize_parameter_mapping(frozen, field_name="parameter_policy")
    return frozen


def resolve_schedule_parameter_policy(
    policy: Mapping[str, Any],
    *,
    scheduled_for: str | datetime,
    timezone_name: str,
) -> Mapping[str, FrozenJsonValue]:
    """Freeze the values a logical Run will use at its planned time."""
    entries = _require_mapping(policy, "parameter_policy")
    timezone_name = normalize_timezone_name(timezone_name)
    if isinstance(scheduled_for, str):
        instant = parse_utc_datetime(scheduled_for, field_name="scheduled_for")
    elif isinstance(scheduled_for, datetime):
        if scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        instant = scheduled_for
    else:
        raise TypeError("scheduled_for must be a datetime or normalized string")
    local = instant.astimezone(ZoneInfo(timezone_name))

    resolved: dict[str, Any] = {}
    for parameter_id, raw_entry in entries.items():
        entry = _require_mapping(
            raw_entry,
            f"parameter_policy.{parameter_id}",
        )
        source = entry.get("source")
        if source == "literal":
            _require_exact_fields(
                entry,
                {"source", "value"},
                field_name=f"parameter_policy.{parameter_id}",
            )
            resolved[parameter_id] = thaw_json(entry["value"])
            continue
        if source not in {"scheduled_date", "scheduled_datetime"}:
            raise ValueError(
                f"parameter_policy.{parameter_id}.source is unsupported"
            )
        _require_exact_fields(
            entry,
            {"source", "offset_days"},
            field_name=f"parameter_policy.{parameter_id}",
        )
        offset_days = entry["offset_days"]
        if (
            type(offset_days) is not int
            or abs(offset_days) > MAX_SCHEDULE_OFFSET_DAYS
        ):
            raise ValueError(
                f"parameter_policy.{parameter_id}.offset_days is invalid"
            )
        shifted = local + timedelta(days=offset_days)
        resolved[parameter_id] = (
            shifted.date().isoformat()
            if source == "scheduled_date"
            else shifted.isoformat()
        )

    frozen = freeze_json(resolved)
    if not isinstance(frozen, Mapping):  # pragma: no cover - object built above
        raise TypeError("resolved parameters must be a JSON object")
    serialize_parameter_mapping(frozen, field_name="parameters")
    return frozen


def serialize_parameter_mapping(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> str:
    payload = canonical_json_bytes(_require_mapping(value, field_name))
    if len(payload) > MAX_PARAMETER_JSON_BYTES:
        raise ValueError(
            f"{field_name} cannot exceed {MAX_PARAMETER_JSON_BYTES} bytes"
        )
    return payload.decode("utf-8")


def deserialize_parameter_mapping(
    value: str,
    *,
    field_name: str,
) -> Mapping[str, FrozenJsonValue]:
    if type(value) is not str:
        raise TypeError(f"{field_name} JSON must be a string")
    if len(value.encode("utf-8")) > MAX_PARAMETER_JSON_BYTES:
        raise ValueError(
            f"{field_name} cannot exceed {MAX_PARAMETER_JSON_BYTES} bytes"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} contains invalid JSON") from exc
    mapping = _require_mapping(parsed, field_name)
    frozen = freeze_json(mapping)
    if not isinstance(frozen, Mapping):  # pragma: no cover - checked above
        raise TypeError(f"{field_name} must be a JSON object")
    return frozen
