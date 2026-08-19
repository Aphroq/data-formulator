# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Request-independent, deterministic execution for RecipeSpec v1."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any

from data_formulator.data_loader.connector_errors import (
    ConnectorErrorInfo,
    classify_connector_error,
)
from data_formulator.data_operations import (
    ConnectorQueryStep,
    DataOperation,
    DataOperationExecutor,
    DataOperationPlan,
    DataOperationStatus,
)
from data_formulator.recipes.binding import BoundRecipeStep, bind_recipe_parameters
from data_formulator.recipes.canonical import canonical_json_bytes, thaw_json
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.run_store import (
    RecipeRunArtifactStore,
    RecipeRunKind,
    RecipeRunReference,
    RecipeRunStatus,
    RecipeRunWriter,
)
from data_formulator.recipes.spec import InputMode, RecipeSpec, RecipeStep, RecipeStepKind
from data_formulator.recipes.table_artifacts import parquet_file_hashes
from data_formulator.sandbox.local_sandbox import LocalSandbox
from data_formulator.security.code_signing import (
    MAX_CODE_SIZE,
    require_stable_code_signing,
    verify_code,
)


LoaderResolver = Callable[[str], Any]
ExecutionCheckpoint = Callable[[], bool]


class _SanitizedLoaderProxy:
    """Keep connector exceptions and configuration out of Recipe run logs."""

    def __init__(
        self,
        loader: Any,
        error_sink: Callable[[ConnectorErrorInfo], None],
    ) -> None:
        self._loader = loader
        self._error_sink = error_sink

    def fetch_data_as_arrow(self, *, source_table: str, import_options: dict):
        try:
            return self._loader.fetch_data_as_arrow(
                source_table=source_table,
                import_options=import_options,
            )
        except Exception as exc:
            self._error_sink(
                classify_connector_error(exc, operation="refresh")
            )
            raise RuntimeError("Recipe connector fetch failed") from None

    @staticmethod
    def get_safe_params() -> dict:
        return {}

    def get_column_types(self, source_table: str):
        try:
            return self._loader.get_column_types(source_table)
        except Exception:
            return None


@dataclass(frozen=True, slots=True)
class RecipeExecutionError:
    code: str
    exception_type: str
    message: str
    retryable: bool = False
    automation_code: str | None = None
    automation_message: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "exception_type": self.exception_type,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class RecipeStepResult:
    step_id: str
    kind: RecipeStepKind
    content_hash: HashDigest
    schema_hash: HashDigest
    output_path: str
    duration_ms: int = 0

    def event_details(self) -> dict[str, Any]:
        return {
            "content_hash": str(self.content_hash),
            "schema_hash": str(self.schema_hash),
            "output_path": self.output_path,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class RecipeExecutionResult:
    status: RecipeRunStatus
    reference: RecipeRunReference | None
    step_results: tuple[RecipeStepResult, ...]
    error: RecipeExecutionError | None = None


class RecipeExecutionFailure(RuntimeError):
    code = "execution_error"
    safe_message = "Recipe execution failed."
    status = RecipeRunStatus.FAILED

    def __init__(self, *, step_result: RecipeStepResult | None = None) -> None:
        super().__init__(self.safe_message)
        self.step_result = step_result

    def public_error(self) -> RecipeExecutionError:
        return RecipeExecutionError(
            code=self.code,
            exception_type=type(self).__name__,
            message=self.safe_message,
        )


class RecipeExecutionAborted(RuntimeError):
    """Stop an attempt without committing a terminal immutable manifest."""


class _RecipeExecutionCancelled(RuntimeError):
    """Internal control flow for a cooperative boundary cancellation."""


class RecipeExecutionValidationError(RecipeExecutionFailure):
    code = "invalid_recipe"
    safe_message = "Recipe execution inputs are invalid."


class RecipeUnresolvedInputError(RecipeExecutionFailure):
    code = "unresolved_input"
    safe_message = "Recipe inputs must be resolved before execution."


class RecipeUnsupportedInputError(RecipeExecutionFailure):
    code = "unsupported_input_mode"
    safe_message = "A Recipe input mode is not executable in Recipe v1."


class RecipeDependencyError(RecipeExecutionFailure):
    code = "dependency_not_satisfied"
    safe_message = "A Recipe step dependency was not satisfied."


class RecipeConnectorError(RecipeExecutionFailure):
    code = "connector_error"
    safe_message = "A Recipe input could not be loaded."

    def __init__(
        self,
        connector_error: ConnectorErrorInfo | None = None,
    ) -> None:
        super().__init__()
        self.connector_error = connector_error

    def public_error(self) -> RecipeExecutionError:
        error = self.connector_error
        return RecipeExecutionError(
            code=self.code,
            exception_type=type(self).__name__,
            message=self.safe_message,
            retryable=bool(error and error.retry),
            automation_code=error.code if error is not None else None,
            automation_message=error.message if error is not None else None,
        )


class RecipeCodeSignatureError(RecipeExecutionFailure):
    code = "invalid_code_signature"
    safe_message = "Recipe transform code signature is invalid."


class RecipeTransformError(RecipeExecutionFailure):
    code = "transform_error"
    safe_message = "A Recipe transform could not be executed."


class RecipeChartError(RecipeExecutionFailure):
    code = "chart_error"
    safe_message = "A Recipe chart artifact could not be materialized."


class RecipeSchemaDriftError(RecipeExecutionFailure):
    code = "schema_drift"
    safe_message = "A Recipe step produced an incompatible schema."
    status = RecipeRunStatus.NEEDS_REVIEW


class RecipeExecutor:
    """Execute saved load/transform/chart steps without an Agent or request."""

    def __init__(
        self,
        source_workspace,
        loader_resolver: LoaderResolver,
        *,
        sandbox: LocalSandbox | None = None,
    ) -> None:
        self._source_workspace = source_workspace
        self._loader_resolver = loader_resolver
        self._sandbox = sandbox or LocalSandbox()
        self._run_store = RecipeRunArtifactStore.for_workspace(source_workspace)
        self._connector_error: ConnectorErrorInfo | None = None

    def execute(
        self,
        spec: RecipeSpec,
        *,
        parameter_values: Mapping[str, Any],
        kind: RecipeRunKind,
        run_id: str | None = None,
        checkpoint: ExecutionCheckpoint | None = None,
    ) -> RecipeExecutionResult:
        require_stable_code_signing()
        try:
            self._validate_spec(spec)
            bound = bind_recipe_parameters(spec, parameter_values)
        except (TypeError, ValueError) as exc:
            error = RecipeExecutionError(
                code="invalid_recipe",
                exception_type=type(exc).__name__,
                message=RecipeExecutionValidationError.safe_message,
            )
            return RecipeExecutionResult(
                status=RecipeRunStatus.FAILED,
                reference=None,
                step_results=(),
                error=error,
            )

        writer = self._run_store.begin(spec, bound, kind, run_id=run_id)
        self._connector_error = None
        results: list[RecipeStepResult] = []
        current_step: RecipeStep | None = None
        step_started: float | None = None
        try:
            self._run_checkpoint(checkpoint)
            if spec.has_unresolved_inputs:
                raise RecipeUnresolvedInputError()
            unsupported = [
                item for item in spec.inputs
                if item.mode is not InputMode.REFRESHABLE
            ]
            if unsupported:
                raise RecipeUnsupportedInputError()

            bound_by_id = {step.id: step for step in bound.steps}
            completed: set[str] = set()
            for current_step in spec.steps:
                if not set(current_step.dependencies).issubset(completed):
                    raise RecipeDependencyError()
                writer.append_event(
                    step_id=current_step.id,
                    kind=current_step.kind,
                    status="started",
                )
                step_started = perf_counter()
                result = self._execute_step(
                    spec,
                    current_step,
                    bound_by_id[current_step.id],
                    writer,
                )
                result = replace(
                    result,
                    duration_ms=max(0, round((perf_counter() - step_started) * 1000)),
                )
                results.append(result)
                writer.append_event(
                    step_id=current_step.id,
                    kind=current_step.kind,
                    status="succeeded",
                    details=result.event_details(),
                )
                completed.add(current_step.id)
                self._run_checkpoint(checkpoint)
        except RecipeExecutionAborted:
            raise
        except _RecipeExecutionCancelled:
            return self._cancelled_result(writer, results)
        except RecipeExecutionFailure as exc:
            cancelled = self._checkpoint_failure_boundary(
                checkpoint,
                writer,
                results,
            )
            if cancelled is not None:
                return cancelled
            if exc.step_result is not None:
                partial = exc.step_result
                if step_started is not None:
                    partial = replace(
                        partial,
                        duration_ms=max(
                            0,
                            round((perf_counter() - step_started) * 1000),
                        ),
                    )
                results.append(partial)
            error = exc.public_error()
            if current_step is not None:
                details: dict[str, Any] = {"error": error.to_dict()}
                if step_started is not None:
                    details["duration_ms"] = max(
                        0,
                        round((perf_counter() - step_started) * 1000),
                    )
                writer.append_event(
                    step_id=current_step.id,
                    kind=current_step.kind,
                    status=exc.status.value,
                    details=details,
                )
            reference = writer.finalize(exc.status, error=error.to_dict())
            return RecipeExecutionResult(
                status=exc.status,
                reference=reference,
                step_results=tuple(results),
                error=error,
            )
        except Exception as exc:
            cancelled = self._checkpoint_failure_boundary(
                checkpoint,
                writer,
                results,
            )
            if cancelled is not None:
                return cancelled
            error = RecipeExecutionError(
                code="execution_error",
                exception_type=type(exc).__name__,
                message=RecipeExecutionFailure.safe_message,
            )
            if current_step is not None:
                details: dict[str, Any] = {"error": error.to_dict()}
                if step_started is not None:
                    details["duration_ms"] = max(
                        0,
                        round((perf_counter() - step_started) * 1000),
                    )
                writer.append_event(
                    step_id=current_step.id,
                    kind=current_step.kind,
                    status=RecipeRunStatus.FAILED.value,
                    details=details,
                )
            reference = writer.finalize(
                RecipeRunStatus.FAILED,
                error=error.to_dict(),
            )
            return RecipeExecutionResult(
                status=RecipeRunStatus.FAILED,
                reference=reference,
                step_results=tuple(results),
                error=error,
            )

        reference = writer.finalize(RecipeRunStatus.SUCCEEDED)
        return RecipeExecutionResult(
            status=RecipeRunStatus.SUCCEEDED,
            reference=reference,
            step_results=tuple(results),
        )

    def _execute_step(
        self,
        spec: RecipeSpec,
        step: RecipeStep,
        bound_step: BoundRecipeStep,
        writer: RecipeRunWriter,
    ) -> RecipeStepResult:
        if step.kind is RecipeStepKind.LOAD:
            return self._execute_load(spec, step, bound_step, writer)
        if step.kind is RecipeStepKind.TRANSFORM:
            return self._execute_transform(step, bound_step, writer)
        if step.kind is RecipeStepKind.CHART:
            return self._execute_chart(step, bound_step, writer)
        raise RecipeExecutionValidationError()

    def _execute_load(
        self,
        spec: RecipeSpec,
        step: RecipeStep,
        bound_step: BoundRecipeStep,
        writer: RecipeRunWriter,
    ) -> RecipeStepResult:
        execution = thaw_json(bound_step.execution)
        try:
            if execution.get("kind") != "connector_query":
                raise ValueError("Unexpected load execution kind")
            connector = ConnectorQueryStep.from_dict(execution["step"])
            output = execution["output"]
            table_id = str(output["table_id"])
            filename = str(output["filename"])
            connector = replace(connector, display_name=table_id)
            recipe_input = next(item for item in spec.inputs if item.step_id == step.id)
            if connector.source_id != recipe_input.source_id:
                raise ValueError("Load source does not match Recipe input")
        except (KeyError, StopIteration, TypeError, ValueError):
            raise RecipeExecutionValidationError() from None

        plan = DataOperationPlan(
            id=f"plan-{writer.run_id}-{step.id}",
            label=table_id,
            summary="Recipe load",
            steps=(connector,),
        )
        operation = DataOperation(
            id=f"operation-{writer.run_id}-{step.id}",
            reason="Execute persisted Recipe load step",
            plans=(plan,),
            status=DataOperationStatus.RUNNING,
            selected_plan_id=plan.id,
        )
        result = DataOperationExecutor(
            writer.workspace,
            self._resolve_loader_safely,
        ).execute(operation)
        if result.failed_steps or result.result_table_ids != (table_id,):
            raise RecipeConnectorError(self._connector_error)
        metadata = writer.workspace.get_table_metadata(table_id)
        if metadata is None or metadata.filename != filename:
            raise RecipeExecutionValidationError()
        # DataOperation metadata contains the bound connector step and the
        # loader's safe params. Neither is needed to replay downstream steps,
        # and bound filter values must not become part of durable run metadata.
        metadata.loader_type = None
        metadata.loader_params = None
        metadata.source_table = None
        metadata.source_query = None
        metadata.import_options = {
            "recipe_run": {
                "step_id": step.id,
                "kind": step.kind.value,
            }
        }
        writer.workspace.add_table_metadata(metadata)
        result_item = self._table_result(step, writer, table_id)
        if result_item.schema_hash != step.expected_schema:
            raise RecipeSchemaDriftError(step_result=result_item)
        return result_item

    def _resolve_loader_safely(self, source_id: str) -> _SanitizedLoaderProxy:
        try:
            return _SanitizedLoaderProxy(
                self._loader_resolver(source_id),
                self._record_connector_error,
            )
        except Exception as exc:
            self._record_connector_error(
                classify_connector_error(exc, operation="refresh")
            )
            raise RuntimeError("Recipe connector could not be opened") from None

    def _record_connector_error(self, error: ConnectorErrorInfo) -> None:
        self._connector_error = error

    @staticmethod
    def _run_checkpoint(checkpoint: ExecutionCheckpoint | None) -> None:
        if checkpoint is not None and checkpoint():
            raise _RecipeExecutionCancelled()

    @classmethod
    def _checkpoint_failure_boundary(
        cls,
        checkpoint: ExecutionCheckpoint | None,
        writer: RecipeRunWriter,
        results: list[RecipeStepResult],
    ) -> RecipeExecutionResult | None:
        try:
            cls._run_checkpoint(checkpoint)
        except _RecipeExecutionCancelled:
            return cls._cancelled_result(writer, results)
        return None

    @staticmethod
    def _cancelled_result(
        writer: RecipeRunWriter,
        results: list[RecipeStepResult],
    ) -> RecipeExecutionResult:
        reference = writer.finalize(RecipeRunStatus.CANCELLED)
        return RecipeExecutionResult(
            status=RecipeRunStatus.CANCELLED,
            reference=reference,
            step_results=tuple(results),
        )

    def _execute_transform(
        self,
        step: RecipeStep,
        bound_step: BoundRecipeStep,
        writer: RecipeRunWriter,
    ) -> RecipeStepResult:
        execution = thaw_json(bound_step.execution)
        try:
            if execution.get("kind") != "python_transform":
                raise ValueError("Unexpected transform execution kind")
            code = execution["code"]
            signature = execution["code_signature"]
            output_variable = execution["output_variable"]
            output = execution["output"]
            table_id = str(output["table_id"])
            filename = str(output["filename"])
            if not all(
                isinstance(value, str) and value
                for value in (code, signature, output_variable)
            ):
                raise ValueError("Transform execution fields are invalid")
        except (KeyError, TypeError, ValueError):
            raise RecipeExecutionValidationError() from None
        if len(code.encode("utf-8")) > MAX_CODE_SIZE or not verify_code(
            code,
            signature,
            require_stable=True,
        ):
            raise RecipeCodeSignatureError()

        sandbox_result = self._sandbox.run_python_code(
            code,
            writer.workspace,
            output_variable,
        )
        if sandbox_result.get("status") != "ok":
            raise RecipeTransformError()
        try:
            metadata = writer.workspace.write_parquet(
                sandbox_result["content"],
                table_id,
            )
        except Exception:
            raise RecipeTransformError() from None
        if metadata.filename != filename:
            raise RecipeExecutionValidationError()
        result_item = self._table_result(step, writer, table_id)
        if result_item.schema_hash != step.expected_schema:
            raise RecipeSchemaDriftError(step_result=result_item)
        return result_item

    def _execute_chart(
        self,
        step: RecipeStep,
        bound_step: BoundRecipeStep,
        writer: RecipeRunWriter,
    ) -> RecipeStepResult:
        execution = thaw_json(bound_step.execution)
        try:
            if execution.get("kind") != "chart":
                raise ValueError("Unexpected chart execution kind")
            input_table = execution["input_table"]
            table_id = str(input_table["table_id"])
            input_path = writer.workspace.get_parquet_path(table_id)
        except (KeyError, TypeError, ValueError, FileNotFoundError):
            raise RecipeChartError() from None

        _, schema_hash = parquet_file_hashes(input_path)
        if schema_hash != step.expected_schema:
            raise RecipeSchemaDriftError()
        content = canonical_json_bytes(execution)
        content_hash = HashDigest.sha256(content)
        if content_hash != step.content_hash:
            raise RecipeExecutionValidationError()
        output_path = writer.output_path(f"{step.id}.chart.json")
        output_path.write_bytes(content)
        return RecipeStepResult(
            step_id=step.id,
            kind=step.kind,
            content_hash=content_hash,
            schema_hash=schema_hash,
            output_path=output_path.relative_to(writer.root).as_posix(),
        )

    @staticmethod
    def _table_result(
        step: RecipeStep,
        writer: RecipeRunWriter,
        table_id: str,
    ) -> RecipeStepResult:
        path = writer.workspace.get_parquet_path(table_id)
        content_hash, schema_hash = parquet_file_hashes(path)
        return RecipeStepResult(
            step_id=step.id,
            kind=step.kind,
            content_hash=content_hash,
            schema_hash=schema_hash,
            output_path=path.relative_to(writer.root).as_posix(),
        )

    def _validate_spec(self, spec: RecipeSpec) -> None:
        if not isinstance(spec, RecipeSpec):
            raise TypeError("RecipeExecutor requires RecipeSpec")
        if spec.identity_id != self._source_workspace.identity_id:
            raise ValueError("Recipe identity does not match Workspace")
        if spec.workspace_id != self._source_workspace.workspace_id:
            raise ValueError("Recipe workspace does not match Workspace")
        if RecipeSpec.from_dict(spec.to_dict()) != spec:
            raise ValueError("RecipeSpec self-verification failed")
