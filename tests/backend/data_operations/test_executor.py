import hashlib
from pathlib import Path

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
    LoadQueryOrder,
    OperationFilter,
)
from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.lineage import ArtifactLedger
from data_formulator.recipes.models import ArtifactType, HashDigest


class _Loader:
    def __init__(
        self,
        table: pa.Table | None = None,
        error: Exception | None = None,
        source_meta: dict | None = None,
    ):
        self.table = table
        self.error = error
        self.source_meta = source_meta
        self.calls: list[tuple[str, dict]] = []

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        self.calls.append((source_table, import_options))
        if self.error is not None:
            raise self.error
        return self.table

    def get_column_types(self, source_table: str):
        if self.source_meta is None:
            raise NotImplementedError
        return self.source_meta

    def get_safe_params(self):
        return {"host": "example.test"}


def _operation(*steps: ConnectorQueryStep) -> DataOperation:
    plan = DataOperationPlan(
        id="plan-1",
        label="Load data",
        summary="",
        steps=steps,
    )
    return DataOperation(
        id="operation-1",
        reason="Load data",
        plans=(plan,),
        status=DataOperationStatus.RUNNING,
        selected_plan_id=plan.id,
    )


def _step(display_name: str = "Recent orders", source_id: str = "warehouse"):
    return ConnectorQueryStep(
        source_id=source_id,
        table_key="public.orders",
        display_name=display_name,
        source_table="public.orders",
        source_table_name="orders",
        query=LoadQuery(
            limit=2,
            filters=(OperationFilter("region", "IN", ["west", "east"]),),
            columns=("id",),
            order_by=(LoadQueryOrder("created_at", "desc"),),
        ),
    )


def test_executor_materializes_bounded_table_with_provenance(tmp_path: Path) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    loader = _Loader(pa.table({"id": [1, 2, 3], "region": ["west", "east", "north"]}))
    executor = DataOperationExecutor(workspace, lambda _source_id: loader)
    operation = _operation(_step())

    result = executor.execute(operation)

    assert result.result_table_ids == ("recent_orders",)
    assert loader.calls == [("public.orders", {
        "size": 2,
        "source_filters": [{"column": "region", "operator": "IN", "value": ["west", "east"]}],
        "columns": ["id"],
        "sort_columns": ["created_at"],
        "sort_order": "desc",
    })]
    metadata = workspace.get_table_metadata("recent_orders")
    assert metadata is not None
    assert metadata.row_count == 2
    assert metadata.source_table == "public.orders"
    assert metadata.loader_params == {"host": "example.test"}
    assert workspace.read_data_as_df("recent_orders")["id"].tolist() == [1, 2]
    assert result.failed_steps == ()

    artifact = ArtifactLedger.for_workspace(workspace).list_nodes()[0]
    parquet_path = workspace.get_file_path(metadata.filename)
    persisted_schema = pq.ParquetFile(parquet_path).schema_arrow
    plan = operation.plans[0]
    assert artifact.artifact_type is ArtifactType.LOAD
    assert artifact.identity_id == "test-user"
    assert artifact.workspace_id == "test-user"
    assert artifact.origin_id == (
        f"data-operation/{operation.id}/plan/{plan.plan_hash}/step/0"
    )
    assert artifact.parent_ids == ()
    assert artifact.content_hash == HashDigest(
        "sha256",
        hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
    )
    assert artifact.schema_fingerprint == HashDigest.sha256(
        persisted_schema.serialize().to_pybytes()
    )
    assert artifact.to_dict()["execution"] == {
        "kind": "connector_query",
        "operation_id": operation.id,
        "plan_hash": plan.plan_hash,
        "step_index": 0,
        "step": _step().to_dict(),
        "output": {
            "table_id": "recent_orders",
            "filename": "recent_orders.parquet",
        },
    }
    provenance = metadata.import_options["data_operation"]
    assert provenance["step"] == _step().to_dict()
    assert provenance["artifact_id"] == artifact.artifact_id


def test_executor_publishes_source_descriptions(tmp_path: Path) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    loader = _Loader(
        pa.table({"id": [1]}),
        source_meta={
            "description": "Customer orders",
            "columns": [{"name": "id", "description": "Order id"}],
        },
    )
    executor = DataOperationExecutor(workspace, lambda _source_id: loader)

    executor.execute(_operation(ConnectorQueryStep(
        source_id="warehouse",
        table_key="public.orders",
        display_name="Orders",
        source_table="public.orders",
    )))

    metadata = workspace.get_table_metadata("orders")
    assert metadata is not None
    assert metadata.description == "Customer orders"
    assert [column.description for column in metadata.columns] == ["Order id"]


def test_executor_keeps_successful_tables_when_later_step_fails(tmp_path: Path) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    loaders = {
        "first": _Loader(pa.table({"id": [1]})),
        "second": _Loader(error=RuntimeError("source unavailable")),
    }
    executor = DataOperationExecutor(workspace, loaders.__getitem__)

    result = executor.execute(_operation(
        _step("Orders", "first"),
        _step("Customers", "second"),
    ))

    assert result.result_table_ids == ("orders",)
    assert workspace.list_tables() == ["orders"]
    assert len(result.failed_steps) == 1
    assert result.failed_steps[0].step_index == 1
    assert result.failed_steps[0].display_name == "Customers"
    assert result.failed_steps[0].error.code == "connector_error"
    assert len(ArtifactLedger.for_workspace(workspace).list_nodes()) == 1


def test_executor_allocates_distinct_fresh_names(tmp_path: Path) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    workspace.write_parquet_from_arrow(pa.table({"id": [0]}), "orders")
    loader = _Loader(pa.table({"id": [1]}))
    executor = DataOperationExecutor(workspace, lambda _source_id: loader)

    result = executor.execute(_operation(_step("Orders"), _step("Orders")))

    assert result.result_table_ids == ("orders_2", "orders_3")


def test_executor_recovers_published_tables_without_refetching(tmp_path: Path) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    operation = _operation(_step())
    first_loader = _Loader(pa.table({"id": [1]}))
    first_result = DataOperationExecutor(
        workspace,
        lambda _source_id: first_loader,
    ).execute(operation)
    retry_loader = _Loader(error=AssertionError("retry must not refetch"))

    retry_result = DataOperationExecutor(
        workspace,
        lambda _source_id: retry_loader,
    ).execute(operation)

    assert retry_result == first_result
    assert retry_loader.calls == []
    assert len(ArtifactLedger.for_workspace(workspace).list_nodes()) == 1


def test_executor_recovers_lineage_after_artifact_write_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    operation = _operation(_step())
    first_loader = _Loader(pa.table({"id": [1]}))
    original_record = ArtifactLedger.record

    def fail_record(_ledger, _node):
        raise OSError("artifact store unavailable")

    monkeypatch.setattr(ArtifactLedger, "record", fail_record)
    first_result = DataOperationExecutor(
        workspace,
        lambda _source_id: first_loader,
    ).execute(operation)

    assert first_result.result_table_ids == ()
    assert first_result.failed_steps[0].error.code == "artifact_lineage_error"
    assert workspace.list_tables() == ["recent_orders"]
    metadata = workspace.get_table_metadata("recent_orders")
    assert metadata.import_options["data_operation"]["step"] == _step().to_dict()
    assert "artifact_id" not in metadata.import_options["data_operation"]

    monkeypatch.setattr(ArtifactLedger, "record", original_record)
    retry_loader = _Loader(error=AssertionError("retry must not refetch"))
    retry_result = DataOperationExecutor(
        workspace,
        lambda _source_id: retry_loader,
    ).execute(operation)

    assert retry_result.result_table_ids == ("recent_orders",)
    assert retry_result.failed_steps == ()
    assert retry_loader.calls == []
    assert len(ArtifactLedger.for_workspace(workspace).list_nodes()) == 1


def test_executor_rejects_changed_published_content_without_refetching(
    tmp_path: Path,
) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    operation = _operation(_step())
    DataOperationExecutor(
        workspace,
        lambda _source_id: _Loader(pa.table({"id": [1]})),
    ).execute(operation)
    metadata = workspace.get_table_metadata("recent_orders")
    pq.write_table(pa.table({"id": [999]}), workspace.get_file_path(metadata.filename))
    retry_loader = _Loader(error=AssertionError("retry must not refetch"))

    retry_result = DataOperationExecutor(
        workspace,
        lambda _source_id: retry_loader,
    ).execute(operation)

    assert retry_result.result_table_ids == ()
    assert retry_result.failed_steps[0].error.code == "artifact_lineage_error"
    assert retry_loader.calls == []


def test_executor_rejects_tampered_step_snapshot_without_refetching(
    tmp_path: Path,
) -> None:
    workspace = Workspace("test-user", root_dir=tmp_path)
    operation = _operation(_step())
    DataOperationExecutor(
        workspace,
        lambda _source_id: _Loader(pa.table({"id": [1]})),
    ).execute(operation)
    metadata = workspace.get_table_metadata("recent_orders")
    metadata.import_options["data_operation"]["step"]["query"]["limit"] = 99
    workspace.add_table_metadata(metadata)
    retry_loader = _Loader(error=AssertionError("retry must not refetch"))

    retry_result = DataOperationExecutor(
        workspace,
        lambda _source_id: retry_loader,
    ).execute(operation)

    assert retry_result.result_table_ids == ()
    assert retry_result.failed_steps[0].error.code == "artifact_lineage_error"
    assert retry_loader.calls == []


def test_executor_keeps_ephemeral_load_interactive_without_artifact_store(
    tmp_path: Path,
) -> None:
    workspace = Workspace(
        "test-user",
        root_dir=tmp_path,
        storage_backend="ephemeral",
        durable=False,
        supports_durable_artifacts=False,
    )
    loader = _Loader(pa.table({"id": [1]}))

    result = DataOperationExecutor(
        workspace,
        lambda _source_id: loader,
    ).execute(_operation(_step()))

    assert result.result_table_ids == ("recent_orders",)
    assert result.failed_steps == ()
    assert not (workspace.confined_root.root / "artifacts").exists()
