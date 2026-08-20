from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timezone
from typing import Callable

import pyarrow as pa
import pandas as pd

from data_formulator.datalake.parquet_utils import sanitize_table_name
from data_formulator.datalake.workspace_metadata import TableMetadata
from data_formulator.data_loader.external_data_loader import (
    ExternalDataLoader,
    _merge_source_metadata,
    apply_import_projection,
)
from data_formulator.recipes.lineage import (
    ArtifactConflictError,
    ArtifactLedger,
)
from data_formulator.recipes.models import ArtifactNode, ArtifactType
from data_formulator.recipes.table_artifacts import parquet_artifact_hashes

from .models import (
    ConnectorQueryStep,
    DataOperation,
    DataOperationStatus,
    FailedOperationStep,
    OperationError,
)


logger = logging.getLogger(__name__)


LoaderResolver = Callable[[str], ExternalDataLoader]


def _like_pattern(value: object) -> str:
    parts: list[str] = []
    for character in str(value):
        if character == "%":
            parts.append(".*")
        elif character == "_":
            parts.append(".")
        else:
            parts.append(re.escape(character))
    return "^" + "".join(parts) + "$"


def _apply_source_filters_locally(
    table: pa.Table,
    source_filters: object,
) -> pa.Table:
    """Enforce a ConnectorQueryStep when a loader does not push filters down."""
    if not source_filters:
        return table
    if not isinstance(source_filters, list):
        raise TypeError("Source filters must be an array")
    frame = table.to_pandas()
    mask = pd.Series(True, index=frame.index, dtype=bool)
    for item in source_filters:
        if not isinstance(item, Mapping):
            raise TypeError("Source filter must be an object")
        column_name = item.get("column")
        operator = str(item.get("operator") or "").upper()
        if not isinstance(column_name, str):
            raise ValueError("Source filter column is unavailable")
        if column_name not in frame.columns:
            # Some connectors apply the filter remotely and return only the
            # requested projection.  In that case the filtered column is no
            # longer available for an idempotent local check.  We explicitly
            # request filter columns when the connector supports projection;
            # locally enforce every filter that is present in the response.
            continue
        column = frame[column_name]
        value = item.get("value")
        try:
            if operator == "EQ":
                selected = column.isna() if value is None else column.eq(value)
            elif operator == "NEQ":
                selected = column.notna() if value is None else column.ne(value)
            elif operator == "GT":
                selected = column.gt(value)
            elif operator == "GTE":
                selected = column.ge(value)
            elif operator == "LT":
                selected = column.lt(value)
            elif operator == "LTE":
                selected = column.le(value)
            elif operator in {"LIKE", "ILIKE"}:
                selected = column.astype("string").str.match(
                    _like_pattern(value),
                    case=operator == "LIKE",
                    na=False,
                )
            elif operator == "IN":
                values = value if isinstance(value, (list, tuple)) else [value]
                selected = column.isin(values)
            elif operator == "NOT_IN":
                values = value if isinstance(value, (list, tuple)) else [value]
                selected = ~column.isin(values)
            elif operator == "IS_NULL":
                selected = column.isna()
            elif operator == "IS_NOT_NULL":
                selected = column.notna()
            elif operator == "BETWEEN" and isinstance(value, (list, tuple)) and len(value) == 2:
                selected = column.between(value[0], value[1], inclusive="both")
            else:
                raise ValueError("Source filter operator is unsupported")
        except (TypeError, ValueError) as exc:
            raise ValueError("Source filter could not be applied") from exc
        mask &= selected.fillna(False).astype(bool)
    return table.filter(pa.array(mask.to_numpy(dtype=bool)))


class _ArtifactLineagePublicationError(RuntimeError):
    """A table materialized, but its durable lineage could not be committed."""


@dataclass(frozen=True)
class DataOperationExecutionResult:
    result_table_ids: tuple[str, ...]
    failed_steps: tuple[FailedOperationStep, ...] = ()


class DataOperationExecutor:
    def __init__(
        self,
        workspace,
        loader_resolver: LoaderResolver | None = None,
    ):
        self._workspace = workspace
        self._loader_resolver = loader_resolver or self._resolve_live_loader
        capabilities = workspace.storage_capabilities
        self._artifact_ledger = (
            ArtifactLedger.for_workspace(workspace)
            if capabilities.durable and capabilities.supports_durable_artifacts
            else None
        )

    def execute(self, operation: DataOperation) -> DataOperationExecutionResult:
        if operation.status != DataOperationStatus.RUNNING:
            raise ValueError(f"Data operation is not running: {operation.id}")
        if operation.selected_plan_id is None:
            raise ValueError("Running data operation requires selected_plan_id")
        plan = next(
            item for item in operation.plans
            if item.id == operation.selected_plan_id
        )

        published = self._find_published_results(operation.id, plan.plan_hash)
        used_names = set(self._workspace.list_tables())
        result_table_ids: list[str] = []
        failed_steps: list[FailedOperationStep] = []
        for step_index, step in enumerate(plan.steps):
            try:
                if step_index in published:
                    table_name = published[step_index]
                    self._record_load_artifact(
                        table_name,
                        step,
                        operation_id=operation.id,
                        plan_hash=plan.plan_hash,
                        step_index=step_index,
                    )
                    result_table_ids.append(table_name)
                    continue

                table_name = self._allocate_table_name(step.display_name, used_names)
                used_names.add(table_name)
                result_table_ids.append(self._publish_connector_query(
                    table_name,
                    step,
                    operation_id=operation.id,
                    plan_hash=plan.plan_hash,
                    step_index=step_index,
                ))
            except Exception as exc:
                lineage_failure = isinstance(exc, _ArtifactLineagePublicationError)
                logger.exception(
                    "Data operation %s failed to %s step %d (%s)",
                    operation.id,
                    "record lineage for" if lineage_failure else "load",
                    step_index,
                    step.display_name,
                )
                failed_steps.append(FailedOperationStep(
                    step_index=step_index,
                    display_name=step.display_name,
                    error=OperationError(
                        code=(
                            "artifact_lineage_error"
                            if lineage_failure
                            else "connector_error"
                        ),
                        message=(
                            f"{step.display_name} was loaded, but its durable lineage "
                            "could not be recorded."
                            if lineage_failure
                            else f"{step.display_name} could not be loaded."
                        ),
                    ),
                ))
        return DataOperationExecutionResult(
            tuple(result_table_ids),
            tuple(failed_steps),
        )

    def _publish_connector_query(
        self,
        table_name: str,
        step: ConnectorQueryStep,
        *,
        operation_id: str,
        plan_hash: str,
        step_index: int,
    ) -> str:
        loader = self._loader_resolver(step.source_id)
        import_options = self._build_import_options(step)
        fetch_options = dict(import_options)
        filters = fetch_options.get("source_filters")
        requested_columns = fetch_options.get("columns")
        if filters and isinstance(requested_columns, list):
            filter_columns = [
                item.get("column")
                for item in filters
                if isinstance(item, Mapping)
                and isinstance(item.get("column"), str)
            ]
            fetch_options["columns"] = list(dict.fromkeys([
                *requested_columns,
                *filter_columns,
            ]))
        table = loader.fetch_data_as_arrow(
            source_table=step.source_table,
            import_options=fetch_options,
        )
        if not isinstance(table, pa.Table):
            raise TypeError("Connector fetch_data_as_arrow must return pyarrow.Table")
        table = _apply_source_filters_locally(table, filters)
        table = apply_import_projection(table, import_options)
        if step.query.limit is not None and table.num_rows > step.query.limit:
            table = table.slice(0, step.query.limit)

        metadata = self._workspace.write_parquet_from_arrow(
            table,
            table_name,
            source_info={
                "loader_type": loader.__class__.__name__,
                "loader_params": loader.get_safe_params(),
                "source_table": step.source_table,
                "import_options": {
                    **import_options,
                    "data_operation": {
                        "operation_id": operation_id,
                        "plan_hash": plan_hash,
                        "step_index": step_index,
                        "source_id": step.source_id,
                        "table_key": step.table_key,
                        "step": step.to_dict(),
                    },
                },
            },
        )
        # Parity with ExternalDataLoader.ingest_to_workspace: without this the
        # published table carries no source description or column descriptions.
        try:
            source_meta = loader.get_column_types(step.source_table)
            if source_meta:
                _merge_source_metadata(metadata, source_meta)
                self._workspace.add_table_metadata(metadata)
        except Exception:
            logger.debug("Metadata enrichment skipped for %s", table_name, exc_info=True)
        self._record_load_artifact(
            metadata.name,
            step,
            operation_id=operation_id,
            plan_hash=plan_hash,
            step_index=step_index,
            metadata=metadata,
        )
        return metadata.name

    def _record_load_artifact(
        self,
        table_name: str,
        step: ConnectorQueryStep,
        *,
        operation_id: str,
        plan_hash: str,
        step_index: int,
        metadata: TableMetadata | None = None,
    ) -> ArtifactNode | None:
        if self._artifact_ledger is None:
            return None

        try:
            table_metadata = metadata or self._workspace.get_table_metadata(table_name)
            if table_metadata is None:
                raise ValueError(f"Published table metadata is missing: {table_name}")
            if not isinstance(table_metadata.import_options, dict):
                raise ValueError(f"Published table provenance is missing: {table_name}")
            provenance = table_metadata.import_options.get("data_operation")
            if not isinstance(provenance, dict):
                raise ValueError(f"Data operation provenance is missing: {table_name}")

            expected_provenance = {
                "operation_id": operation_id,
                "plan_hash": plan_hash,
                "step_index": step_index,
                "source_id": step.source_id,
                "table_key": step.table_key,
            }
            for key, expected in expected_provenance.items():
                if provenance.get(key) != expected:
                    raise ValueError(
                        f"Published table provenance field {key!r} does not match"
                    )

            serialized_step = step.to_dict()
            stored_step = provenance.get("step")
            if stored_step is not None and stored_step != serialized_step:
                raise ValueError("Published table step snapshot does not match selected plan")

            content_hash, schema_fingerprint = parquet_artifact_hashes(
                self._workspace,
                table_metadata,
            )
            artifact = ArtifactNode(
                artifact_type=ArtifactType.LOAD,
                identity_id=self._workspace.identity_id,
                workspace_id=self._workspace.workspace_id,
                origin_id=self._load_origin_id(
                    operation_id,
                    plan_hash,
                    step_index,
                ),
                parent_ids=(),
                content_hash=content_hash,
                schema_fingerprint=schema_fingerprint,
                execution={
                    "kind": step.kind,
                    "operation_id": operation_id,
                    "plan_hash": plan_hash,
                    "step_index": step_index,
                    "step": serialized_step,
                    "output": {
                        "table_id": table_metadata.name,
                        "filename": table_metadata.filename,
                    },
                },
                created_at=(
                    table_metadata.created_at
                    if table_metadata.created_at.tzinfo is not None
                    else table_metadata.created_at.replace(tzinfo=timezone.utc)
                ),
            )

            stored_artifact_id = provenance.get("artifact_id")
            if stored_artifact_id not in (None, artifact.artifact_id):
                raise ArtifactConflictError(
                    f"Published table points to conflicting artifact {stored_artifact_id!r}"
                )
            recorded = self._artifact_ledger.record(artifact)

            if stored_step != serialized_step or stored_artifact_id != recorded.artifact_id:
                updated_options = dict(table_metadata.import_options)
                updated_options["artifact_id"] = recorded.artifact_id
                updated_provenance = dict(provenance)
                updated_provenance["step"] = serialized_step
                updated_provenance["artifact_id"] = recorded.artifact_id
                updated_options["data_operation"] = updated_provenance
                table_metadata.import_options = updated_options
                self._workspace.add_table_metadata(table_metadata)
            return recorded
        except Exception as exc:
            raise _ArtifactLineagePublicationError(
                f"Could not record lineage for table {table_name!r}"
            ) from exc

    @staticmethod
    def _load_origin_id(
        operation_id: str,
        plan_hash: str,
        step_index: int,
    ) -> str:
        return (
            f"data-operation/{operation_id}/plan/{plan_hash}/step/{step_index}"
        )

    def _find_published_results(
        self,
        operation_id: str,
        plan_hash: str,
    ) -> dict[int, str]:
        matches: dict[int, str] = {}
        for table_name in self._workspace.list_tables():
            metadata = self._workspace.get_table_metadata(table_name)
            provenance = (
                metadata.import_options.get("data_operation")
                if metadata is not None and isinstance(metadata.import_options, dict)
                else None
            )
            if not isinstance(provenance, dict):
                continue
            if (
                provenance.get("operation_id") == operation_id
                and provenance.get("plan_hash") == plan_hash
                and isinstance(provenance.get("step_index"), int)
            ):
                matches[provenance["step_index"]] = table_name
        return matches

    @staticmethod
    def _build_import_options(step: ConnectorQueryStep) -> dict:
        options: dict = {}
        if step.query.limit is not None:
            options["size"] = step.query.limit
        if step.query.filters:
            options["source_filters"] = [item.to_dict() for item in step.query.filters]
        if step.query.columns:
            options["columns"] = list(step.query.columns)
        if step.query.order_by:
            options["sort_columns"] = [item.column for item in step.query.order_by]
            options["sort_order"] = step.query.order_by[0].direction
        return options

    @staticmethod
    def _allocate_table_name(requested_name: str, used: set[str]) -> str:
        base = sanitize_table_name(requested_name)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _resolve_live_loader(source_id: str) -> ExternalDataLoader:
        from data_formulator.data_connector import resolve_live_loader

        return resolve_live_loader(source_id)
