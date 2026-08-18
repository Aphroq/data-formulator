from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import Mock, patch

import pandas as pd
import pyarrow as pa
import pytest

from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.executor import RecipeExecutor
from data_formulator.recipes.run_store import (
    RecipeRunArtifactStore,
    RecipeRunCorruptError,
    RecipeRunKind,
    RecipeRunStatus,
)
from data_formulator.recipes.spec import (
    BindingTarget,
    InputMode,
    ParameterBinding,
    ParameterType,
    RecipeInput,
    RecipeParameter,
    RecipeStep,
    RecipeStepKind,
)
from data_formulator.sandbox import LocalSandbox


pytestmark = [pytest.mark.backend]


class _RunLoader:
    def __init__(self, *, drift: bool = False):
        self.drift = drift

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        if self.drift:
            return pa.table({
                "region": ["west", "east"],
                "amount": ["30", "40"],
            })
        return pa.table({
            "region": ["west", "east"],
            "amount": [30, 40],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


class _FailingLoader(_RunLoader):
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        raise RuntimeError("password=do-not-persist connector failure")


def test_dry_run_executes_three_steps_without_llm_and_isolates_outputs(
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    source_orders = recipe_workspace.get_parquet_path("orders").read_bytes()
    resolver = Mock(return_value=_RunLoader())
    executor = RecipeExecutor(
        recipe_workspace,
        loader_resolver=resolver,
        sandbox=LocalSandbox(),
    )

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Recipe execution must not call an LLM"),
    ):
        result = executor.execute(
            executable_recipe.spec,
            parameter_values={},
            kind=RecipeRunKind.DRY_RUN,
        )

    assert result.status is RecipeRunStatus.SUCCEEDED
    assert [item.kind for item in result.step_results] == [
        RecipeStepKind.LOAD,
        RecipeStepKind.TRANSFORM,
        RecipeStepKind.CHART,
    ]
    assert resolver.call_args_list[0].args == ("warehouse",)
    assert recipe_workspace.get_parquet_path("orders").read_bytes() == source_orders

    stored = RecipeRunArtifactStore.for_workspace(recipe_workspace).load(
        result.reference
    )
    assert stored.reference == result.reference
    assert [event["status"] for event in stored.events] == [
        "started",
        "succeeded",
        "started",
        "succeeded",
        "started",
        "succeeded",
    ]
    run_dir = recipe_workspace.confined_root.resolve(
        result.reference.artifact_path
    )
    output = pd.read_parquet(
        run_dir / "workspace" / "data" / "regional_totals.parquet"
    )
    assert output.to_dict("records") == [
        {"region": "east", "total": 40},
        {"region": "west", "total": 30},
    ]
    chart = json.loads(
        (run_dir / "outputs" / f"{result.step_results[-1].step_id}.chart.json")
        .read_text(encoding="utf-8")
    )
    assert chart["title"] == "Regional totals"
    assert "scratch" not in result.reference.artifact_path


def test_schema_drift_stops_run_and_requires_review(
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    executor = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _RunLoader(drift=True),
    )

    result = executor.execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )

    assert result.status is RecipeRunStatus.NEEDS_REVIEW
    assert result.error.code == "schema_drift"
    assert len(result.step_results) == 1
    stored = RecipeRunArtifactStore.for_workspace(recipe_workspace).load(
        result.reference
    )
    assert stored.manifest["error"] == {
        "code": "schema_drift",
        "exception_type": "RecipeSchemaDriftError",
        "message": "A Recipe step produced an incompatible schema.",
    }


def test_executor_rejects_invalid_transform_signature(
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    transform = next(
        step
        for step in executable_recipe.spec.steps
        if step.kind is RecipeStepKind.TRANSFORM
    )
    execution = transform.to_dict()["execution"]
    execution["code_signature"] = "invalid"
    changed_transform = RecipeStep(
        id=transform.id,
        kind=transform.kind,
        artifact_id=transform.artifact_id,
        dependencies=transform.dependencies,
        execution=execution,
        content_hash=transform.content_hash,
        expected_schema=transform.expected_schema,
    )
    changed_spec = replace(
        executable_recipe.spec,
        steps=tuple(
            changed_transform if step.id == transform.id else step
            for step in executable_recipe.spec.steps
        ),
    )
    executor = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _RunLoader(),
    )

    result = executor.execute(
        changed_spec,
        parameter_values={},
        kind=RecipeRunKind.MANUAL,
    )

    assert result.status is RecipeRunStatus.FAILED
    assert result.error.code == "invalid_code_signature"
    assert [item.kind for item in result.step_results] == [RecipeStepKind.LOAD]


def test_unresolved_input_fails_before_connector_open(
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    original = executable_recipe.spec.inputs[0]
    unresolved = RecipeInput(
        id=original.id,
        step_id=original.step_id,
        mode=InputMode.UNRESOLVED,
        source_id=None,
        credential_ref=None,
        content_hash=original.content_hash,
        expected_schema=original.expected_schema,
    )
    spec = replace(executable_recipe.spec, inputs=(unresolved,))
    resolver = Mock(side_effect=AssertionError("connector must not be opened"))
    executor = RecipeExecutor(recipe_workspace, loader_resolver=resolver)

    result = executor.execute(
        spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )

    assert result.status is RecipeRunStatus.FAILED
    assert result.error.code == "unresolved_input"
    resolver.assert_not_called()


def test_run_store_detects_output_tampering(
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    result = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _RunLoader(),
    ).execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )
    run_dir = recipe_workspace.confined_root.resolve(
        result.reference.artifact_path
    )
    chart_path = (
        run_dir
        / "outputs"
        / f"{result.step_results[-1].step_id}.chart.json"
    )
    chart_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RecipeRunCorruptError, match="hash"):
        RecipeRunArtifactStore.for_workspace(recipe_workspace).load(
            result.reference
        )


def test_run_artifacts_do_not_persist_bound_values_or_connector_errors(
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    caplog,
) -> None:
    load = executable_recipe.spec.steps[0]
    execution = load.to_dict()["execution"]
    execution["step"]["query"] = {
        "filters": [{
            "column": "region",
            "op": "eq",
            "value": "compile-time-value",
        }]
    }
    changed_load = RecipeStep(
        id=load.id,
        kind=load.kind,
        artifact_id=load.artifact_id,
        dependencies=load.dependencies,
        execution=execution,
        content_hash=load.content_hash,
        expected_schema=load.expected_schema,
    )
    parameterized = replace(
        executable_recipe.spec,
        steps=(changed_load, *executable_recipe.spec.steps[1:]),
        parameters=(RecipeParameter(
            id="region_filter",
            name="Region",
            value_type=ParameterType.STRING,
        ),),
        bindings=(ParameterBinding(
            parameter_id="region_filter",
            step_id=load.id,
            target=BindingTarget.LOAD_FILTER_VALUE,
            filter_index=0,
        ),),
    )

    succeeded = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _RunLoader(),
    ).execute(
        parameterized,
        parameter_values={"region_filter": "bound-value-do-not-persist"},
        kind=RecipeRunKind.DRY_RUN,
    )
    failed = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _FailingLoader(),
    ).execute(
        parameterized,
        parameter_values={"region_filter": "bound-value-do-not-persist"},
        kind=RecipeRunKind.DRY_RUN,
    )

    assert succeeded.status is RecipeRunStatus.SUCCEEDED
    assert failed.status is RecipeRunStatus.FAILED
    assert failed.error.code == "connector_error"
    for reference in (succeeded.reference, failed.reference):
        run_dir = recipe_workspace.confined_root.resolve(reference.artifact_path)
        persisted = b"\n".join(
            path.read_bytes()
            for path in run_dir.rglob("*")
            if path.is_file()
        )
        assert b"bound-value-do-not-persist" not in persisted
        assert b"password=do-not-persist" not in persisted
    assert "password=do-not-persist" not in caplog.text
