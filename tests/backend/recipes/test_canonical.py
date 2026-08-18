from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from data_formulator.recipes.canonical import (
    canonical_json_bytes,
    canonical_sha256,
    freeze_json,
    thaw_json,
)


pytestmark = [pytest.mark.backend]


def test_canonical_json_is_stable_across_mapping_order() -> None:
    first = {"z": [3, 2, 1], "a": {"name": "café", "enabled": True}}
    second = {"a": {"enabled": True, "name": "café"}, "z": [3, 2, 1]}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_sha256(first) == canonical_sha256(second)
    assert b"caf\xc3\xa9" in canonical_json_bytes(first)


@pytest.mark.parametrize(
    "value",
    [
        {1: "non-string key"},
        {"value": math.nan},
        {"value": math.inf},
        {"value": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        {"value": b"bytes are not JSON"},
    ],
)
def test_canonical_json_rejects_values_without_a_portable_wire_form(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_json_bytes(value)


def test_freeze_json_deep_copies_and_makes_nested_values_immutable() -> None:
    source = {"filters": [{"column": "region", "values": ["west"]}]}

    frozen = freeze_json(source)
    source["filters"][0]["values"].append("east")

    assert thaw_json(frozen) == {
        "filters": [{"column": "region", "values": ["west"]}],
    }
    with pytest.raises(TypeError):
        frozen["filters"][0]["column"] = "country"  # type: ignore[index]
    with pytest.raises(AttributeError):
        frozen["filters"].append({})  # type: ignore[union-attr]
