# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Immutable RecipeSpec v1 wire models."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar

from data_formulator.recipes.canonical import (
    FrozenJsonValue,
    canonical_json_bytes,
    freeze_json,
    thaw_json,
)
from data_formulator.recipes.models import ArtifactType, HashDigest


_RECIPE_ID_PATTERN = re.compile(r"^rcp_[0-9a-f]{64}$")
_STEP_ID_PATTERN = re.compile(r"^step_[0-9a-f]{64}$")
_ARTIFACT_ID_PATTERN = re.compile(r"^art_[0-9a-f]{64}$")
_PARAMETER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _require_exact_fields(
    data: Mapping[str, Any],
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    fields = set(data)
    missing = required - fields
    unknown = fields - required - optional
    if missing or unknown:
        raise ValueError(
            f"Invalid fields; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a boolean")
    return value


class RecipeStepKind(StrEnum):
    LOAD = "load"
    TRANSFORM = "transform"
    CHART = "chart"

    @classmethod
    def from_artifact_type(cls, artifact_type: ArtifactType) -> "RecipeStepKind":
        try:
            return cls(artifact_type.value)
        except ValueError as exc:
            raise ValueError(
                f"Artifact type {artifact_type.value!r} is not executable in Recipe v1"
            ) from exc


class InputMode(StrEnum):
    REFRESHABLE = "refreshable"
    PINNED_SNAPSHOT = "pinned_snapshot"
    EXTERNAL_PATH = "external_path"
    UNRESOLVED = "unresolved"


class ParameterType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


class BindingTarget(StrEnum):
    LOAD_FILTER_VALUE = "load_filter_value"
    LOAD_LIMIT = "load_limit"


@dataclass(frozen=True, slots=True)
class CredentialReference:
    kind: str
    reference_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("Credential reference kind cannot be empty")
        if not isinstance(self.reference_id, str) or not self.reference_id.strip():
            raise ValueError("Credential reference id cannot be empty")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "reference_id": self.reference_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CredentialReference":
        _require_exact_fields(data, {"kind", "reference_id"})
        return cls(kind=data["kind"], reference_id=data["reference_id"])


@dataclass(frozen=True, slots=True)
class RecipeInput:
    id: str
    step_id: str
    mode: InputMode
    content_hash: HashDigest
    expected_schema: HashDigest
    source_id: str | None = None
    credential_ref: CredentialReference | None = None

    def __post_init__(self) -> None:
        if not self.id.startswith("input_") or len(self.id) <= len("input_"):
            raise ValueError("Recipe input id must start with 'input_'")
        if not _STEP_ID_PATTERN.fullmatch(self.step_id):
            raise ValueError("Recipe input step_id is invalid")
        object.__setattr__(self, "mode", InputMode(self.mode))
        if not isinstance(self.content_hash, HashDigest):
            raise TypeError("Recipe input content_hash must be a HashDigest")
        if not isinstance(self.expected_schema, HashDigest):
            raise TypeError("Recipe input expected_schema must be a HashDigest")
        if self.credential_ref is not None and not isinstance(
            self.credential_ref,
            CredentialReference,
        ):
            raise TypeError("Recipe input credential_ref must be a CredentialReference")
        if self.mode is InputMode.REFRESHABLE:
            if not isinstance(self.source_id, str) or not self.source_id.strip():
                raise ValueError("Refreshable input requires source_id")
            if self.credential_ref is None:
                raise ValueError("Refreshable input requires credential_ref")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "step_id": self.step_id,
            "mode": self.mode.value,
            "content_hash": str(self.content_hash),
            "expected_schema": str(self.expected_schema),
        }
        if self.source_id is not None:
            result["source_id"] = self.source_id
        if self.credential_ref is not None:
            result["credential_ref"] = self.credential_ref.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecipeInput":
        _require_exact_fields(
            data,
            {"id", "step_id", "mode", "content_hash", "expected_schema"},
            {"source_id", "credential_ref"},
        )
        credential = data.get("credential_ref")
        return cls(
            id=data["id"],
            step_id=data["step_id"],
            mode=InputMode(data["mode"]),
            content_hash=HashDigest.parse(data["content_hash"]),
            expected_schema=HashDigest.parse(data["expected_schema"]),
            source_id=data.get("source_id"),
            credential_ref=(
                CredentialReference.from_dict(credential)
                if credential is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RecipeParameter:
    id: str
    name: str
    value_type: ParameterType
    required: bool = True
    has_default: bool = False
    default_value: FrozenJsonValue = None

    def __post_init__(self) -> None:
        if not _PARAMETER_ID_PATTERN.fullmatch(self.id):
            raise ValueError(f"Invalid parameter id: {self.id!r}")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Parameter name cannot be empty")
        _require_bool(self.required, "required")
        _require_bool(self.has_default, "has_default")
        object.__setattr__(self, "value_type", ParameterType(self.value_type))
        if self.has_default:
            frozen = freeze_json(self.default_value)
            object.__setattr__(self, "default_value", frozen)
            self.validate_value(thaw_json(frozen))
        else:
            object.__setattr__(self, "default_value", None)

    def validate_value(self, value: Any) -> None:
        valid = False
        if self.value_type is ParameterType.STRING:
            valid = type(value) is str
        elif self.value_type is ParameterType.INTEGER:
            valid = type(value) is int
        elif self.value_type is ParameterType.NUMBER:
            valid = type(value) in (int, float) and math.isfinite(value)
        elif self.value_type is ParameterType.BOOLEAN:
            valid = type(value) is bool
        elif self.value_type is ParameterType.DATE:
            if type(value) is str:
                try:
                    date.fromisoformat(value)
                    valid = "T" not in value
                except ValueError:
                    pass
        elif self.value_type is ParameterType.DATETIME:
            if type(value) is str:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    valid = parsed.tzinfo is not None and parsed.utcoffset() is not None
                except ValueError:
                    pass
        if not valid:
            raise TypeError(
                f"Parameter {self.id!r} requires a {self.value_type.value} value"
            )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.value_type.value,
            "required": self.required,
        }
        if self.has_default:
            result["default"] = thaw_json(self.default_value)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecipeParameter":
        _require_exact_fields(data, {"id", "name", "type", "required"}, {"default"})
        return cls(
            id=data["id"],
            name=data["name"],
            value_type=ParameterType(data["type"]),
            required=_require_bool(data["required"], "required"),
            has_default="default" in data,
            default_value=data.get("default"),
        )


@dataclass(frozen=True, slots=True)
class ParameterBinding:
    parameter_id: str
    step_id: str
    target: BindingTarget
    filter_index: int | None = None

    def __post_init__(self) -> None:
        if not _PARAMETER_ID_PATTERN.fullmatch(self.parameter_id):
            raise ValueError("Binding parameter_id is invalid")
        if not _STEP_ID_PATTERN.fullmatch(self.step_id):
            raise ValueError("Binding step_id is invalid")
        object.__setattr__(self, "target", BindingTarget(self.target))
        if self.target is BindingTarget.LOAD_FILTER_VALUE:
            if type(self.filter_index) is not int or self.filter_index < 0:
                raise ValueError("load_filter_value binding requires filter_index")
        elif self.filter_index is not None:
            raise ValueError("filter_index is only valid for load_filter_value")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "parameter_id": self.parameter_id,
            "step_id": self.step_id,
            "target": self.target.value,
        }
        if self.filter_index is not None:
            result["filter_index"] = self.filter_index
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParameterBinding":
        _require_exact_fields(
            data,
            {"parameter_id", "step_id", "target"},
            {"filter_index"},
        )
        return cls(
            parameter_id=data["parameter_id"],
            step_id=data["step_id"],
            target=BindingTarget(data["target"]),
            filter_index=data.get("filter_index"),
        )


@dataclass(frozen=True, slots=True)
class RecipeStep:
    id: str
    kind: RecipeStepKind
    artifact_id: str
    dependencies: tuple[str, ...]
    execution: Mapping[str, FrozenJsonValue]
    content_hash: HashDigest
    expected_schema: HashDigest
    step_hash: HashDigest = field(init=False)

    def __post_init__(self) -> None:
        if not _STEP_ID_PATTERN.fullmatch(self.id):
            raise ValueError("Recipe step id is invalid")
        object.__setattr__(self, "kind", RecipeStepKind(self.kind))
        if not _ARTIFACT_ID_PATTERN.fullmatch(self.artifact_id):
            raise ValueError("Recipe step artifact_id is invalid")
        dependencies = tuple(self.dependencies)
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("Recipe step dependencies must be unique")
        if any(not _STEP_ID_PATTERN.fullmatch(item) for item in dependencies):
            raise ValueError("Recipe step dependency id is invalid")
        object.__setattr__(self, "dependencies", dependencies)
        frozen_execution = freeze_json(self.execution)
        if not isinstance(frozen_execution, Mapping) or not frozen_execution:
            raise ValueError("Recipe step execution must be a non-empty object")
        object.__setattr__(self, "execution", frozen_execution)
        if not isinstance(self.content_hash, HashDigest):
            raise TypeError("Recipe step content_hash must be a HashDigest")
        if not isinstance(self.expected_schema, HashDigest):
            raise TypeError("Recipe step expected_schema must be a HashDigest")
        object.__setattr__(
            self,
            "step_hash",
            HashDigest.sha256(canonical_json_bytes(self.identity_payload())),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "artifact_id": self.artifact_id,
            "dependencies": list(self.dependencies),
            "execution": thaw_json(self.execution),
            "content_hash": str(self.content_hash),
            "expected_schema": str(self.expected_schema),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "step_hash": str(self.step_hash)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecipeStep":
        _require_exact_fields(
            data,
            {
                "id",
                "kind",
                "artifact_id",
                "dependencies",
                "execution",
                "content_hash",
                "expected_schema",
                "step_hash",
            },
        )
        step = cls(
            id=data["id"],
            kind=RecipeStepKind(data["kind"]),
            artifact_id=data["artifact_id"],
            dependencies=tuple(data["dependencies"]),
            execution=data["execution"],
            content_hash=HashDigest.parse(data["content_hash"]),
            expected_schema=HashDigest.parse(data["expected_schema"]),
        )
        if data["step_hash"] != str(step.step_hash):
            raise ValueError("Serialized step_hash does not match step content")
        return step


@dataclass(frozen=True, slots=True)
class RecipeOutput:
    artifact_id: str
    step_id: str
    kind: RecipeStepKind

    def __post_init__(self) -> None:
        if not _ARTIFACT_ID_PATTERN.fullmatch(self.artifact_id):
            raise ValueError("Recipe output artifact_id is invalid")
        if not _STEP_ID_PATTERN.fullmatch(self.step_id):
            raise ValueError("Recipe output step_id is invalid")
        object.__setattr__(self, "kind", RecipeStepKind(self.kind))

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "step_id": self.step_id,
            "kind": self.kind.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecipeOutput":
        _require_exact_fields(data, {"artifact_id", "step_id", "kind"})
        return cls(
            artifact_id=data["artifact_id"],
            step_id=data["step_id"],
            kind=RecipeStepKind(data["kind"]),
        )


def _binding_slot(binding: ParameterBinding) -> tuple[Any, ...]:
    return (binding.step_id, binding.target.value, binding.filter_index)


def _validate_binding_slot(
    binding: ParameterBinding,
    parameter: RecipeParameter,
    step: RecipeStep,
) -> None:
    if step.kind is not RecipeStepKind.LOAD:
        raise ValueError("Recipe parameters may only bind to load steps in v1")
    execution = thaw_json(step.execution)
    source_step = execution.get("step")
    if not isinstance(source_step, dict):
        raise ValueError("Load step is missing connector step execution")
    query = source_step.get("query") or {}
    if not isinstance(query, dict):
        raise ValueError("Load step query must be an object")
    if binding.target is BindingTarget.LOAD_FILTER_VALUE:
        filters = query.get("filters") or []
        if (
            not isinstance(filters, list)
            or binding.filter_index is None
            or binding.filter_index >= len(filters)
        ):
            raise ValueError("Binding filter_index does not identify a load filter")
        if not isinstance(filters[binding.filter_index], dict):
            raise ValueError("Binding filter_index does not identify a load filter")
    elif binding.target is BindingTarget.LOAD_LIMIT:
        if parameter.value_type is not ParameterType.INTEGER:
            raise ValueError("load_limit binding requires an integer parameter")


@dataclass(frozen=True, slots=True)
class RecipeSpec:
    SCHEMA_VERSION: ClassVar[int] = 1

    recipe_id: str
    name: str
    description: str
    created_by: str
    identity_id: str
    workspace_id: str
    target_artifact_ids: tuple[str, ...]
    steps: tuple[RecipeStep, ...]
    parameters: tuple[RecipeParameter, ...]
    bindings: tuple[ParameterBinding, ...]
    inputs: tuple[RecipeInput, ...]
    final_outputs: tuple[RecipeOutput, ...]
    compiler_version: str
    version_id: str = field(init=False)
    recipe_hash: HashDigest = field(init=False)

    def __post_init__(self) -> None:
        if not _RECIPE_ID_PATTERN.fullmatch(self.recipe_id):
            raise ValueError("recipe_id is invalid")
        for field_name in (
            "name",
            "created_by",
            "identity_id",
            "workspace_id",
            "compiler_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")

        requested_targets = tuple(self.target_artifact_ids)
        if len(set(requested_targets)) != len(requested_targets):
            raise ValueError("target_artifact_ids must be unique")
        targets = tuple(sorted(requested_targets))
        if not targets or any(
            not _ARTIFACT_ID_PATTERN.fullmatch(item) for item in targets
        ):
            raise ValueError("target_artifact_ids must contain valid artifact ids")
        object.__setattr__(self, "target_artifact_ids", targets)
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(
            self,
            "parameters",
            tuple(sorted(self.parameters, key=lambda item: item.id)),
        )
        object.__setattr__(
            self,
            "bindings",
            tuple(
                sorted(
                    self.bindings,
                    key=lambda item: (
                        item.step_id,
                        item.target.value,
                        -1 if item.filter_index is None else item.filter_index,
                        item.parameter_id,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "inputs",
            tuple(sorted(self.inputs, key=lambda item: item.id)),
        )
        object.__setattr__(
            self,
            "final_outputs",
            tuple(sorted(self.final_outputs, key=lambda item: item.artifact_id)),
        )

        if not self.steps:
            raise ValueError("Recipe requires at least one step")
        step_ids: set[str] = set()
        artifact_ids: set[str] = set()
        steps_by_id: dict[str, RecipeStep] = {}
        for step in self.steps:
            if step.id in step_ids or step.artifact_id in artifact_ids:
                raise ValueError("Recipe step ids and artifact ids must be unique")
            if any(dependency not in step_ids for dependency in step.dependencies):
                raise ValueError("Recipe steps must be in topological dependency order")
            step_ids.add(step.id)
            artifact_ids.add(step.artifact_id)
            steps_by_id[step.id] = step
        if not set(self.target_artifact_ids).issubset(artifact_ids):
            raise ValueError("Every target artifact must have a recipe step")

        output_targets = {output.artifact_id for output in self.final_outputs}
        if output_targets != set(self.target_artifact_ids):
            raise ValueError("final_outputs must match target_artifact_ids")
        if any(
            output.step_id not in steps_by_id
            or steps_by_id[output.step_id].artifact_id != output.artifact_id
            or steps_by_id[output.step_id].kind is not output.kind
            for output in self.final_outputs
        ):
            raise ValueError("Recipe final output does not match its step")

        if len({item.id for item in self.inputs}) != len(self.inputs):
            raise ValueError("Recipe input ids must be unique")
        if len({item.step_id for item in self.inputs}) != len(self.inputs):
            raise ValueError("Every load step must have exactly one input")
        if any(
            item.step_id not in steps_by_id
            or steps_by_id[item.step_id].kind is not RecipeStepKind.LOAD
            for item in self.inputs
        ):
            raise ValueError("Recipe inputs must reference load steps")
        load_step_ids = {
            step.id for step in self.steps if step.kind is RecipeStepKind.LOAD
        }
        if {item.step_id for item in self.inputs} != load_step_ids:
            raise ValueError("Every load step must have exactly one input")
        if any(
            item.content_hash != steps_by_id[item.step_id].content_hash
            or item.expected_schema != steps_by_id[item.step_id].expected_schema
            for item in self.inputs
        ):
            raise ValueError("Recipe input hashes must match their load step")

        parameters_by_id = {item.id: item for item in self.parameters}
        if len(parameters_by_id) != len(self.parameters):
            raise ValueError("Recipe parameter ids must be unique")
        bound_parameters: set[str] = set()
        occupied_slots: set[tuple[Any, ...]] = set()
        for binding in self.bindings:
            parameter = parameters_by_id.get(binding.parameter_id)
            step = steps_by_id.get(binding.step_id)
            if parameter is None:
                raise ValueError(f"Unknown binding parameter: {binding.parameter_id}")
            if step is None:
                raise ValueError(f"Unknown binding step: {binding.step_id}")
            slot = _binding_slot(binding)
            if slot in occupied_slots:
                raise ValueError("Multiple parameters cannot bind to the same slot")
            occupied_slots.add(slot)
            bound_parameters.add(parameter.id)
            _validate_binding_slot(binding, parameter, step)
        if bound_parameters != set(parameters_by_id):
            raise ValueError("Every recipe parameter must have at least one binding")

        digest = HashDigest.sha256(canonical_json_bytes(self.identity_payload()))
        object.__setattr__(self, "recipe_hash", digest)
        object.__setattr__(self, "version_id", f"rv_{digest.digest}")

    @property
    def has_unresolved_inputs(self) -> bool:
        """Whether input resolution must finish before validation or publication."""
        return any(item.mode is InputMode.UNRESOLVED for item in self.inputs)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "recipe_id": self.recipe_id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "identity_id": self.identity_id,
            "workspace_id": self.workspace_id,
            "target_artifact_ids": list(self.target_artifact_ids),
            "steps": [step.to_dict() for step in self.steps],
            "parameters": [item.to_dict() for item in self.parameters],
            "bindings": [item.to_dict() for item in self.bindings],
            "inputs": [item.to_dict() for item in self.inputs],
            "final_outputs": [item.to_dict() for item in self.final_outputs],
            "compiler_version": self.compiler_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "version_id": self.version_id,
            "recipe_hash": str(self.recipe_hash),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecipeSpec":
        _require_exact_fields(
            data,
            {
                "schema_version",
                "recipe_id",
                "version_id",
                "recipe_hash",
                "name",
                "description",
                "created_by",
                "identity_id",
                "workspace_id",
                "target_artifact_ids",
                "steps",
                "parameters",
                "bindings",
                "inputs",
                "final_outputs",
                "compiler_version",
            },
        )
        if data["schema_version"] != cls.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported recipe schema version: {data['schema_version']!r}"
            )
        spec = cls(
            recipe_id=data["recipe_id"],
            name=data["name"],
            description=data["description"],
            created_by=data["created_by"],
            identity_id=data["identity_id"],
            workspace_id=data["workspace_id"],
            target_artifact_ids=tuple(data["target_artifact_ids"]),
            steps=tuple(RecipeStep.from_dict(item) for item in data["steps"]),
            parameters=tuple(
                RecipeParameter.from_dict(item) for item in data["parameters"]
            ),
            bindings=tuple(
                ParameterBinding.from_dict(item) for item in data["bindings"]
            ),
            inputs=tuple(RecipeInput.from_dict(item) for item in data["inputs"]),
            final_outputs=tuple(
                RecipeOutput.from_dict(item) for item in data["final_outputs"]
            ),
            compiler_version=data["compiler_version"],
        )
        if data["recipe_hash"] != str(spec.recipe_hash):
            raise ValueError("Serialized recipe_hash does not match recipe content")
        if data["version_id"] != spec.version_id:
            raise ValueError("Serialized version_id does not match recipe_hash")
        return spec
