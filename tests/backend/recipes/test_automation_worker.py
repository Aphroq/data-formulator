from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

import pyarrow as pa
import pytest

from data_formulator.automation.models import AutomationRunStatus
from data_formulator.automation.repository import (
    AutomationLeaseError,
    AutomationRepository,
)
from data_formulator.automation.worker import (
    AutomationWorker,
    AutomationWorkerDisabledError,
    AutomationWorkerLeaseLostError,
)
from data_formulator.datalake.workspace import sanitize_identity_dirname
from data_formulator.datalake.workspace_manager import WorkspaceManager
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.openers import LocalWorkspaceOpener
from data_formulator.recipes.repository import RecipeRepository
from data_formulator.recipes.service import RecipeService
from data_formulator.security.code_signing import CodeSigningConfigurationError


pytestmark = [pytest.mark.backend]


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> None:
        self.current += timedelta(**kwargs)


class _WorkerLoader:
    def __init__(self, *, drift: bool = False) -> None:
        self._drift = drift

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        amounts = ["30", "40"] if self._drift else [30, 40]
        return pa.table({"region": ["west", "east"], "amount": amounts})

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


class _TimeoutLoader(_WorkerLoader):
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        raise TimeoutError("password=do-not-persist connection timed out")


class _ConnectorOpener:
    def __init__(self, *loaders) -> None:
        self._loaders = iter(loaders)
        self.calls: list[tuple[str, str]] = []

    def open(self, identity_id: str, source_id: str):
        self.calls.append((identity_id, source_id))
        return next(self._loaders)


class _CancellingLoader(_WorkerLoader):
    def __init__(self, repository: AutomationRepository, run_id: str) -> None:
        super().__init__()
        self._repository = repository
        self._run_id = run_id

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        self._repository.request_run_cancel(
            "user:alice",
            "ws-1",
            self._run_id,
        )
        return super().fetch_data_as_arrow(source_table, import_options)


def _copy_workspace_into_data_home(source, data_home: Path):
    workspace_root = (
        data_home
        / "users"
        / sanitize_identity_dirname(source.identity_id)
        / "workspaces"
    )
    manager = WorkspaceManager(workspace_root)
    manager.create_workspace(source.workspace_id)
    target = manager.open_workspace(source.workspace_id, source.identity_id)
    shutil.copytree(
        source.confined_root.root,
        target.confined_root.root,
        dirs_exist_ok=True,
    )
    return manager.open_workspace(source.workspace_id, source.identity_id)


def _publish_version(
    repository: RecipeRepository,
    workspace,
    executable_recipe: CompiledRecipe,
):
    draft = repository.save_draft(workspace, executable_recipe)
    result = RecipeService(repository).dry_run(
        workspace,
        draft.version_id,
        parameter_values={},
        loader_resolver=lambda _source_id: _WorkerLoader(),
    )
    assert result.reference is not None
    return RecipeService(repository).publish(workspace, draft.version_id)


def _seed_queued_run(tmp_path, recipe_workspace, executable_recipe):
    data_home = tmp_path / "data-home"
    workspace = _copy_workspace_into_data_home(recipe_workspace, data_home)
    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, workspace, executable_recipe)
    clock = _MutableClock(datetime(2026, 8, 20, 9, tzinfo=timezone.utc))
    run_ids = iter((UUID("1" * 32), UUID("2" * 32)))
    lease_tokens = iter(("lease-1", "lease-2", "lease-3"))
    automation = AutomationRepository(
        database_path,
        clock=clock,
        id_factory=lambda: next(run_ids),
        token_factory=lambda: next(lease_tokens),
    )
    schedule = automation.create_schedule(
        identity_id=workspace.identity_id,
        workspace_id=workspace.workspace_id,
        version_id=published.version_id,
        name="Daily regional totals",
        cron_expression="0 9 * * *",
        timezone_name="UTC",
        next_run_at=clock.current + timedelta(days=1),
        schedule_id="sch_" + "a" * 32,
    )
    queued = automation.enqueue_scheduled_run(
        workspace.identity_id,
        workspace.workspace_id,
        schedule.schedule_id,
        scheduled_for=clock.current,
    )
    return data_home, workspace, recipes, automation, clock, schedule, queued


def _worker(
    data_home: Path,
    recipes: RecipeRepository,
    automation: AutomationRepository,
    clock: _MutableClock,
    connector_opener,
    *,
    attempt_ids=("a", "b", "c"),
) -> AutomationWorker:
    ids = iter(UUID(character * 32) for character in attempt_ids)
    return AutomationWorker(
        automation,
        recipes,
        LocalWorkspaceOpener(data_home),
        connector_opener,
        worker_id="worker-a",
        enabled=True,
        clock=clock,
        lease_duration=timedelta(seconds=30),
        retry_delays=(timedelta(seconds=5), timedelta(seconds=30)),
        attempt_id_factory=lambda: next(ids),
    )


def _read_attempt(workspace, run_id: str) -> tuple[dict, bytes]:
    run_dir = workspace.confined_root.resolve(
        f"artifacts/recipe-runs/{run_id}"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    persisted = b"\n".join(
        path.read_bytes() for path in run_dir.rglob("*") if path.is_file()
    )
    return manifest, persisted


def test_worker_refuses_disabled_or_unsigned_execution_before_claim(
    monkeypatch,
) -> None:
    automation = Mock()
    disabled = AutomationWorker(
        automation,
        Mock(),
        Mock(),
        Mock(),
        worker_id="worker-a",
    )

    with pytest.raises(AutomationWorkerDisabledError, match="disabled"):
        disabled.run_once()
    automation.claim_next_run.assert_not_called()

    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    unsigned = AutomationWorker(
        automation,
        Mock(),
        Mock(),
        Mock(),
        worker_id="worker-a",
        enabled=True,
    )
    with pytest.raises(CodeSigningConfigurationError, match="stable"):
        unsigned.run_once()
    automation.claim_next_run.assert_not_called()


def test_worker_returns_none_when_no_run_is_available() -> None:
    automation = Mock()
    automation.claim_next_run.return_value = None
    workspace_opener = Mock()
    worker = AutomationWorker(
        automation,
        Mock(),
        workspace_opener,
        Mock(),
        worker_id="worker-a",
        enabled=True,
    )

    assert worker.run_once() is None
    workspace_opener.open.assert_not_called()


def test_worker_factory_resolves_one_absolute_data_home(tmp_path) -> None:
    data_home = tmp_path / "relative-data-home"
    data_home.mkdir()

    worker = AutomationWorker.for_data_home(
        data_home,
        worker_id="worker-a",
        connector_opener=Mock(),
    )

    assert worker.data_home == data_home.resolve()
    assert worker.database_path == (
        data_home.resolve() / "automation" / "automation.db"
    )

    other_database = tmp_path / "other" / "automation.db"
    with pytest.raises(ValueError, match="share one database path"):
        AutomationWorker(
            AutomationRepository(worker.database_path),
            RecipeRepository(other_database),
            LocalWorkspaceOpener(data_home),
            Mock(),
            worker_id="worker-b",
        )


def test_worker_executes_an_archived_fixed_version_without_request_or_llm(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    (
        data_home,
        workspace,
        recipes,
        automation,
        clock,
        schedule,
        queued,
    ) = _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    automation.set_schedule_enabled(
        workspace.identity_id,
        workspace.workspace_id,
        schedule.schedule_id,
        enabled=False,
    )
    recipes.archive_version(workspace, queued.version_id)
    connectors = _ConnectorOpener(_WorkerLoader())
    worker = _worker(data_home, recipes, automation, clock, connectors)

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        finished = worker.run_once()

    assert finished is not None
    assert finished.status is AutomationRunStatus.SUCCEEDED
    assert finished.run_id == queued.run_id
    assert finished.attempt_count == 1
    assert finished.artifact_run_id == "run_" + "a" * 32
    assert finished.artifact_run_id != finished.run_id
    assert finished.artifact_path == (
        "artifacts/recipe-runs/" + finished.artifact_run_id
    )
    assert connectors.calls == [(workspace.identity_id, "warehouse")]
    manifest, _persisted = _read_attempt(workspace, finished.artifact_run_id)
    assert manifest["kind"] == "automation"
    assert manifest["status"] == "succeeded"
    assert manifest["version_id"] == queued.version_id


def test_worker_maps_schema_drift_to_needs_review_without_retry(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(_WorkerLoader(drift=True)),
    )

    finished = worker.run_once()

    assert finished is not None
    assert finished.status is AutomationRunStatus.NEEDS_REVIEW
    assert finished.attempt_count == 1
    assert finished.error_code == "schema_drift"
    assert finished.artifact_run_id == "run_" + "a" * 32
    assert automation.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    ) is None
    manifest, _persisted = _read_attempt(workspace, finished.artifact_run_id)
    assert manifest["status"] == "needs_review"
    assert manifest["error"]["code"] == "schema_drift"
    assert finished.run_id == queued.run_id


def test_worker_retries_only_safe_transient_connector_failures(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, _queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    connectors = _ConnectorOpener(_TimeoutLoader(), _WorkerLoader())
    worker = _worker(data_home, recipes, automation, clock, connectors)

    retry = worker.run_once()

    assert retry is not None
    assert retry.status is AutomationRunStatus.QUEUED
    assert retry.attempt_count == 1
    assert retry.available_at == "2026-08-20T09:00:05.000000Z"
    assert retry.error_code == "DB_CONNECTION_FAILED"
    assert retry.error_message == "Data source connection timed out"
    assert retry.artifact_run_id is None
    first_manifest, persisted = _read_attempt(workspace, "run_" + "a" * 32)
    assert first_manifest["status"] == "failed"
    assert first_manifest["error"]["code"] == "connector_error"
    assert b"password=do-not-persist" not in persisted

    assert worker.run_once() is None
    clock.advance(seconds=5)
    succeeded = worker.run_once()

    assert succeeded is not None
    assert succeeded.status is AutomationRunStatus.SUCCEEDED
    assert succeeded.attempt_count == 2
    assert succeeded.artifact_run_id == "run_" + "b" * 32


def test_worker_stops_after_three_transient_attempts_and_keeps_final_artifact(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, _queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(_TimeoutLoader(), _TimeoutLoader(), _TimeoutLoader()),
    )

    first = worker.run_once()
    assert first is not None and first.status is AutomationRunStatus.QUEUED
    clock.advance(seconds=5)
    second = worker.run_once()
    assert second is not None and second.status is AutomationRunStatus.QUEUED
    clock.advance(seconds=30)
    final = worker.run_once()

    assert final is not None
    assert final.status is AutomationRunStatus.FAILED
    assert final.attempt_count == 3
    assert final.error_code == "DB_CONNECTION_FAILED"
    assert final.artifact_run_id == "run_" + "c" * 32
    manifest, persisted = _read_attempt(workspace, final.artifact_run_id)
    assert manifest["status"] == "failed"
    assert b"password=do-not-persist" not in persisted
    assert automation.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    ) is None


def test_worker_maps_sqlite_busy_to_a_bounded_retry(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    monkeypatch,
) -> None:
    data_home, _workspace, recipes, automation, clock, _schedule, _queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    monkeypatch.setattr(
        recipes,
        "load_version",
        Mock(side_effect=sqlite3.OperationalError("database is locked")),
    )
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(),
    )

    retry = worker.run_once()

    assert retry is not None
    assert retry.status is AutomationRunStatus.QUEUED
    assert retry.error_code == "SQLITE_BUSY"
    assert retry.error_message == "Automation storage is temporarily busy."
    assert retry.available_at == "2026-08-20T09:00:05.000000Z"


def test_worker_cancels_with_an_immutable_boundary_artifact(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(_CancellingLoader(automation, queued.run_id)),
    )

    cancelled = worker.run_once()

    assert cancelled is not None
    assert cancelled.status is AutomationRunStatus.CANCELLED
    assert cancelled.cancel_requested_at is not None
    assert cancelled.error_code is None
    assert cancelled.artifact_run_id == "run_" + "a" * 32
    manifest, _persisted = _read_attempt(workspace, cancelled.artifact_run_id)
    assert manifest["status"] == "cancelled"
    assert manifest["error"] is None
    events = json.loads("[" + ",".join(
        (workspace.confined_root.resolve(cancelled.artifact_path) / "events.jsonl")
        .read_text("utf-8")
        .splitlines()
    ) + "]")
    assert [event["status"] for event in events] == ["started", "succeeded"]


def test_worker_never_finalizes_after_lease_fencing_loss(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    monkeypatch,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    original_renew = automation.renew_run_lease
    renewals = 0

    def lose_second_renewal(*args, **kwargs):
        nonlocal renewals
        renewals += 1
        if renewals == 2:
            raise AutomationLeaseError("Worker lease fencing token is stale")
        return original_renew(*args, **kwargs)

    monkeypatch.setattr(automation, "renew_run_lease", lose_second_renewal)
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(_WorkerLoader()),
    )

    with pytest.raises(AutomationWorkerLeaseLostError, match="lease"):
        worker.run_once()

    current = automation.get_run(
        workspace.identity_id,
        workspace.workspace_id,
        queued.run_id,
    )
    assert current.status is AutomationRunStatus.RUNNING
    attempt_dir = workspace.confined_root.resolve(
        "artifacts/recipe-runs/run_" + "a" * 32
    )
    assert attempt_dir.is_dir()
    assert not (attempt_dir / "manifest.json").exists()
