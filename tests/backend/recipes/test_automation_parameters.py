from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from data_formulator.automation.parameters import (
    normalize_manual_parameter_values,
    normalize_schedule_parameter_policy,
    resolve_schedule_parameter_policy,
)
from data_formulator.recipes.canonical import thaw_json
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.spec import (
    BindingTarget,
    ParameterBinding,
    ParameterType,
    RecipeParameter,
)


pytestmark = [pytest.mark.backend]


def _parameterized_recipe(executable_recipe: CompiledRecipe) -> CompiledRecipe:
    original_load_step = executable_recipe.spec.steps[0]
    execution = thaw_json(original_load_step.execution)
    execution["step"]["query"] = {
        "filters": [{"column": "as_of", "op": "LTE", "value": "2026-08-19"}],
        "limit": 100,
    }
    load_step = replace(original_load_step, execution=execution)
    steps = tuple(
        load_step if step.id == load_step.id else step
        for step in executable_recipe.spec.steps
    )
    spec = replace(
        executable_recipe.spec,
        steps=steps,
        parameters=(
            RecipeParameter(
                id="as_of",
                name="As of date",
                value_type=ParameterType.DATE,
            ),
            RecipeParameter(
                id="row_limit",
                name="Row limit",
                value_type=ParameterType.INTEGER,
                has_default=True,
                default_value=25,
            ),
        ),
        bindings=(
            ParameterBinding(
                parameter_id="as_of",
                step_id=load_step.id,
                target=BindingTarget.LOAD_FILTER_VALUE,
                filter_index=0,
            ),
            ParameterBinding(
                parameter_id="row_limit",
                step_id=load_step.id,
                target=BindingTarget.LOAD_LIMIT,
            ),
        ),
    )
    return CompiledRecipe(spec, executable_recipe.workflow_markdown)


def test_schedule_policy_resolves_the_planned_local_date_and_defaults(
    executable_recipe: CompiledRecipe,
) -> None:
    recipe = _parameterized_recipe(executable_recipe)

    policy = normalize_schedule_parameter_policy(
        recipe.spec,
        {
            "as_of": {
                "source": "scheduled_date",
                "offset_days": -1,
            },
        },
    )
    resolved = resolve_schedule_parameter_policy(
        policy,
        scheduled_for="2026-08-20T01:30:00.000000Z",
        timezone_name="America/Los_Angeles",
    )

    assert policy == {
        "as_of": {"source": "scheduled_date", "offset_days": -1},
        "row_limit": {"source": "literal", "value": 25},
    }
    assert resolved == {
        "as_of": "2026-08-18",
        "row_limit": 25,
    }


def test_schedule_policy_rejects_untyped_or_unsafe_dynamic_values(
    executable_recipe: CompiledRecipe,
) -> None:
    recipe = _parameterized_recipe(executable_recipe)

    with pytest.raises(ValueError, match="Unknown parameter"):
        normalize_schedule_parameter_policy(
            recipe.spec,
            {"not_a_slot": {"source": "literal", "value": "x"}},
        )
    with pytest.raises(TypeError, match="row_limit"):
        normalize_schedule_parameter_policy(
            recipe.spec,
            {
                "as_of": {"source": "literal", "value": "2026-08-20"},
                "row_limit": {
                    "source": "scheduled_date",
                    "offset_days": 0,
                },
            },
        )
    with pytest.raises(ValueError, match="offset_days"):
        normalize_schedule_parameter_policy(
            recipe.spec,
            {
                "as_of": {
                    "source": "scheduled_date",
                    "offset_days": 100_000,
                },
            },
        )


def test_manual_parameter_values_are_resolved_and_typed_before_enqueue(
    executable_recipe: CompiledRecipe,
) -> None:
    recipe = _parameterized_recipe(executable_recipe)

    assert normalize_manual_parameter_values(
        recipe.spec,
        {"as_of": "2026-08-20", "row_limit": 10},
    ) == {"as_of": "2026-08-20", "row_limit": 10}

    with pytest.raises(TypeError, match="row_limit"):
        normalize_manual_parameter_values(
            recipe.spec,
            {"as_of": "2026-08-20", "row_limit": "10; import os"},
        )


def test_scheduled_datetime_policy_preserves_the_schedule_timezone(
    executable_recipe: CompiledRecipe,
) -> None:
    parameterized = _parameterized_recipe(executable_recipe)
    load_step = parameterized.spec.steps[0]
    spec = replace(
        parameterized.spec,
        parameters=(RecipeParameter(
            id="window_end",
            name="Window end",
            value_type=ParameterType.DATETIME,
        ),),
        bindings=(ParameterBinding(
            parameter_id="window_end",
            step_id=load_step.id,
            target=BindingTarget.LOAD_FILTER_VALUE,
            filter_index=0,
        ),),
    )

    policy = normalize_schedule_parameter_policy(
        spec,
        {"window_end": {"source": "scheduled_datetime", "offset_days": 0}},
    )

    assert resolve_schedule_parameter_policy(
        policy,
        scheduled_for=datetime(2026, 8, 20, 1, 30, tzinfo=timezone.utc),
        timezone_name="Asia/Shanghai",
    ) == {"window_end": "2026-08-20T09:30:00+08:00"}
