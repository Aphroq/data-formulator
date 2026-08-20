# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace-aware orchestration for Schedule and durable Run APIs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from data_formulator.automation.models import (
    AutomationRunStatus,
    StoredAutomationRun,
    StoredSchedule,
)
from data_formulator.automation.parameters import (
    normalize_manual_parameter_values,
    normalize_schedule_parameter_policy,
)
from data_formulator.automation.repository import (
    AutomationRepository,
    AutomationStateError,
)
from data_formulator.datalake.parquet_utils import (
    df_to_safe_records,
    normalize_dtype_to_app_type,
)
from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.canonical import thaw_json
from data_formulator.recipes.repository import (
    RecipeRepository,
    RecipeVersionStatus,
)
from data_formulator.recipes.run_store import (
    RecipeRunArtifactStore,
    RecipeRunCorruptError,
    RecipeRunKind,
    RecipeRunReference,
    RecipeRunStatus,
    StoredRecipeRun,
)
from data_formulator.recipes.spec import RecipeSpec, RecipeStepKind
from data_formulator.security.code_signing import require_stable_code_signing
from data_formulator.security.path_safety import ConfinedDir


_ARTIFACT_STATUSES = {
    AutomationRunStatus.SUCCEEDED: RecipeRunStatus.SUCCEEDED,
    AutomationRunStatus.FAILED: RecipeRunStatus.FAILED,
    AutomationRunStatus.NEEDS_REVIEW: RecipeRunStatus.NEEDS_REVIEW,
    AutomationRunStatus.CANCELLED: RecipeRunStatus.CANCELLED,
}

_RESULT_PREVIEW_ROWS = 100
_RESULT_PREVIEW_COLUMNS = 50


@dataclass(frozen=True, slots=True)
class AutomationRunResult:
    """Verified user-facing outputs for one finalized Automation Run."""

    artifact: StoredRecipeRun
    report: dict[str, Any]
    outputs: tuple[dict[str, Any], ...]
    _workspace: Workspace = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class AutomationRunTable:
    """One final-output table opened from a verified Run artifact."""

    artifact: StoredRecipeRun
    workspace: Workspace = field(repr=False, compare=False)
    name: str


def _quote_duckdb_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


class AutomationService:
    """Join the queue catalog to immutable Recipe and Run artifacts."""

    def __init__(
        self,
        automation_repository: AutomationRepository,
        recipe_repository: RecipeRepository,
    ) -> None:
        if automation_repository.database_path != recipe_repository.database_path:
            raise ValueError(
                "Automation and Recipe repositories must share one database"
            )
        self._automation = automation_repository
        self._recipes = recipe_repository

    def create_schedule(
        self,
        workspace,
        *,
        version_id: str,
        name: str,
        cron_expression: str,
        timezone_name: str,
        parameter_policy: Mapping[str, Any] | None = None,
    ) -> StoredSchedule:
        require_stable_code_signing()
        spec = self._load_spec(workspace, version_id, require_published=True)
        normalized_policy = normalize_schedule_parameter_policy(
            spec,
            parameter_policy or {},
        )
        return self._automation.create_schedule(
            identity_id=workspace.identity_id,
            workspace_id=workspace.workspace_id,
            version_id=version_id,
            name=name,
            cron_expression=cron_expression,
            timezone_name=timezone_name,
            parameter_policy=normalized_policy,
        )

    def update_schedule(
        self,
        workspace,
        schedule_id: str,
        *,
        name: str | None = None,
        cron_expression: str | None = None,
        timezone_name: str | None = None,
        parameter_policy: Mapping[str, Any] | None = None,
    ) -> StoredSchedule:
        require_stable_code_signing()
        normalized_policy = None
        if parameter_policy is not None:
            schedule = self._automation.get_schedule(
                workspace.identity_id,
                workspace.workspace_id,
                schedule_id,
            )
            spec = self._load_spec(
                workspace,
                schedule.version_id,
                require_published=False,
            )
            normalized_policy = normalize_schedule_parameter_policy(
                spec,
                parameter_policy,
            )
        return self._automation.update_schedule(
            workspace.identity_id,
            workspace.workspace_id,
            schedule_id,
            name=name,
            cron_expression=cron_expression,
            timezone_name=timezone_name,
            parameter_policy=normalized_policy,
        )

    def enqueue_manual_run(
        self,
        workspace,
        version_id: str,
        parameter_values: Mapping[str, Any] | None = None,
    ) -> StoredAutomationRun:
        require_stable_code_signing()
        spec = self._load_spec(workspace, version_id, require_published=True)
        normalized_values = normalize_manual_parameter_values(
            spec,
            parameter_values or {},
        )
        return self._automation.enqueue_manual_run(
            workspace.identity_id,
            workspace.workspace_id,
            version_id,
            parameter_values=normalized_values,
        )

    def load_run_artifact(
        self,
        workspace,
        run_id: str,
    ) -> StoredRecipeRun:
        run = self._automation.get_run(
            workspace.identity_id,
            workspace.workspace_id,
            run_id,
        )
        artifact_status = _ARTIFACT_STATUSES.get(run.status)
        if artifact_status is None:
            raise AutomationStateError(
                "Run artifacts are unavailable while the Run is active"
            )
        if (
            run.artifact_run_id is None
            or run.artifact_path is None
            or run.manifest_hash is None
            or run.binding_hash is None
        ):
            raise AutomationStateError(
                "This Run did not produce a finalized artifact"
            )
        version = self._recipes.get_version(
            workspace.identity_id,
            workspace.workspace_id,
            run.version_id,
        )
        reference = RecipeRunReference(
            run_id=run.artifact_run_id,
            recipe_id=version.recipe_id,
            version_id=run.version_id,
            identity_id=workspace.identity_id,
            workspace_id=workspace.workspace_id,
            kind=RecipeRunKind.AUTOMATION,
            status=artifact_status,
            binding_hash=run.binding_hash,
            artifact_path=run.artifact_path,
            manifest_hash=run.manifest_hash,
        )
        return RecipeRunArtifactStore.for_workspace(workspace).load(reference)

    def load_run_result(
        self,
        workspace,
        run_id: str,
    ) -> AutomationRunResult:
        """Read bounded table/chart previews from an already verified Run."""
        artifact = self.load_run_artifact(workspace, run_id)
        loaded = self._recipes.load_version(workspace, artifact.reference.version_id)
        spec = loaded.compiled.spec
        successful_steps = {
            event.get("step_id")
            for event in artifact.events
            if event.get("status") == "succeeded"
        }
        try:
            run_root = workspace.confined_root.resolve(
                artifact.reference.artifact_path,
            )
            run_workspace_path = ConfinedDir(
                run_root,
                mkdir=False,
            ).resolve("workspace")
            run_workspace = Workspace(
                spec.identity_id,
                workspace_path=run_workspace_path,
                workspace_id=spec.workspace_id,
                storage_backend="recipe_run",
                durable=True,
                supports_durable_artifacts=False,
            )
            steps = {step.id: step for step in spec.steps}
            outputs = tuple(
                self._result_output(
                    spec,
                    steps[output.step_id],
                    run_workspace,
                )
                for output in spec.final_outputs
                if output.step_id in successful_steps
            )
            if (
                artifact.reference.status is RecipeRunStatus.SUCCEEDED
                and len(outputs) != len(spec.final_outputs)
            ):
                raise ValueError("A successful Run is missing a final output")
            return AutomationRunResult(
                artifact=artifact,
                report=self._result_report(spec),
                outputs=outputs,
                _workspace=run_workspace,
            )
        except RecipeRunCorruptError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise RecipeRunCorruptError(
                "Recipe run result could not be verified"
            ) from exc

    def open_run_result_table(
        self,
        workspace,
        run_id: str,
        table_name: str,
    ) -> AutomationRunTable:
        """Open an allowed final-output table without copying the Run.

        The Run manifest and every file hash are verified by
        :meth:`load_run_result` before the immutable artifact Workspace is
        exposed to a read-only route.  Intermediate tables are deliberately
        excluded from this boundary: the result viewer renders declared final
        outputs, while the audit view remains responsible for step evidence.
        """
        if not isinstance(table_name, str) or not table_name:
            raise ValueError("Run result table name is required")
        result = self.load_run_result(workspace, run_id)
        if result.artifact.reference.status is not RecipeRunStatus.SUCCEEDED:
            raise AutomationStateError(
                "Run results are available only for successful Runs"
            )
        allowed_names = {
            output["table"]["name"]
            for output in result.outputs
            if isinstance(output.get("table"), Mapping)
            and isinstance(output["table"].get("name"), str)
        }
        if table_name not in allowed_names:
            raise AutomationStateError(
                "The requested table is not a declared Run output"
            )
        return AutomationRunTable(
            artifact=result.artifact,
            workspace=result._workspace,
            name=table_name,
        )

    @classmethod
    def _result_output(
        cls,
        spec: RecipeSpec,
        step,
        run_workspace: Workspace,
    ) -> dict[str, Any]:
        execution = thaw_json(step.execution)
        chart: dict[str, Any] | None = None
        if step.kind is RecipeStepKind.CHART:
            input_table = execution.get("input_table")
            chart_spec = execution.get("chart")
            if not isinstance(input_table, Mapping) or not isinstance(
                chart_spec,
                Mapping,
            ):
                raise ValueError("Chart output metadata is invalid")
            table_name = input_table.get("table_id")
            if not isinstance(table_name, str) or not table_name:
                raise ValueError("Chart output table is invalid")
            field_metadata = execution.get("field_metadata")
            field_display_names = execution.get("field_display_names")
            chart = {
                "spec": dict(chart_spec),
                "field_metadata": (
                    dict(field_metadata)
                    if isinstance(field_metadata, Mapping)
                    else {}
                ),
                "field_display_names": (
                    dict(field_display_names)
                    if isinstance(field_display_names, Mapping)
                    else {}
                ),
            }
        elif step.kind in {RecipeStepKind.LOAD, RecipeStepKind.TRANSFORM}:
            output = execution.get("output")
            if not isinstance(output, Mapping):
                raise ValueError("Table output metadata is invalid")
            table_name = output.get("table_id")
            if not isinstance(table_name, str) or not table_name:
                raise ValueError("Table output is invalid")
            chart_spec = None
        else:
            raise ValueError("Recipe output kind is invalid")

        return {
            "step_id": step.id,
            "kind": step.kind.value,
            "title": _string(execution.get("title")) or table_name,
            "subtitle": _string(execution.get("subtitle")),
            "display_instruction": _string(execution.get("display_instruction")),
            "chart": chart,
            "table": cls._table_preview(
                run_workspace,
                table_name,
                chart_spec=chart_spec,
            ),
        }

    @staticmethod
    def _result_report(spec: RecipeSpec) -> dict[str, Any]:
        """Build the stable, human-facing context for a Run report.

        The projection comes only from the verified immutable RecipeVersion.
        It deliberately excludes hashes, source code, and generated prose: the
        report explains what this fixed analysis does without turning a normal
        Automation Run into Workflow Replay or an LLM call.
        """

        steps: list[dict[str, str]] = []
        for step in spec.steps:
            execution = thaw_json(step.execution)
            title = ""
            if step.kind is RecipeStepKind.LOAD:
                source = execution.get("step")
                if isinstance(source, Mapping):
                    title = _string(source.get("display_name")) or _string(
                        source.get("source_table")
                    )
            elif step.kind is RecipeStepKind.TRANSFORM:
                output = execution.get("output")
                if isinstance(output, Mapping):
                    title = _string(output.get("table_id"))
            elif step.kind is RecipeStepKind.CHART:
                title = _string(execution.get("title")) or _string(
                    execution.get("chart_id")
                )
            steps.append({
                "step_id": step.id,
                "kind": step.kind.value,
                "title": title,
            })

        return {
            "title": spec.name,
            "description": spec.description,
            "parameters": [
                {
                    "id": parameter.id,
                    "name": parameter.name,
                    "description": parameter.description,
                    "type": parameter.value_type.value,
                }
                for parameter in spec.parameters
            ],
            "steps": steps,
        }

    @staticmethod
    def _table_preview(
        run_workspace: Workspace,
        table_name: str,
        *,
        chart_spec: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        schema = run_workspace.get_parquet_schema(table_name)
        raw_columns = schema.get("columns")
        if not isinstance(raw_columns, list):
            raise ValueError("Result table schema is invalid")
        columns: list[tuple[str, str]] = []
        for item in raw_columns:
            if not isinstance(item, Mapping):
                raise ValueError("Result table column is invalid")
            name = item.get("name")
            dtype = item.get("type")
            if not isinstance(name, str) or not isinstance(dtype, str):
                raise ValueError("Result table column is invalid")
            columns.append((name, dtype))

        preferred: list[str] = []
        if chart_spec is not None:
            encodings = chart_spec.get("encodings")
            if isinstance(encodings, Mapping):
                for value in encodings.values():
                    if isinstance(value, str) and value not in preferred:
                        preferred.append(value)
        available = {name for name, _dtype in columns}
        selected_names = [name for name in preferred if name in available]
        selected_names.extend(
            name
            for name, _dtype in columns
            if name not in selected_names
        )
        selected_names = selected_names[:_RESULT_PREVIEW_COLUMNS]
        selected_types = dict(columns)

        if selected_names:
            select_list = ", ".join(
                _quote_duckdb_identifier(name) for name in selected_names
            )
            frame = run_workspace.run_parquet_sql(
                table_name,
                (
                    f"SELECT {select_list} FROM {{parquet}} AS result "
                    f"LIMIT {_RESULT_PREVIEW_ROWS}"
                ),
            )
            rows = df_to_safe_records(frame)
        else:
            rows = []

        row_count = schema.get("num_rows")
        column_count = schema.get("num_columns")
        if type(row_count) is not int or type(column_count) is not int:
            raise ValueError("Result table dimensions are invalid")
        return {
            "name": table_name,
            "row_count": row_count,
            "column_count": column_count,
            "columns": [
                {
                    "name": name,
                    "type": normalize_dtype_to_app_type(selected_types[name]),
                }
                for name in selected_names
            ],
            "rows": rows,
            "rows_truncated": row_count > len(rows),
            "columns_truncated": column_count > len(selected_names),
        }

    def _load_spec(
        self,
        workspace,
        version_id: str,
        *,
        require_published: bool,
    ) -> RecipeSpec:
        loaded = self._recipes.load_version(workspace, version_id)
        if (
            require_published
            and loaded.version.status is not RecipeVersionStatus.PUBLISHED
        ):
            raise AutomationStateError(
                "Automation requires a published RecipeVersion"
            )
        return loaded.compiled.spec
