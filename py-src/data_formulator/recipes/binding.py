# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed, structural Recipe parameter binding."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from data_formulator.recipes.canonical import (
    FrozenJsonValue,
    canonical_json_bytes,
    freeze_json,
    thaw_json,
)
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.spec import (
    BindingTarget,
    RecipeSpec,
    RecipeStepKind,
)


@dataclass(frozen=True, slots=True)
class BoundRecipeStep:
    id: str
    kind: RecipeStepKind
    execution: Mapping[str, FrozenJsonValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", RecipeStepKind(self.kind))
        frozen = freeze_json(self.execution)
        if not isinstance(frozen, Mapping):
            raise TypeError("Bound step execution must be an object")
        object.__setattr__(self, "execution", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "execution": thaw_json(self.execution),
        }


@dataclass(frozen=True, slots=True)
class BoundRecipe:
    version_id: str
    parameter_values: Mapping[str, FrozenJsonValue]
    steps: tuple[BoundRecipeStep, ...]
    binding_hash: HashDigest = field(init=False)

    def __post_init__(self) -> None:
        frozen_values = freeze_json(self.parameter_values)
        if not isinstance(frozen_values, Mapping):
            raise TypeError("parameter_values must be an object")
        object.__setattr__(self, "parameter_values", frozen_values)
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(
            self,
            "binding_hash",
            HashDigest.sha256(canonical_json_bytes(self.identity_payload())),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "parameter_values": thaw_json(self.parameter_values),
            "steps": [step.to_dict() for step in self.steps],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "binding_hash": str(self.binding_hash),
        }


def _resolve_parameter_values(
    spec: RecipeSpec,
    provided: Mapping[str, Any],
) -> dict[str, Any]:
    parameters = {item.id: item for item in spec.parameters}
    unknown = sorted(set(provided) - set(parameters))
    if unknown:
        raise ValueError(f"Unknown parameter value(s): {unknown}")

    resolved: dict[str, Any] = {}
    for parameter_id, parameter in parameters.items():
        if parameter_id in provided:
            value = provided[parameter_id]
        elif parameter.has_default:
            value = thaw_json(parameter.default_value)
        elif parameter.required:
            raise ValueError(f"Missing required parameter: {parameter_id}")
        else:
            continue
        parameter.validate_value(value)
        resolved[parameter_id] = value
    return resolved


def bind_recipe_parameters(
    spec: RecipeSpec,
    values: Mapping[str, Any],
) -> BoundRecipe:
    """Apply validated values to predefined structural slots only."""
    if not isinstance(values, Mapping):
        raise TypeError("Recipe parameter values must be an object")
    resolved = _resolve_parameter_values(spec, values)
    executions = {
        step.id: thaw_json(step.execution)
        for step in spec.steps
    }

    for binding in spec.bindings:
        if binding.parameter_id not in resolved:
            continue
        execution = executions[binding.step_id]
        connector_step = execution["step"]
        query = connector_step.setdefault("query", {})
        value = resolved[binding.parameter_id]
        if binding.target is BindingTarget.LOAD_FILTER_VALUE:
            filter_index = binding.filter_index
            if filter_index is None:  # pragma: no cover - RecipeSpec validates this
                raise ValueError("load_filter_value binding requires filter_index")
            query["filters"][filter_index]["value"] = value
        elif binding.target is BindingTarget.LOAD_LIMIT:
            if value < 1:
                raise ValueError("load_limit parameter must be positive")
            query["limit"] = value
        else:  # pragma: no cover - enum construction prevents this
            raise ValueError(f"Unsupported binding target: {binding.target}")

    steps = tuple(
        BoundRecipeStep(step.id, step.kind, executions[step.id])
        for step in spec.steps
    )
    return BoundRecipe(
        version_id=spec.version_id,
        parameter_values=resolved,
        steps=steps,
    )
