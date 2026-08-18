from __future__ import annotations

import pytest
import pandas as pd
import pyarrow as pa

from data_formulator.data_operations import (
    ConnectorQueryStep,
    DataOperation,
    DataOperationExecutor,
    DataOperationPlan,
    DataOperationStatus,
)
from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.compiler import CompiledRecipe, RecipeCompiler
from data_formulator.recipes.lineage import ArtifactLedger
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.spec import (
    CredentialReference,
    InputMode,
    RecipeInput,
    RecipeOutput,
    RecipeSpec,
    RecipeStep,
    RecipeStepKind,
)
from data_formulator.recipes.visualize import record_visualize_artifacts
from data_formulator.security.code_signing import sign_code


@pytest.fixture
def recipe_workspace(tmp_path) -> Workspace:
    return Workspace(
        "user:alice",
        root_dir=tmp_path / "workspaces",
        workspace_id="ws-1",
    )


@pytest.fixture
def compiled_recipe(recipe_workspace: Workspace) -> CompiledRecipe:
    artifact_id = "art_" + "1" * 64
    step_id = "step_" + "1" * 64
    content_hash = HashDigest.sha256(b"orders")
    schema_hash = HashDigest.sha256(b"orders-schema")
    step = RecipeStep(
        id=step_id,
        kind=RecipeStepKind.LOAD,
        artifact_id=artifact_id,
        dependencies=(),
        execution={
            "kind": "connector_query",
            "step": {
                "kind": "connector_query",
                "source_id": "warehouse",
                "table_key": "public.orders",
                "display_name": "Orders",
                "source_table": "public.orders",
            },
            "output": {
                "table_id": "orders",
                "filename": "orders.parquet",
            },
        },
        content_hash=content_hash,
        expected_schema=schema_hash,
    )
    spec = RecipeSpec(
        recipe_id="rcp_" + "2" * 64,
        name="Orders",
        description="Refresh the orders table.",
        created_by=recipe_workspace.identity_id,
        identity_id=recipe_workspace.identity_id,
        workspace_id=recipe_workspace.workspace_id,
        target_artifact_ids=(artifact_id,),
        steps=(step,),
        parameters=(),
        bindings=(),
        inputs=(RecipeInput(
            id="input_" + "1" * 64,
            step_id=step_id,
            mode=InputMode.REFRESHABLE,
            source_id="warehouse",
            credential_ref=CredentialReference("connector", "warehouse"),
            content_hash=content_hash,
            expected_schema=schema_hash,
        ),),
        final_outputs=(RecipeOutput(
            artifact_id=artifact_id,
            step_id=step_id,
            kind=RecipeStepKind.LOAD,
        ),),
        compiler_version="test-compiler/1",
    )
    return CompiledRecipe(spec=spec, workflow_markdown="# Orders\n")


class _BaselineLoader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": [10, 20],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


@pytest.fixture
def executable_recipe(recipe_workspace: Workspace) -> CompiledRecipe:
    connector_step = ConnectorQueryStep(
        source_id="warehouse",
        table_key="public.orders",
        display_name="Orders",
        source_table="public.orders",
    )
    plan = DataOperationPlan(
        id="plan-1",
        label="Orders",
        summary="",
        steps=(connector_step,),
    )
    operation = DataOperation(
        id="operation-1",
        reason="Load orders",
        plans=(plan,),
        status=DataOperationStatus.RUNNING,
        selected_plan_id=plan.id,
    )
    result = DataOperationExecutor(
        recipe_workspace,
        lambda _source_id: _BaselineLoader(),
    ).execute(operation)
    assert result.result_table_ids == ("orders",)

    recipe_workspace.write_parquet(
        pd.DataFrame({
            "region": ["east", "west"],
            "total": [20, 10],
        }),
        "regional_totals",
    )
    code = "\n".join([
        "import pandas as pd",
        'orders = pd.read_parquet("data/orders.parquet")',
        "result_df = (",
        "    orders.groupby('region', as_index=False)['amount']",
        "    .sum()",
        "    .rename(columns={'amount': 'total'})",
        "    .sort_values('region')",
        "    .reset_index(drop=True)",
        ")",
    ])
    artifacts = record_visualize_artifacts(
        recipe_workspace,
        chart_id="chart-regions",
        input_table_names=("orders",),
        output_table_name="regional_totals",
        code=code,
        code_signature=sign_code(code),
        output_variable="result_df",
        chart_spec={
            "chart_type": "Bar Chart",
            "encodings": {"x": "region", "y": "total"},
        },
        field_metadata={},
        field_display_names={},
        display_instruction="Compare totals by region",
        title="Regional totals",
        subtitle="",
    )
    assert ArtifactLedger.for_workspace(recipe_workspace).get(
        artifacts.chart.artifact_id
    ) is not None
    return RecipeCompiler.for_workspace(recipe_workspace).compile(
        target_artifact_ids=(artifacts.chart.artifact_id,),
        name="Regional totals",
    )
