from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_formulator.data_operations import (
    ConnectorQueryStep,
    DataOperation,
    DataOperationExecutor,
    DataOperationPlan,
    DataOperationStatus,
    LoadQuery,
    OperationFilter,
)
from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.binding import bind_recipe_parameters
from data_formulator.recipes.compiler import RecipeCompileError, RecipeCompiler
from data_formulator.recipes.lineage import ArtifactLedger, ArtifactLineageError
from data_formulator.recipes.models import ArtifactNode, ArtifactType
from data_formulator.recipes.spec import (
    BindingTarget,
    InputMode,
    ParameterBinding,
    ParameterType,
    RecipeParameter,
    RecipeSpec,
    RecipeStepKind,
)
from data_formulator.recipes.visualize import record_visualize_artifacts
from data_formulator.security.code_signing import sign_code


pytestmark = [pytest.mark.backend]


class _Loader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": [10, 20],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


@dataclass(frozen=True)
class _Graph:
    workspace: Workspace
    ledger: ArtifactLedger
    target_artifact_id: str


@pytest.fixture
def graph(tmp_path) -> _Graph:
    workspace = Workspace(
        "user:alice",
        root_dir=tmp_path / "workspaces",
        workspace_id="ws-1",
    )
    step = ConnectorQueryStep(
        source_id="warehouse",
        table_key="public.orders",
        display_name="Orders",
        source_table="public.orders",
        query=LoadQuery(
            filters=(OperationFilter("region", "EQ", "west"),),
            limit=100,
        ),
    )
    plan = DataOperationPlan(
        id="plan-1",
        label="Orders",
        summary="",
        steps=(step,),
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

    workspace.write_parquet(
        pd.DataFrame({"region": ["west", "east"], "total": [10, 20]}),
        "regional_totals",
    )
    code = "result_df = orders.groupby('region', as_index=False).sum()"
    artifacts = record_visualize_artifacts(
        workspace,
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
        field_metadata={"total": {"semantic_type": "number"}},
        field_display_names={"total": "Total"},
        display_instruction="Compare totals by region",
        title="Regional totals",
        subtitle="Current selection",
    )
    return _Graph(
        workspace,
        ArtifactLedger.for_workspace(workspace),
        artifacts.chart.artifact_id,
    )


def test_compiler_walks_ancestors_and_builds_stable_recipe(graph: _Graph) -> None:
    compiler = RecipeCompiler.for_workspace(graph.workspace)

    first = compiler.compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
        description="Refresh orders and rebuild the regional chart.",
    )
    second = compiler.compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
        description="Refresh orders and rebuild the regional chart.",
    )

    assert first.spec.canonical_bytes() == second.spec.canonical_bytes()
    assert first.spec.recipe_hash == second.spec.recipe_hash
    assert first.spec.version_id == second.spec.version_id
    assert first.workflow_markdown == second.workflow_markdown
    assert [step.kind for step in first.spec.steps] == [
        RecipeStepKind.LOAD,
        RecipeStepKind.TRANSFORM,
        RecipeStepKind.CHART,
    ]
    assert first.spec.steps[0].dependencies == ()
    assert first.spec.steps[1].dependencies == (first.spec.steps[0].id,)
    assert first.spec.steps[2].dependencies == (first.spec.steps[1].id,)
    assert first.spec.target_artifact_ids == (graph.target_artifact_id,)
    assert first.spec.inputs[0].mode is InputMode.REFRESHABLE
    assert first.spec.inputs[0].source_id == "warehouse"
    assert first.spec.inputs[0].credential_ref.reference_id == "warehouse"
    assert first.spec.has_unresolved_inputs is False
    assert "## Steps" in first.workflow_markdown
    assert "Regional totals" in first.workflow_markdown


def test_compiler_is_independent_of_ledger_serialization_order(graph: _Graph) -> None:
    before = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
    )
    payload = json.loads(graph.ledger.storage_path.read_text(encoding="utf-8"))
    payload["artifacts"].reverse()
    graph.ledger.storage_path.write_text(json.dumps(payload), encoding="utf-8")

    after = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
    )

    assert after.spec.canonical_bytes() == before.spec.canonical_bytes()
    assert after.workflow_markdown == before.workflow_markdown


def test_recipe_spec_round_trip_reverifies_step_and_recipe_hashes(graph: _Graph) -> None:
    compiled = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
    )

    restored = RecipeSpec.from_dict(compiled.spec.to_dict())

    assert restored == compiled.spec
    tampered = compiled.spec.to_dict()
    tampered["steps"][-1]["execution"]["title"] = "Tampered title"
    with pytest.raises(ValueError, match="step_hash"):
        RecipeSpec.from_dict(tampered)


def test_recipe_spec_rejects_coerced_booleans_and_missing_load_input(
    graph: _Graph,
) -> None:
    base = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
    )
    load_step = next(
        step for step in base.spec.steps if step.kind is RecipeStepKind.LOAD
    )
    compiled = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
        parameters=(RecipeParameter(
            id="region",
            name="Region",
            value_type=ParameterType.STRING,
        ),),
        bindings=(ParameterBinding(
            parameter_id="region",
            step_id=load_step.id,
            target=BindingTarget.LOAD_FILTER_VALUE,
            filter_index=0,
        ),),
    )

    serialized = compiled.spec.to_dict()
    serialized["parameters"][0]["required"] = "false"
    with pytest.raises(TypeError, match="required"):
        RecipeSpec.from_dict(serialized)

    with pytest.raises(ValueError, match="exactly one input"):
        replace(compiled.spec, inputs=())


def test_compiler_rejects_missing_target_and_changed_materialization(
    graph: _Graph,
) -> None:
    compiler = RecipeCompiler.for_workspace(graph.workspace)
    with pytest.raises(ArtifactLineageError, match="target"):
        compiler.compile(
            target_artifact_ids=("art_" + "9" * 64,),
            name="Missing",
        )

    metadata = graph.workspace.get_table_metadata("regional_totals")
    pq.write_table(
        pa.table({"region": ["west"], "total": [999]}),
        graph.workspace.get_file_path(metadata.filename),
    )
    with pytest.raises(RecipeCompileError, match="content hash"):
        compiler.compile(
            target_artifact_ids=(graph.target_artifact_id,),
            name="Regional totals",
        )


@pytest.mark.parametrize(
    ("signature", "declared_table", "message"),
    [
        ("sha256:invalid", "orders", "signature"),
        (None, "not_orders", "declared input table"),
    ],
)
def test_compiler_rejects_untrusted_transform_execution(
    graph: _Graph,
    signature: str | None,
    declared_table: str,
    message: str,
) -> None:
    load = next(
        node
        for node in graph.ledger.list_nodes()
        if node.artifact_type is ArtifactType.LOAD
    )
    existing = next(
        node
        for node in graph.ledger.list_nodes()
        if node.artifact_type is ArtifactType.TRANSFORM
    )
    execution = existing.to_dict()["execution"]
    if signature is not None:
        execution["code_signature"] = signature
    execution["input_tables"][0]["table_id"] = declared_table
    untrusted = ArtifactNode(
        artifact_type=ArtifactType.TRANSFORM,
        identity_id=existing.identity_id,
        workspace_id=existing.workspace_id,
        origin_id=f"test/untrusted/{message}",
        parent_ids=(load.artifact_id,),
        content_hash=existing.content_hash,
        schema_fingerprint=existing.schema_fingerprint,
        execution=execution,
        created_at=existing.created_at,
    )
    graph.ledger.record(untrusted)

    with pytest.raises(RecipeCompileError, match=message):
        RecipeCompiler.for_workspace(graph.workspace).compile(
            target_artifact_ids=(untrusted.artifact_id,),
            name="Untrusted transform",
        )


def test_typed_binding_updates_structural_slots_without_template_substitution(
    graph: _Graph,
) -> None:
    base = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
    )
    load_step = next(
        step for step in base.spec.steps if step.kind is RecipeStepKind.LOAD
    )
    parameters = (
        RecipeParameter(
            id="region",
            name="Region",
            value_type=ParameterType.STRING,
        ),
        RecipeParameter(
            id="row_limit",
            name="Row limit",
            value_type=ParameterType.INTEGER,
        ),
    )
    bindings = (
        ParameterBinding(
            parameter_id="region",
            step_id=load_step.id,
            target=BindingTarget.LOAD_FILTER_VALUE,
            filter_index=0,
        ),
        ParameterBinding(
            parameter_id="row_limit",
            step_id=load_step.id,
            target=BindingTarget.LOAD_LIMIT,
        ),
    )
    compiled = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
        parameters=parameters,
        bindings=bindings,
    )
    suspicious_text = "west'; DROP TABLE orders; --"

    bound = bind_recipe_parameters(
        compiled.spec,
        {"region": suspicious_text, "row_limit": 25},
    )

    bound_load = next(
        step for step in bound.steps if step.kind is RecipeStepKind.LOAD
    ).to_dict()
    query = bound_load["execution"]["step"]["query"]
    assert query["filters"][0]["value"] == suspicious_text
    assert query["limit"] == 25
    assert suspicious_text not in bound_load["execution"].get("code", "")
    assert (
        compiled.spec.steps[0].to_dict()["execution"]["step"]["query"][
            "filters"
        ][0]["value"]
        == "west"
    )

    with pytest.raises(TypeError, match="row_limit"):
        bind_recipe_parameters(
            compiled.spec,
            {"region": "west", "row_limit": "25; import os"},
        )
    with pytest.raises(ValueError, match="Unknown parameter"):
        bind_recipe_parameters(
            compiled.spec,
            {"region": "west", "row_limit": 25, "extra": True},
        )


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (ParameterType.INTEGER, 2**53),
        (ParameterType.NUMBER, 2**53),
        (ParameterType.NUMBER, 2**10000),
        (ParameterType.NUMBER, float("inf")),
    ],
)
def test_recipe_parameter_rejects_unsafe_numeric_values(
    value_type: ParameterType,
    value,
) -> None:
    parameter = RecipeParameter(
        id="numeric_value",
        name="Numeric value",
        value_type=value_type,
    )

    with pytest.raises(TypeError, match="numeric_value"):
        parameter.validate_value(value)


def test_recipe_parameter_accepts_safe_integer_boundary() -> None:
    value = 2**53 - 1
    RecipeParameter(
        id="integer_value",
        name="Integer value",
        value_type=ParameterType.INTEGER,
    ).validate_value(value)
    RecipeParameter(
        id="number_value",
        name="Number value",
        value_type=ParameterType.NUMBER,
    ).validate_value(value)


def test_compiler_rejects_binding_to_missing_filter_slot(graph: _Graph) -> None:
    base = RecipeCompiler.for_workspace(graph.workspace).compile(
        target_artifact_ids=(graph.target_artifact_id,),
        name="Regional totals",
    )
    load_step = next(
        step for step in base.spec.steps if step.kind is RecipeStepKind.LOAD
    )

    with pytest.raises(ValueError, match="filter_index"):
        RecipeCompiler.for_workspace(graph.workspace).compile(
            target_artifact_ids=(graph.target_artifact_id,),
            name="Regional totals",
            parameters=(RecipeParameter(
                id="region",
                name="Region",
                value_type=ParameterType.STRING,
            ),),
            bindings=(ParameterBinding(
                parameter_id="region",
                step_id=load_step.id,
                target=BindingTarget.LOAD_FILTER_VALUE,
                filter_index=99,
            ),),
        )
