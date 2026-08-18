# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic compiler from durable Artifact lineage to RecipeSpec v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from data_formulator.data_operations.models import ConnectorQueryStep
from data_formulator.recipes.canonical import canonical_json_bytes, canonical_sha256
from data_formulator.recipes.lineage import ArtifactLedger
from data_formulator.recipes.models import ArtifactNode, ArtifactType, HashDigest
from data_formulator.recipes.spec import (
    CredentialReference,
    InputMode,
    ParameterBinding,
    RecipeInput,
    RecipeOutput,
    RecipeParameter,
    RecipeSpec,
    RecipeStep,
    RecipeStepKind,
)
from data_formulator.recipes.table_artifacts import parquet_artifact_hashes
from data_formulator.security.code_signing import verify_code


class RecipeCompileError(ValueError):
    """Artifact lineage cannot be represented as an executable Recipe v1."""


@dataclass(frozen=True, slots=True)
class CompiledRecipe:
    spec: RecipeSpec
    workflow_markdown: str


def _step_id(artifact_id: str) -> str:
    return f"step_{artifact_id.removeprefix('art_')}"


def _execution(node: ArtifactNode) -> dict[str, Any]:
    return node.to_dict()["execution"]


def _output_table(execution: Mapping[str, Any]) -> tuple[str, str]:
    output = execution.get("output")
    if not isinstance(output, Mapping):
        raise RecipeCompileError("Artifact execution is missing output metadata")
    table_id = output.get("table_id")
    filename = output.get("filename")
    if not isinstance(table_id, str) or not table_id:
        raise RecipeCompileError("Artifact output table_id is invalid")
    if not isinstance(filename, str) or not filename:
        raise RecipeCompileError("Artifact output filename is invalid")
    return table_id, filename


class RecipeCompiler:
    COMPILER_VERSION = "recipe-compiler/1.0"

    def __init__(self, workspace, ledger: ArtifactLedger):
        if (
            workspace.identity_id != ledger.identity_id
            or workspace.workspace_id != ledger.workspace_id
        ):
            raise ValueError("Recipe compiler workspace and ledger scopes do not match")
        self._workspace = workspace
        self._ledger = ledger

    @classmethod
    def for_workspace(cls, workspace) -> "RecipeCompiler":
        return cls(workspace, ArtifactLedger.for_workspace(workspace))

    def compile(
        self,
        *,
        target_artifact_ids: Sequence[str],
        name: str,
        description: str = "",
        created_by: str | None = None,
        parameters: Sequence[RecipeParameter] = (),
        bindings: Sequence[ParameterBinding] = (),
    ) -> CompiledRecipe:
        if isinstance(target_artifact_ids, (str, bytes)):
            raise TypeError("target_artifact_ids must be a sequence of artifact ids")
        targets = tuple(sorted(set(target_artifact_ids)))
        nodes = self._ledger.ancestry(targets)
        by_id = {node.artifact_id: node for node in nodes}

        for node in nodes:
            self._verify_node(node, by_id)

        steps: list[RecipeStep] = []
        inputs: list[RecipeInput] = []
        for node in nodes:
            kind = RecipeStepKind.from_artifact_type(node.artifact_type)
            execution = _execution(node)
            step = RecipeStep(
                id=_step_id(node.artifact_id),
                kind=kind,
                artifact_id=node.artifact_id,
                dependencies=tuple(_step_id(parent_id) for parent_id in node.parent_ids),
                execution=execution,
                content_hash=node.content_hash,
                expected_schema=node.schema_fingerprint,
            )
            steps.append(step)
            if kind is RecipeStepKind.LOAD:
                inputs.append(self._compile_input(node, step, execution))

        final_outputs = tuple(
            RecipeOutput(
                artifact_id=artifact_id,
                step_id=_step_id(artifact_id),
                kind=RecipeStepKind.from_artifact_type(by_id[artifact_id].artifact_type),
            )
            for artifact_id in targets
        )
        recipe_id = "rcp_" + canonical_sha256({
            "identity_id": self._ledger.identity_id,
            "workspace_id": self._ledger.workspace_id,
            "target_artifact_ids": list(targets),
        })
        spec = RecipeSpec(
            recipe_id=recipe_id,
            name=name,
            description=description,
            created_by=created_by or self._ledger.identity_id,
            identity_id=self._ledger.identity_id,
            workspace_id=self._ledger.workspace_id,
            target_artifact_ids=targets,
            steps=tuple(steps),
            parameters=tuple(parameters),
            bindings=tuple(bindings),
            inputs=tuple(inputs),
            final_outputs=final_outputs,
            compiler_version=self.COMPILER_VERSION,
        )
        return CompiledRecipe(spec, self._workflow_markdown(spec))

    def _verify_node(
        self,
        node: ArtifactNode,
        nodes_by_id: Mapping[str, ArtifactNode],
    ) -> None:
        execution = _execution(node)
        if node.artifact_type in (ArtifactType.LOAD, ArtifactType.TRANSFORM):
            table_id, filename = _output_table(execution)
            metadata = self._workspace.get_table_metadata(table_id)
            if metadata is None or metadata.filename != filename:
                raise RecipeCompileError(
                    f"Artifact output table is unavailable: {table_id!r}"
                )
            try:
                content_hash, schema_fingerprint = parquet_artifact_hashes(
                    self._workspace,
                    metadata,
                )
            except Exception as exc:
                raise RecipeCompileError(
                    f"Artifact output cannot be verified: {table_id!r}"
                ) from exc
            if content_hash != node.content_hash:
                raise RecipeCompileError(
                    f"Artifact content hash changed for table {table_id!r}"
                )
            if schema_fingerprint != node.schema_fingerprint:
                raise RecipeCompileError(
                    f"Artifact schema fingerprint changed for table {table_id!r}"
                )

        if node.artifact_type is ArtifactType.LOAD:
            self._verify_load(node, execution)
        elif node.artifact_type is ArtifactType.TRANSFORM:
            self._verify_transform(node, execution, nodes_by_id)
        elif node.artifact_type is ArtifactType.CHART:
            self._verify_chart(node, execution, nodes_by_id)
        else:
            raise RecipeCompileError(
                f"Artifact type {node.artifact_type.value!r} is not executable in Recipe v1"
            )

    @staticmethod
    def _verify_load(node: ArtifactNode, execution: Mapping[str, Any]) -> None:
        if execution.get("kind") != "connector_query":
            raise RecipeCompileError("Load artifact must contain connector_query execution")
        step = execution.get("step")
        if not isinstance(step, Mapping):
            raise RecipeCompileError("Load artifact is missing its connector step snapshot")
        try:
            parsed_step = ConnectorQueryStep.from_dict(step)
        except (KeyError, TypeError, ValueError) as exc:
            raise RecipeCompileError("Load connector step snapshot is invalid") from exc
        if parsed_step.to_dict() != step:
            raise RecipeCompileError("Load connector step snapshot is not canonical")
        if node.parent_ids:
            raise RecipeCompileError("Load artifact cannot depend on parent artifacts")

    @staticmethod
    def _verify_transform(
        node: ArtifactNode,
        execution: Mapping[str, Any],
        nodes_by_id: Mapping[str, ArtifactNode],
    ) -> None:
        if execution.get("kind") != "python_transform":
            raise RecipeCompileError("Transform artifact must contain python_transform execution")
        code = execution.get("code")
        signature = execution.get("code_signature")
        if not isinstance(code, str) or not isinstance(signature, str):
            raise RecipeCompileError("Transform artifact is missing signed code")
        if not verify_code(code, signature):
            raise RecipeCompileError("Transform code signature is invalid")
        declared_inputs = execution.get("input_tables")
        if not isinstance(declared_inputs, list):
            raise RecipeCompileError("Transform artifact is missing declared inputs")
        declared_parent_ids: list[str] = []
        for index, item in enumerate(declared_inputs):
            if not isinstance(item, Mapping):
                raise RecipeCompileError("Transform declared input is invalid")
            parent_id = item.get("artifact_id")
            if not isinstance(parent_id, str):
                raise RecipeCompileError("Transform declared input is invalid")
            parent = nodes_by_id.get(parent_id)
            if parent is None:
                raise RecipeCompileError(
                    "Transform declared input does not identify an ancestor artifact"
                )
            parent_execution = _execution(parent)
            parent_table_id, _ = _output_table(parent_execution)
            if item.get("table_id") != parent_table_id:
                raise RecipeCompileError(
                    f"Transform declared input table at index {index} "
                    "does not match parent output"
                )
            declared_parent_ids.append(parent_id)
        if tuple(declared_parent_ids) != node.parent_ids:
            raise RecipeCompileError("Transform declared inputs do not match parent lineage")

    @staticmethod
    def _verify_chart(
        node: ArtifactNode,
        execution: Mapping[str, Any],
        nodes_by_id: Mapping[str, ArtifactNode],
    ) -> None:
        if execution.get("kind") != "chart":
            raise RecipeCompileError("Chart artifact must contain chart execution")
        if len(node.parent_ids) != 1:
            raise RecipeCompileError("Chart artifact requires exactly one transform parent")
        parent = nodes_by_id[node.parent_ids[0]]
        if parent.artifact_type is not ArtifactType.TRANSFORM:
            raise RecipeCompileError("Chart parent must be a transform artifact")
        input_table = execution.get("input_table")
        if (
            not isinstance(input_table, Mapping)
            or input_table.get("artifact_id") != parent.artifact_id
        ):
            raise RecipeCompileError("Chart input does not match its transform parent")
        parent_table_id, _ = _output_table(_execution(parent))
        if input_table.get("table_id") != parent_table_id:
            raise RecipeCompileError("Chart input table does not match its transform parent")
        expected_hash = HashDigest.sha256(canonical_json_bytes(execution))
        if expected_hash != node.content_hash:
            raise RecipeCompileError("Chart content hash does not match chart execution")
        if node.schema_fingerprint != parent.schema_fingerprint:
            raise RecipeCompileError("Chart schema does not match its transform parent")

    @staticmethod
    def _compile_input(
        node: ArtifactNode,
        step: RecipeStep,
        execution: Mapping[str, Any],
    ) -> RecipeInput:
        connector_step = execution.get("step")
        if not isinstance(connector_step, Mapping):
            raise RecipeCompileError("Load input has no connector step snapshot")
        source_id = ConnectorQueryStep.from_dict(connector_step).source_id
        if isinstance(source_id, str) and source_id.strip():
            mode = InputMode.REFRESHABLE
            credential_ref = CredentialReference("connector", source_id)
        else:
            mode = InputMode.UNRESOLVED
            source_id = None
            credential_ref = None
        return RecipeInput(
            id=f"input_{node.artifact_id.removeprefix('art_')}",
            step_id=step.id,
            mode=mode,
            source_id=source_id,
            credential_ref=credential_ref,
            content_hash=node.content_hash,
            expected_schema=node.schema_fingerprint,
        )

    @staticmethod
    def _workflow_markdown(spec: RecipeSpec) -> str:
        def one_line(value: Any) -> str:
            return " ".join(str(value).splitlines()).strip()

        lines = [f"# {one_line(spec.name)}", ""]
        if spec.description:
            lines.extend([one_line(spec.description), ""])
        lines.extend([
            f"- Recipe: `{spec.recipe_id}`",
            f"- Version: `{spec.version_id}`",
            f"- Hash: `{spec.recipe_hash}`",
            "",
            "## Inputs",
            "",
        ])
        for item in spec.inputs:
            source = f" (`{item.source_id}`)" if item.source_id else ""
            lines.append(f"- `{item.id}`: {item.mode.value}{source}")
        if not spec.inputs:
            lines.append("- None")

        if spec.parameters:
            lines.extend(["", "## Parameters", ""])
            for parameter in spec.parameters:
                lines.append(
                    f"- `{parameter.id}` ({parameter.value_type.value}): "
                    f"{one_line(parameter.name)}"
                )

        lines.extend(["", "## Steps", ""])
        for index, step in enumerate(spec.steps, start=1):
            execution = step.to_dict()["execution"]
            if step.kind is RecipeStepKind.LOAD:
                label = (execution.get("step") or {}).get("display_name", "Load data")
            elif step.kind is RecipeStepKind.TRANSFORM:
                label = (execution.get("output") or {}).get("table_id", "Transform data")
            else:
                label = execution.get("title") or execution.get("chart_id") or "Chart"
            dependency_text = (
                ", ".join(f"`{item}`" for item in step.dependencies)
                if step.dependencies
                else "none"
            )
            lines.extend([
                f"{index}. **{step.kind.value}** — {one_line(label)}",
                f"   - Step: `{step.id}`",
                f"   - Dependencies: {dependency_text}",
                f"   - Hash: `{step.step_hash}`",
            ])

        lines.extend(["", "## Outputs", ""])
        for output in spec.final_outputs:
            lines.append(
                f"- {output.kind.value}: `{output.artifact_id}` via `{output.step_id}`"
            )
        return "\n".join(lines) + "\n"
