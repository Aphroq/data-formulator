from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.canonical import canonical_json_bytes
from data_formulator.recipes.lineage import ArtifactLedger
from data_formulator.recipes.models import ArtifactNode, ArtifactType, HashDigest
from data_formulator.recipes.visualize import (
    MissingParentArtifactError,
    record_visualize_artifacts,
)
from data_formulator.security.code_signing import sign_code


pytestmark = [pytest.mark.backend]


def _seed_load_artifact(workspace: Workspace) -> ArtifactNode:
    metadata = workspace.write_parquet_from_arrow(
        pa.table({"region": ["west", "east"], "amount": [10, 20]}),
        "orders",
    )
    path = workspace.get_file_path(metadata.filename)
    schema = pq.read_schema(path)
    node = ArtifactNode(
        artifact_type=ArtifactType.LOAD,
        identity_id=workspace.identity_id,
        workspace_id=workspace.workspace_id,
        origin_id="data-operation/op-1/plan/hash-1/step/0",
        parent_ids=(),
        content_hash=HashDigest(
            "sha256",
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ),
        schema_fingerprint=HashDigest.sha256(schema.serialize().to_pybytes()),
        execution={
            "kind": "connector_query",
            "step": {"source_id": "warehouse", "source_table": "orders"},
            "output": {"table_id": metadata.name, "filename": metadata.filename},
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ArtifactLedger.for_workspace(workspace).record(node)
    metadata.import_options = {
        "data_operation": {"artifact_id": node.artifact_id},
    }
    workspace.add_table_metadata(metadata)
    return node


def _write_derived_table(workspace: Workspace) -> None:
    workspace.write_parquet(
        pd.DataFrame({"region": ["west", "east"], "total": [10, 20]}),
        "derived",
        source_info={
            "loader_type": "AnalystTransform",
            "import_options": {
                "visualize": {
                    "chart_id": "chart-abc",
                    "input_tables": ["orders"],
                },
            },
        },
    )


def _record_table_chart(workspace: Workspace, *, chart_id: str = "chart-abc"):
    code = "result_df = orders.copy()"
    return record_visualize_artifacts(
        workspace,
        chart_id=chart_id,
        input_table_names=("orders",),
        output_table_name="derived",
        code=code,
        code_signature=sign_code(code),
        output_variable="result_df",
        chart_spec={"chart_type": "Table", "encodings": {}},
        field_metadata={},
        field_display_names={},
        display_instruction="Inspect orders",
        title="Orders",
        subtitle="",
    )


def test_visualize_records_transform_and_chart_atomically(tmp_path) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    parent = _seed_load_artifact(workspace)
    _write_derived_table(workspace)
    chart_spec = {
        "chart_type": "Bar Chart",
        "encodings": {"x": "region", "y": "total"},
    }
    code = "result_df = orders.groupby('region').sum()"
    code_signature = sign_code(code)

    artifacts = record_visualize_artifacts(
        workspace,
        chart_id="chart-abc",
        input_table_names=("orders",),
        output_table_name="derived",
        code=code,
        code_signature=code_signature,
        output_variable="result_df",
        chart_spec=chart_spec,
        field_metadata={"total": {"semantic_type": "number"}},
        field_display_names={"total": "Total"},
        display_instruction="Compare totals by region",
        title="Regional totals",
        subtitle="Current selection",
    )

    assert artifacts.transform.artifact_type is ArtifactType.TRANSFORM
    assert artifacts.transform.parent_ids == (parent.artifact_id,)
    assert artifacts.transform.origin_id == "visualize/chart-abc/transform"
    assert artifacts.transform.to_dict()["execution"] == {
        "kind": "python_transform",
        "code": code,
        "code_signature": code_signature,
        "output_variable": "result_df",
        "input_tables": [{
            "table_id": "orders",
            "artifact_id": parent.artifact_id,
        }],
        "output": {
            "table_id": "derived",
            "filename": "derived.parquet",
        },
    }
    assert artifacts.chart.artifact_type is ArtifactType.CHART
    assert artifacts.chart.parent_ids == (artifacts.transform.artifact_id,)
    assert artifacts.chart.origin_id == "visualize/chart-abc/chart"
    chart_execution = artifacts.chart.to_dict()["execution"]
    assert chart_execution == {
        "kind": "chart",
        "chart_id": "chart-abc",
        "chart": chart_spec,
        "field_metadata": {"total": {"semantic_type": "number"}},
        "field_display_names": {"total": "Total"},
        "display_instruction": "Compare totals by region",
        "title": "Regional totals",
        "subtitle": "Current selection",
        "input_table": {
            "table_id": "derived",
            "artifact_id": artifacts.transform.artifact_id,
        },
    }
    assert artifacts.chart.content_hash == HashDigest.sha256(
        canonical_json_bytes(chart_execution)
    )
    assert (
        artifacts.chart.schema_fingerprint
        == artifacts.transform.schema_fingerprint
    )
    assert ArtifactLedger.for_workspace(workspace).list_nodes() == (
        parent,
        artifacts.transform,
        artifacts.chart,
    )
    metadata = workspace.get_table_metadata("derived")
    assert metadata.import_options["artifact_id"] == artifacts.transform.artifact_id
    assert metadata.import_options["visualize"]["chart_artifact_id"] == (
        artifacts.chart.artifact_id
    )


def test_visualize_refuses_missing_parent_but_keeps_output_table(tmp_path) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    workspace.write_parquet(pd.DataFrame({"value": [1]}), "manual_input")
    workspace.write_parquet(pd.DataFrame({"value": [2]}), "derived")
    code = "result_df = manual_input.copy()"

    with pytest.raises(MissingParentArtifactError, match="manual_input"):
        record_visualize_artifacts(
            workspace,
            chart_id="chart-abc",
            input_table_names=("manual_input",),
            output_table_name="derived",
            code=code,
            code_signature=sign_code(code),
            output_variable="result_df",
            chart_spec={"chart_type": "Table", "encodings": {}},
            field_metadata={},
            field_display_names={},
            display_instruction="Inspect values",
            title="Values",
            subtitle="",
        )

    assert workspace.get_table_metadata("derived") is not None
    assert ArtifactLedger.for_workspace(workspace).list_nodes() == ()


@pytest.mark.parametrize(
    "changed_parent",
    [
        pa.table({"region": ["west", "east"], "amount": [100, 200]}),
        pa.table({"region": ["west", "east"], "amount": ["100", "200"]}),
    ],
    ids=("content", "schema"),
)
def test_visualize_rejects_changed_linked_parent_before_recording(
    tmp_path,
    changed_parent: pa.Table,
) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    parent = _seed_load_artifact(workspace)
    _write_derived_table(workspace)
    pq.write_table(changed_parent, workspace.get_parquet_path("orders"))

    with pytest.raises(MissingParentArtifactError, match="current table"):
        _record_table_chart(workspace)

    assert ArtifactLedger.for_workspace(workspace).list_nodes() == (parent,)


def test_visualize_rejects_changed_parent_found_by_ledger_fallback(tmp_path) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    parent = _seed_load_artifact(workspace)
    metadata = workspace.get_table_metadata("orders")
    metadata.import_options = {}
    workspace.add_table_metadata(metadata)
    _write_derived_table(workspace)
    pq.write_table(
        pa.table({"region": ["west", "east"], "amount": [30, 40]}),
        workspace.get_parquet_path("orders"),
    )

    with pytest.raises(MissingParentArtifactError, match="current table"):
        _record_table_chart(workspace)

    assert ArtifactLedger.for_workspace(workspace).list_nodes() == (parent,)


def test_visualize_does_not_record_transform_when_chart_payload_is_invalid(
    tmp_path,
) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    parent = _seed_load_artifact(workspace)
    _write_derived_table(workspace)
    code = "result_df = orders.copy()"

    with pytest.raises(TypeError, match="datetime"):
        record_visualize_artifacts(
            workspace,
            chart_id="chart-abc",
            input_table_names=("orders",),
            output_table_name="derived",
            code=code,
            code_signature=sign_code(code),
            output_variable="result_df",
            chart_spec={"chart_type": "Table", "created_at": datetime.now()},
            field_metadata={},
            field_display_names={},
            display_instruction="Inspect orders",
            title="Orders",
            subtitle="",
        )

    assert ArtifactLedger.for_workspace(workspace).list_nodes() == (parent,)


def test_visualize_rejects_unverified_code_signature(tmp_path) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    parent = _seed_load_artifact(workspace)
    _write_derived_table(workspace)

    with pytest.raises(ValueError, match="code_signature"):
        record_visualize_artifacts(
            workspace,
            chart_id="chart-abc",
            input_table_names=("orders",),
            output_table_name="derived",
            code="result_df = orders.copy()",
            code_signature="tampered",
            output_variable="result_df",
            chart_spec={"chart_type": "Table", "encodings": {}},
            field_metadata={},
            field_display_names={},
            display_instruction="Inspect orders",
            title="Orders",
            subtitle="",
        )

    assert ArtifactLedger.for_workspace(workspace).list_nodes() == (parent,)


@pytest.mark.parametrize(
    "input_table_names",
    [(), ("orders", "orders"), ("",)],
)
def test_visualize_rejects_invalid_declared_inputs(
    tmp_path,
    input_table_names: tuple[str, ...],
) -> None:
    workspace = Workspace("user:alice", root_dir=tmp_path, workspace_id="ws-1")
    _seed_load_artifact(workspace)
    _write_derived_table(workspace)
    code = "result_df = orders.copy()"

    with pytest.raises(ValueError, match="input table"):
        record_visualize_artifacts(
            workspace,
            chart_id="chart-abc",
            input_table_names=input_table_names,
            output_table_name="derived",
            code=code,
            code_signature=sign_code(code),
            output_variable="result_df",
            chart_spec={"chart_type": "Table", "encodings": {}},
            field_metadata={},
            field_display_names={},
            display_instruction="Inspect orders",
            title="Orders",
            subtitle="",
        )
