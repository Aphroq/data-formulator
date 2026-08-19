from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
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
from data_formulator.automation.scheduler import AutomationScheduler
from data_formulator.automation.runtime import AutomationRuntime
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


_HARD_KILL_WORKER_SCRIPT = r"""
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from data_formulator.automation.repository import AutomationRepository
from data_formulator.automation.worker import AutomationWorker
from data_formulator.recipes.openers import LocalWorkspaceOpener
from data_formulator.recipes.repository import RecipeRepository


class BlockingLoader:
    def __init__(self, marker):
        self.marker = marker

    def fetch_data_as_arrow(self, source_table, import_options):
        self.marker.write_text("started", encoding="utf-8")
        while True:
            time.sleep(0.1)

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table):
        raise NotImplementedError


class ConnectorOpener:
    def __init__(self, marker):
        self.marker = marker

    def open(self, identity_id, source_id):
        return BlockingLoader(self.marker)


data_home = Path(sys.argv[1]).resolve()
database_path = data_home / "automation" / "automation.db"
marker = data_home / "hard-kill-worker.started"


def clock():
    return datetime(2026, 8, 20, 9, tzinfo=timezone.utc)


AutomationWorker(
    AutomationRepository(database_path, clock=clock),
    RecipeRepository(database_path),
    LocalWorkspaceOpener(data_home),
    ConnectorOpener(marker),
    worker_id="hard-kill-worker",
    enabled=True,
    clock=clock,
    lease_duration=timedelta(seconds=1),
    heartbeat_interval=timedelta(milliseconds=100),
    attempt_id_factory=lambda: UUID("d" * 32),
).run_once()
"""


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


class _HeartbeatWaitingLoader(_WorkerLoader):
    def __init__(self, heartbeat_observed: threading.Event) -> None:
        super().__init__()
        self.started = threading.Event()
        self._heartbeat_observed = heartbeat_observed

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        self.started.set()
        if not self._heartbeat_observed.wait(timeout=5):
            raise AssertionError("Heartbeat was not observed during the load step")
        return super().fetch_data_as_arrow(source_table, import_options)


class _CancellingHeartbeatWaitingLoader(_WorkerLoader):
    def __init__(
        self,
        repository: AutomationRepository,
        run_id: str,
        heartbeat_after_cancel: threading.Event,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._run_id = run_id
        self._heartbeat_after_cancel = heartbeat_after_cancel
        self.cancel_requested = threading.Event()

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        self._repository.request_run_cancel(
            "user:alice",
            "ws-1",
            self._run_id,
        )
        self.cancel_requested.set()
        if not self._heartbeat_after_cancel.wait(timeout=5):
            raise AssertionError(
                "Lease was not renewed after cancellation during a long step"
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
    heartbeat_interval: timedelta | None = None,
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
        heartbeat_interval=heartbeat_interval,
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
    automation.recover_expired_runs.return_value = ()
    automation.list_runs_pending_attempt_cleanup.return_value = ()
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

    clock.advance(seconds=31)
    replacement = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(_WorkerLoader()),
        attempt_ids=("b",),
    ).run_once()

    assert replacement is not None
    assert replacement.status is AutomationRunStatus.SUCCEEDED
    assert replacement.attempt_count == 2
    assert replacement.artifact_run_id == "run_" + "b" * 32
    assert replacement.active_attempt_run_id is None
    assert replacement.cleanup_attempt_run_id is None
    assert not attempt_dir.exists()


def test_worker_recovers_an_incomplete_attempt_after_process_termination(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    marker = data_home / "hard-kill-worker.started"
    project_root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (
                str(project_root / "py-src"),
                environment.get("PYTHONPATH"),
            ),
        )
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _HARD_KILL_WORKER_SCRIPT,
            str(data_home),
        ],
        cwd=project_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                _stdout, stderr = process.communicate()
                pytest.fail(f"Hard-kill Worker exited before execution: {stderr}")
            time.sleep(0.05)
        assert marker.exists(), "Hard-kill Worker did not enter the load step"

        running = automation.get_run(
            workspace.identity_id,
            workspace.workspace_id,
            queued.run_id,
        )
        attempt_run_id = "run_" + "d" * 32
        assert running.status is AutomationRunStatus.RUNNING
        assert running.active_attempt_run_id == attempt_run_id
        attempt_dir = workspace.confined_root.resolve(
            f"artifacts/recipe-runs/{attempt_run_id}"
        )
        assert attempt_dir.is_dir()
        assert not (attempt_dir / "manifest.json").exists()

        process.terminate()
        process.wait(timeout=10)
        assert process.returncode != 0

        clock.advance(seconds=2)
        replacement = _worker(
            data_home,
            recipes,
            automation,
            clock,
            _ConnectorOpener(_WorkerLoader()),
            attempt_ids=("e",),
        ).run_once()

        assert replacement is not None
        assert replacement.status is AutomationRunStatus.SUCCEEDED
        assert replacement.attempt_count == 2
        assert replacement.artifact_run_id == "run_" + "e" * 32
        assert not attempt_dir.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_worker_renews_lease_while_a_long_step_is_still_running(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    monkeypatch,
) -> None:
    data_home, _workspace, recipes, automation, clock, _schedule, _queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    heartbeat_observed = threading.Event()
    loader = _HeartbeatWaitingLoader(heartbeat_observed)
    original_renew = automation.renew_run_lease
    original_lease_deadline = clock.current + timedelta(seconds=30)
    renewals_during_step = 0

    def observe_heartbeat(*args, **kwargs):
        nonlocal renewals_during_step
        if loader.started.is_set():
            renewals_during_step += 1
            clock.advance(seconds=10)
        renewed = original_renew(*args, **kwargs)
        if renewals_during_step >= 4:
            heartbeat_observed.set()
        return renewed

    monkeypatch.setattr(automation, "renew_run_lease", observe_heartbeat)
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(loader),
        heartbeat_interval=timedelta(milliseconds=10),
    )

    finished = worker.run_once()

    assert heartbeat_observed.is_set()
    assert clock.current > original_lease_deadline
    assert finished is not None
    assert finished.status is AutomationRunStatus.SUCCEEDED


def test_worker_does_not_finalize_after_background_heartbeat_loses_fence(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    monkeypatch,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    heartbeat_failed = threading.Event()
    loader = _HeartbeatWaitingLoader(heartbeat_failed)
    original_renew = automation.renew_run_lease

    def lose_fence_during_step(*args, **kwargs):
        if loader.started.is_set():
            heartbeat_failed.set()
            raise AutomationLeaseError("Worker lease fencing token is stale")
        return original_renew(*args, **kwargs)

    monkeypatch.setattr(
        automation,
        "renew_run_lease",
        lose_fence_during_step,
    )
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(loader),
        heartbeat_interval=timedelta(milliseconds=10),
    )

    with pytest.raises(AutomationWorkerLeaseLostError, match="lease"):
        worker.run_once()

    assert heartbeat_failed.is_set()
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


def test_worker_keeps_lease_alive_until_long_step_reaches_cancel_boundary(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    monkeypatch,
) -> None:
    data_home, workspace, recipes, automation, clock, _schedule, queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    heartbeat_after_cancel = threading.Event()
    loader = _CancellingHeartbeatWaitingLoader(
        automation,
        queued.run_id,
        heartbeat_after_cancel,
    )
    original_renew = automation.renew_run_lease

    def observe_post_cancel_renewal(*args, **kwargs):
        renewed = original_renew(*args, **kwargs)
        if loader.cancel_requested.is_set():
            heartbeat_after_cancel.set()
        return renewed

    monkeypatch.setattr(
        automation,
        "renew_run_lease",
        observe_post_cancel_renewal,
    )
    worker = _worker(
        data_home,
        recipes,
        automation,
        clock,
        _ConnectorOpener(loader),
        heartbeat_interval=timedelta(milliseconds=10),
    )

    cancelled = worker.run_once()

    assert heartbeat_after_cancel.is_set()
    assert cancelled is not None
    assert cancelled.status is AutomationRunStatus.CANCELLED
    manifest, _persisted = _read_attempt(workspace, cancelled.artifact_run_id)
    assert manifest["status"] == "cancelled"


def test_worker_rejects_a_heartbeat_that_cannot_precede_lease_expiry() -> None:
    with pytest.raises(ValueError, match="heartbeat_interval"):
        AutomationWorker(
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            worker_id="worker-a",
            enabled=True,
            lease_duration=timedelta(seconds=30),
            heartbeat_interval=timedelta(seconds=30),
        )


def test_restarted_runtime_executes_a_run_persisted_by_an_earlier_cycle(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    data_home, workspace, _recipes, automation, clock, schedule, _queued = (
        _seed_queued_run(tmp_path, recipe_workspace, executable_recipe)
    )
    with sqlite3.connect(automation.database_path) as connection:
        connection.execute("DELETE FROM runs")
        connection.execute(
            "UPDATE schedules SET next_run_at = ? WHERE schedule_id = ?",
            ("2026-08-20T09:00:00.000000Z", schedule.schedule_id),
        )

    scheduler_only_worker = Mock()
    scheduler_only_worker.run_once.return_value = None
    first_process = AutomationRuntime(
        AutomationScheduler(automation, clock=clock),
        scheduler_only_worker,
        enabled=True,
    )

    scheduled = first_process.run_cycle()

    assert len(scheduled.scheduler.runs) == 1
    persisted_run_id = scheduled.scheduler.runs[0].run_id
    scheduler_only_worker.run_once.assert_called_once_with()

    restarted_automation = AutomationRepository(
        automation.database_path,
        clock=clock,
    )
    restarted_recipes = RecipeRepository(automation.database_path)
    restarted_worker = _worker(
        data_home,
        restarted_recipes,
        restarted_automation,
        clock,
        _ConnectorOpener(_WorkerLoader()),
    )
    restarted_process = AutomationRuntime(
        AutomationScheduler(restarted_automation, clock=clock),
        restarted_worker,
        enabled=True,
    )

    completed = restarted_process.run_cycle()

    assert completed.run is not None
    assert completed.run.run_id == persisted_run_id
    assert completed.run.status is AutomationRunStatus.SUCCEEDED
    assert restarted_automation.get_run(
        workspace.identity_id,
        workspace.workspace_id,
        persisted_run_id,
    ).status is AutomationRunStatus.SUCCEEDED
