from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from data_formulator.datalake.ephemeral_workspace import EphemeralWorkspaceManager
from data_formulator.datalake.workspace_manager import WorkspaceManager
from data_formulator.recipes.lineage import (
    ArtifactConflictError,
    ArtifactLedger,
    ArtifactLineageError,
    ArtifactScopeError,
    DurableArtifactStorageRequired,
)
from data_formulator.recipes.models import ArtifactNode, ArtifactType, HashDigest


pytestmark = [pytest.mark.backend]


def _artifact(
    *,
    origin_id: str,
    artifact_type: ArtifactType = ArtifactType.LOAD,
    parent_ids: tuple[str, ...] = (),
    identity_id: str = "user:alice",
    workspace_id: str = "workspace-1",
    content: bytes = b"content",
) -> ArtifactNode:
    return ArtifactNode(
        artifact_type=artifact_type,
        identity_id=identity_id,
        workspace_id=workspace_id,
        origin_id=origin_id,
        parent_ids=parent_ids,
        content_hash=HashDigest.sha256(content),
        schema_fingerprint=HashDigest.sha256(b"schema"),
        execution={"kind": artifact_type.value, "origin": origin_id},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def durable_workspace(tmp_path):
    manager = WorkspaceManager(tmp_path / "workspaces")
    return manager.create_and_open_workspace("workspace-1", "user:alice")


def test_workspace_exposes_explicit_artifact_storage_capabilities(durable_workspace) -> None:
    capabilities = durable_workspace.storage_capabilities

    assert durable_workspace.identity_id == "user:alice"
    assert durable_workspace.workspace_id == "workspace-1"
    assert capabilities.storage_backend == "local"
    assert capabilities.durable is True
    assert capabilities.supports_durable_artifacts is True


def test_ledger_persists_under_workspace_root_and_reloads(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    artifact = _artifact(origin_id="load/orders")

    recorded = ledger.record(artifact)
    restored = ArtifactLedger.for_workspace(durable_workspace)

    assert recorded == artifact
    assert ledger.root == durable_workspace.confined_root.root / "artifacts" / "lineage"
    assert ledger.root.is_relative_to(durable_workspace.confined_root.root)
    assert not ledger.root.is_relative_to(durable_workspace.confined_scratch.root)
    assert restored.get(artifact.artifact_id) == artifact
    assert restored.get_by_origin("load/orders") == artifact


def test_record_is_idempotent_for_same_artifact_and_origin(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    artifact = _artifact(origin_id="load/orders")
    retried_payload = artifact.to_dict()
    retried_payload["created_at"] = (
        artifact.created_at + timedelta(minutes=5)
    ).isoformat()
    retried = ArtifactNode.from_dict(retried_payload)

    assert ledger.record(artifact) == artifact
    assert retried.artifact_id == artifact.artifact_id
    assert ledger.record(retried) == artifact
    assert ledger.list_nodes() == (artifact,)


def test_origin_cannot_be_rebound_to_different_artifact(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    ledger.record(_artifact(origin_id="load/orders", content=b"version one"))

    with pytest.raises(ArtifactConflictError, match="origin"):
        ledger.record(_artifact(origin_id="load/orders", content=b"version two"))


def test_record_rejects_missing_parent(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    child = _artifact(
        origin_id="transform/orders",
        artifact_type=ArtifactType.TRANSFORM,
        parent_ids=("art_" + "9" * 64,),
    )

    with pytest.raises(ArtifactLineageError, match="parent"):
        ledger.record(child)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"identity_id": "user:bob"}, "identity"),
        ({"workspace_id": "workspace-2"}, "workspace"),
    ],
)
def test_record_rejects_cross_scope_artifacts(
    durable_workspace,
    overrides: dict[str, str],
    message: str,
) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)

    with pytest.raises(ArtifactScopeError, match=message):
        ledger.record(_artifact(origin_id="load/foreign", **overrides))


def test_record_many_is_atomic_and_accepts_parents_from_same_batch(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    parent = _artifact(origin_id="load/orders")
    child = _artifact(
        origin_id="transform/orders",
        artifact_type=ArtifactType.TRANSFORM,
        parent_ids=(parent.artifact_id,),
    )

    assert ledger.record_many((parent, child)) == (parent, child)

    other = _artifact(origin_id="load/customers", content=b"customers")
    broken = _artifact(
        origin_id="chart/broken",
        artifact_type=ArtifactType.CHART,
        parent_ids=("art_" + "8" * 64,),
    )
    with pytest.raises(ArtifactLineageError, match="parent"):
        ledger.record_many((other, broken))

    assert ledger.get(other.artifact_id) is None


def test_concurrent_records_do_not_lose_artifacts(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    artifacts = tuple(
        _artifact(
            origin_id=f"load/table-{index}",
            content=f"table-{index}".encode(),
        )
        for index in range(8)
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        recorded = tuple(executor.map(ledger.record, artifacts))

    assert {node.artifact_id for node in recorded} == {
        node.artifact_id for node in artifacts
    }
    assert {node.artifact_id for node in ledger.list_nodes()} == {
        node.artifact_id for node in artifacts
    }


def test_ledger_fails_closed_when_persisted_identity_is_corrupted(durable_workspace) -> None:
    ledger = ArtifactLedger.for_workspace(durable_workspace)
    artifact = ledger.record(_artifact(origin_id="load/orders"))
    payload = json.loads(ledger.storage_path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["content_hash"] = str(HashDigest.sha256(b"tampered"))
    ledger.storage_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactLineageError, match="corrupt"):
        ArtifactLedger.for_workspace(durable_workspace)


def test_ephemeral_workspace_rejects_durable_artifact_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EPHEMERAL_WORKSPACE_ROOT", str(tmp_path / "ephemeral"))
    manager = EphemeralWorkspaceManager("user:alice")
    workspace = manager.create_and_open_workspace("workspace-1", "user:alice")

    assert workspace.storage_capabilities.durable is False
    assert workspace.storage_capabilities.supports_durable_artifacts is False
    with pytest.raises(DurableArtifactStorageRequired, match="durable"):
        ArtifactLedger.for_workspace(workspace)


def test_durable_backend_without_artifact_api_fails_closed(tmp_path) -> None:
    manager = WorkspaceManager(
        tmp_path / "workspaces",
        storage_backend="azure_blob",
        durable=True,
        supports_durable_artifacts=False,
    )
    workspace = manager.create_and_open_workspace("workspace-1", "user:alice")

    assert workspace.storage_capabilities.durable is True
    assert workspace.storage_capabilities.supports_durable_artifacts is False
    with pytest.raises(DurableArtifactStorageRequired, match="azure_blob"):
        ArtifactLedger.for_workspace(workspace)
