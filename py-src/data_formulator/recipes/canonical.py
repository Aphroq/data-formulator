# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Small, strict helpers for stable JSON hashing.

The recipe wire models intentionally accept only values with an unambiguous
JSON representation.  This keeps identity computation independent of Python
object reprs, locale, mapping insertion order, and mutable caller state.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, TypeAlias


JsonPrimitive: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
FrozenJsonValue: TypeAlias = (
    JsonPrimitive | tuple["FrozenJsonValue", ...] | Mapping[str, "FrozenJsonValue"]
)


def _normalize_json(value: Any, *, path: str = "$") -> JsonValue:
    """Return a detached JSON tree or reject values without a portable form."""
    if value is None or type(value) in (bool, int, str):
        return value

    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"Non-finite number at {path}")
        return value

    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise TypeError(f"JSON object key at {path} must be a string")
            normalized[key] = _normalize_json(child, path=f"{path}.{key}")
        return normalized

    if isinstance(value, (list, tuple)):
        return [
            _normalize_json(child, path=f"{path}[{index}]")
            for index, child in enumerate(value)
        ]

    raise TypeError(f"Unsupported JSON value at {path}: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize *value* to deterministic, whitespace-free UTF-8 JSON."""
    normalized = _normalize_json(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the lowercase SHA-256 hex digest of canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _freeze_normalized(value: JsonValue) -> FrozenJsonValue:
    if isinstance(value, dict):
        return MappingProxyType({
            key: _freeze_normalized(child)
            for key, child in value.items()
        })
    if isinstance(value, list):
        return tuple(_freeze_normalized(child) for child in value)
    return value


def freeze_json(value: Any) -> FrozenJsonValue:
    """Deep-copy a JSON value into tuples and read-only mappings."""
    return _freeze_normalized(_normalize_json(value))


def thaw_json(value: Any) -> JsonValue:
    """Return a detached mutable JSON tree from a frozen JSON value."""
    return _normalize_json(value)
