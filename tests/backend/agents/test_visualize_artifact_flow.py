from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pytest

from data_formulator.analyst.agent import AnalystAgent
from data_formulator.data_operations import (
    ConnectorQueryStep,
    DataOperation,
    DataOperationExecutor,
    DataOperationPlan,
    DataOperationStatus,
)
from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.compiler import RecipeCompiler
from data_formulator.recipes.lineage import ArtifactLedger
from data_formulator.recipes.models import ArtifactType
from data_formulator.recipes.spec import RecipeStepKind
from data_formulator.security.code_signing import sign_result


pytestmark = [pytest.mark.backend]


class _Loader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({"region": ["west", "east"], "amount": [10, 20]})

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


class _Sandbox:
    def run_python_code(self, *, code, workspace, output_variable):
        return {
            "status": "ok",
            "content": pd.DataFrame({
                "region": ["west", "east"],
                "total": [10, 20],
            }),
        }


def _load_orders(workspace: Workspace) -> None:
    plan = DataOperationPlan(
        id="plan-1",
        label="Orders",
        summary="",
        steps=(ConnectorQueryStep(
            source_id="warehouse",
            table_key="public.orders",
            display_name="Orders",
            source_table="public.orders",
        ),),
    )
    operation = DataOperation(
        id="operation-1",
        reason="Load orders",
        plans=(plan,),
        status=DataOperationStatus.RUNNING,
        selected_plan_id=plan.id,
    )
    result = DataOperationExecutor(workspace, lambda _source_id: _Loader()).execute(
        operation
    )
    assert result.result_table_ids == ("orders",)


def test_load_transform_chart_vertical_lineage(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path / "home"))
    workspace = Workspace(
        "user:alice",
        root_dir=tmp_path / "workspaces",
        workspace_id="ws-1",
    )
    _load_orders(workspace)
    agent = AnalystAgent(client=None, workspace=workspace)
    chart_spec = {
        "chart_type": "Bar Chart",
        "encodings": {"x": "region", "y": "total"},
    }
    code = "result_df = orders.groupby('region', as_index=False).sum()"

    with patch("data_formulator.sandbox.create_sandbox", return_value=_Sandbox()):
        visualize = agent.run_visualize_code(
            code=code,
            output_variable="result_df",
            input_tables=["orders"],
            chart_spec=chart_spec,
            field_metadata={},
            field_display_names={},
            display_instruction="Compare totals by region",
            title="Regional totals",
            subtitle="",
            messages=[],
        )

    assert visualize["status"] == "ok"
    transform_result = sign_result(visualize["transform_result"])
    lineage = agent.record_visualize_artifacts(
        transform_result=transform_result,
        input_tables=["orders"],
        chart_spec=chart_spec,
        field_metadata={},
        field_display_names={},
        display_instruction="Compare totals by region",
        title="Regional totals",
        subtitle="",
        output_variable="result_df",
    )

    assert lineage["status"] == "ok"
    nodes = ArtifactLedger.for_workspace(workspace).list_nodes()
    assert [node.artifact_type for node in nodes] == [
        ArtifactType.LOAD,
        ArtifactType.TRANSFORM,
        ArtifactType.CHART,
    ]
    assert nodes[1].parent_ids == (nodes[0].artifact_id,)
    assert nodes[2].parent_ids == (nodes[1].artifact_id,)
    output_table = transform_result["content"]["virtual"]["table_name"]
    metadata = workspace.get_table_metadata(output_table)
    assert metadata.import_options["visualize"]["input_tables"] == ["orders"]
    assert metadata.import_options["artifact_id"] == nodes[1].artifact_id

    compiler = RecipeCompiler.for_workspace(workspace)
    first = compiler.compile(
        target_artifact_ids=(nodes[2].artifact_id,),
        name="Regional totals",
    )
    second = compiler.compile(
        target_artifact_ids=(nodes[2].artifact_id,),
        name="Regional totals",
    )
    assert [step.kind for step in first.spec.steps] == [
        RecipeStepKind.LOAD,
        RecipeStepKind.TRANSFORM,
        RecipeStepKind.CHART,
    ]
    assert first.spec.canonical_bytes() == second.spec.canonical_bytes()
    assert first.workflow_markdown == second.workflow_markdown


def test_missing_parent_keeps_visualize_result_but_marks_lineage_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path / "home"))
    workspace = Workspace(
        "user:alice",
        root_dir=tmp_path / "workspaces",
        workspace_id="ws-1",
    )
    workspace.write_parquet(pd.DataFrame({"value": [1]}), "manual_input")
    agent = AnalystAgent(client=None, workspace=workspace)

    with patch("data_formulator.sandbox.create_sandbox", return_value=_Sandbox()):
        visualize = agent.run_visualize_code(
            code="result_df = manual_input.copy()",
            output_variable="result_df",
            input_tables=["manual_input"],
            chart_spec={"chart_type": "Table", "encodings": {}},
            field_metadata={},
            field_display_names={},
            display_instruction="Inspect values",
            title="Values",
            subtitle="",
            messages=[],
        )

    transform_result = sign_result(visualize["transform_result"])
    lineage = agent.record_visualize_artifacts(
        transform_result=transform_result,
        input_tables=["manual_input"],
        chart_spec={"chart_type": "Table", "encodings": {}},
        field_metadata={},
        field_display_names={},
        display_instruction="Inspect values",
        title="Values",
        subtitle="",
        output_variable="result_df",
    )

    assert visualize["status"] == "ok"
    assert lineage == {
        "status": "unavailable",
        "reason": "missing_parent_artifact",
    }
    output_table = transform_result["content"]["virtual"]["table_name"]
    assert workspace.get_table_metadata(output_table) is not None
    assert ArtifactLedger.for_workspace(workspace).list_nodes() == ()
