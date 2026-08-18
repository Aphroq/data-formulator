from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from data_formulator.recipes.models import ArtifactNode, ArtifactType, HashDigest


pytestmark = [pytest.mark.backend]


def _artifact(**overrides: object) -> ArtifactNode:
    values: dict[str, object] = {
        "artifact_type": ArtifactType.LOAD,
        "identity_id": "user:alice",
        "workspace_id": "workspace-1",
        "origin_id": "data-operation/op-1/plan-abc/step/0",
        "parent_ids": (),
        "content_hash": HashDigest.sha256(b"table bytes"),
        "schema_fingerprint": HashDigest.sha256(b"schema bytes"),
        "execution": {
            "kind": "connector_query",
            "source_id": "warehouse",
            "plan_hash": "plan-abc",
        },
        "created_at": datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ArtifactNode(**values)  # type: ignore[arg-type]


def test_artifact_round_trip_preserves_verified_identity() -> None:
    artifact = _artifact()

    restored = ArtifactNode.from_dict(artifact.to_dict())

    assert restored == artifact
    assert restored.artifact_id.startswith("art_")
    assert len(restored.artifact_id) == len("art_") + 64


def test_artifact_identity_ignores_observation_time_but_includes_execution() -> None:
    first = _artifact()
    retry = _artifact(created_at=first.created_at + timedelta(minutes=5))
    changed_execution = _artifact(execution={"kind": "connector_query", "plan_hash": "other"})

    assert retry.artifact_id == first.artifact_id
    assert changed_execution.artifact_id != first.artifact_id


def test_artifact_rejects_tampered_serialized_identity() -> None:
    serialized = _artifact().to_dict()
    serialized["execution"]["plan_hash"] = "tampered"

    with pytest.raises(ValueError, match="artifact_id"):
        ArtifactNode.from_dict(serialized)


def test_artifact_execution_is_deeply_immutable() -> None:
    execution = {"kind": "transform", "params": {"columns": ["amount"]}}
    artifact = _artifact(
        artifact_type=ArtifactType.TRANSFORM,
        parent_ids=("art_" + "1" * 64,),
        execution=execution,
    )
    execution["params"]["columns"].append("tax")

    assert artifact.to_dict()["execution"]["params"]["columns"] == ["amount"]
    with pytest.raises(TypeError):
        artifact.execution["kind"] = "load"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        artifact.origin_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("artifact_type", "parent_ids"),
    [
        (ArtifactType.LOAD, ("art_" + "1" * 64,)),
        (ArtifactType.TRANSFORM, ()),
        (ArtifactType.CHART, ()),
    ],
)
def test_artifact_type_enforces_parent_constraints(
    artifact_type: ArtifactType,
    parent_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="parent"):
        _artifact(artifact_type=artifact_type, parent_ids=parent_ids)


@pytest.mark.parametrize(
    "value",
    ["", "sha256:not-hex", "sha256:" + "0" * 63, "md5:" + "0" * 32],
)
def test_hash_digest_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError):
        HashDigest.parse(value)
