from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from data_formulator.automation.models import AutomationRunStatus
from data_formulator.automation.repository import (
    AutomationLeaseError,
    AutomationRepository,
    AutomationScopeError,
    AutomationStateError,
)
from data_formulator.recipes.models import HashDigest


pytestmark = [pytest.mark.backend]


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> None:
        self.current += timedelta(**kwargs)


def _seed_repository(tmp_path, *, tokens=("lease-1", "lease-2", "lease-3")):
    clock = _MutableClock(datetime(2026, 8, 20, 9, tzinfo=timezone.utc))
    token_values = iter(tokens)
    repository = AutomationRepository(
        tmp_path / "automation.db",
        clock=clock,
        token_factory=lambda: next(token_values),
    )
    with sqlite3.connect(repository.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO recipes (
                recipe_id, identity_id, workspace_id, name, description,
                created_by, created_at, updated_at
            ) VALUES (
                'recipe-1', 'user:alice', 'ws-1', 'Recipe', '',
                'user:alice', ?, ?
            )
            """,
            (
                "2026-08-19T00:00:00.000000Z",
                "2026-08-19T00:00:00.000000Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO recipe_versions (
                version_id, recipe_id, identity_id, workspace_id,
                recipe_hash, status, artifact_path, manifest_hash,
                created_at, published_at
            ) VALUES (
                ?, 'recipe-1', 'user:alice', 'ws-1', ?, 'published',
                'recipes/recipe-1/version.json', ?, ?, ?
            )
            """,
            (
                "rv_" + "1" * 64,
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
                "2026-08-19T00:00:00.000000Z",
                "2026-08-19T01:00:00.000000Z",
            ),
        )
    schedule = repository.create_schedule(
        identity_id="user:alice",
        workspace_id="ws-1",
        version_id="rv_" + "1" * 64,
        name="Daily recipe",
        cron_expression="0 9 * * *",
        timezone_name="UTC",
        next_run_at=clock.current + timedelta(days=1),
        schedule_id="sch_" + "1" * 32,
    )
    run = repository.enqueue_scheduled_run(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
        scheduled_for=clock.current,
    )
    return repository, clock, schedule, run


def test_claim_and_renew_use_a_scoped_fenced_lease(tmp_path) -> None:
    repository, clock, _schedule, queued = _seed_repository(tmp_path)

    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )

    assert claimed is not None
    assert claimed.run_id == queued.run_id
    assert claimed.status is AutomationRunStatus.RUNNING
    assert claimed.attempt_count == 1
    assert claimed.lease_owner == "worker-a"
    assert claimed.lease_token == "lease-1"
    assert claimed.lease_expires_at == "2026-08-20T09:00:30.000000Z"
    assert repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    ) is None

    clock.advance(seconds=10)
    renewed = repository.renew_run_lease(
        "user:alice",
        "ws-1",
        queued.run_id,
        worker_id="worker-a",
        lease_token="lease-1",
        lease_duration=timedelta(seconds=45),
    )
    assert renewed.lease_expires_at == "2026-08-20T09:00:55.000000Z"

    with pytest.raises(AutomationLeaseError, match="fencing"):
        repository.renew_run_lease(
            "user:alice",
            "ws-1",
            queued.run_id,
            worker_id="worker-a",
            lease_token="wrong-token",
            lease_duration=timedelta(seconds=30),
        )


def test_expired_worker_cannot_finish_after_the_run_is_reclaimed(tmp_path) -> None:
    repository, clock, _schedule, queued = _seed_repository(tmp_path)
    first = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert first is not None
    clock.advance(seconds=31)

    second = repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    )

    assert second is not None
    assert second.run_id == first.run_id
    assert second.attempt_count == 2
    assert second.lease_token == "lease-2"
    digest = HashDigest.sha256(b"artifact")
    with pytest.raises(ValueError, match="differ from the logical"):
        repository.finish_run(
            "user:alice",
            "ws-1",
            queued.run_id,
            worker_id="worker-b",
            lease_token="lease-2",
            status=AutomationRunStatus.SUCCEEDED,
            artifact_run_id=queued.run_id,
            artifact_path="recipes/recipe-1/runs/logical-id",
            manifest_hash=digest,
            binding_hash=digest,
        )
    with pytest.raises(AutomationLeaseError, match="fencing"):
        repository.finish_run(
            "user:alice",
            "ws-1",
            queued.run_id,
            worker_id="worker-a",
            lease_token="lease-1",
            status=AutomationRunStatus.SUCCEEDED,
            artifact_run_id="run_" + "a" * 32,
            artifact_path="recipes/recipe-1/runs/attempt-a",
            manifest_hash=digest,
            binding_hash=digest,
        )

    finished = repository.finish_run(
        "user:alice",
        "ws-1",
        queued.run_id,
        worker_id="worker-b",
        lease_token="lease-2",
        status=AutomationRunStatus.SUCCEEDED,
        artifact_run_id="run_" + "b" * 32,
        artifact_path="recipes/recipe-1/runs/attempt-b",
        manifest_hash=digest,
        binding_hash=digest,
    )
    assert finished.status is AutomationRunStatus.SUCCEEDED
    assert finished.artifact_run_id != finished.run_id
    assert finished.lease_token is None


def test_expired_attempt_must_be_cleaned_before_the_run_is_reclaimed(
    tmp_path,
) -> None:
    repository, clock, _schedule, queued = _seed_repository(tmp_path)
    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    attempt_run_id = "run_" + "a" * 32

    started = repository.start_run_attempt(
        "user:alice",
        "ws-1",
        queued.run_id,
        worker_id="worker-a",
        lease_token="lease-1",
        attempt_run_id=attempt_run_id,
    )

    assert started.active_attempt_run_id == attempt_run_id
    assert started.cleanup_attempt_run_id is None
    digest = HashDigest.sha256(b"wrong-attempt")
    with pytest.raises(AutomationStateError, match="active physical attempt"):
        repository.finish_run(
            "user:alice",
            "ws-1",
            queued.run_id,
            worker_id="worker-a",
            lease_token="lease-1",
            status=AutomationRunStatus.SUCCEEDED,
            artifact_run_id="run_" + "b" * 32,
            artifact_path="artifacts/recipe-runs/run_" + "b" * 32,
            manifest_hash=digest,
            binding_hash=digest,
        )
    clock.advance(seconds=31)
    recovered = repository.recover_expired_runs()

    assert len(recovered) == 1
    assert recovered[0].status is AutomationRunStatus.QUEUED
    assert recovered[0].active_attempt_run_id is None
    assert recovered[0].cleanup_attempt_run_id == attempt_run_id
    assert repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    ) is None

    unchanged = repository.complete_run_attempt_cleanup(
        "user:alice",
        "ws-1",
        queued.run_id,
        attempt_run_id="run_" + "b" * 32,
    )
    assert unchanged.cleanup_attempt_run_id == attempt_run_id

    cleaned = repository.complete_run_attempt_cleanup(
        "user:alice",
        "ws-1",
        queued.run_id,
        attempt_run_id=attempt_run_id,
    )
    assert cleaned.cleanup_attempt_run_id is None

    reclaimed = repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    )
    assert reclaimed is not None
    assert reclaimed.run_id == queued.run_id
    assert reclaimed.attempt_count == 2


def test_queued_and_running_cancellation_never_reopen_terminal_state(
    tmp_path,
) -> None:
    repository, _clock, schedule, first = _seed_repository(tmp_path)

    cancelled = repository.request_run_cancel(
        "user:alice",
        "ws-1",
        first.run_id,
    )
    assert cancelled.status is AutomationRunStatus.CANCELLED
    assert repository.request_run_cancel(
        "user:alice",
        "ws-1",
        first.run_id,
    ) == cancelled

    second = repository.enqueue_scheduled_run(
        "user:alice",
        "ws-1",
        schedule.schedule_id,
        scheduled_for=datetime(2026, 8, 20, 10, tzinfo=timezone.utc),
    )
    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None and claimed.run_id == second.run_id
    requested = repository.request_run_cancel(
        "user:alice",
        "ws-1",
        second.run_id,
    )
    assert requested.status is AutomationRunStatus.RUNNING
    assert requested.cancel_requested_at is not None

    digest = HashDigest.sha256(b"artifact")
    with pytest.raises(AutomationStateError, match="cancellation"):
        repository.finish_run(
            "user:alice",
            "ws-1",
            second.run_id,
            worker_id="worker-a",
            lease_token="lease-1",
            status=AutomationRunStatus.SUCCEEDED,
            artifact_run_id="run_" + "a" * 32,
            artifact_path="recipes/recipe-1/runs/attempt-a",
            manifest_hash=digest,
            binding_hash=digest,
        )

    completed_cancel = repository.finish_run(
        "user:alice",
        "ws-1",
        second.run_id,
        worker_id="worker-a",
        lease_token="lease-1",
        status=AutomationRunStatus.CANCELLED,
    )
    assert completed_cancel.status is AutomationRunStatus.CANCELLED

    assert repository.request_run_cancel(
        "user:alice",
        "ws-1",
        completed_cancel.run_id,
    ) == completed_cancel


def test_retryable_failures_stop_after_three_total_attempts(tmp_path) -> None:
    repository, _clock, _schedule, run = _seed_repository(
        tmp_path,
        tokens=("lease-1", "lease-2", "lease-3"),
    )

    for attempt in (1, 2, 3):
        claimed = repository.claim_next_run(
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.attempt_count == attempt
        failed = repository.fail_run(
            "user:alice",
            "ws-1",
            run.run_id,
            worker_id="worker-a",
            lease_token=f"lease-{attempt}",
            retryable=True,
            error_code="DB_CONNECTION_FAILED",
            error_message="timeout password=do-not-store",
        )
        expected = (
            AutomationRunStatus.QUEUED
            if attempt < 3
            else AutomationRunStatus.FAILED
        )
        assert failed.status is expected

    stored = repository.get_run("user:alice", "ws-1", run.run_id)
    assert stored.attempt_count == 3
    assert stored.error_code == "DB_CONNECTION_FAILED"
    assert "do-not-store" not in (stored.error_message or "")
    assert repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    ) is None


def test_retry_at_delays_the_next_claim(tmp_path) -> None:
    repository, clock, _schedule, run = _seed_repository(tmp_path)
    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None

    retrying = repository.fail_run(
        "user:alice",
        "ws-1",
        run.run_id,
        worker_id="worker-a",
        lease_token="lease-1",
        retryable=True,
        error_code="UPSTREAM_TIMEOUT",
        error_message="The upstream request timed out.",
        retry_at=clock.current + timedelta(minutes=1),
    )

    assert retrying.status is AutomationRunStatus.QUEUED
    assert retrying.available_at == "2026-08-20T09:01:00.000000Z"
    assert repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    ) is None
    clock.advance(minutes=1)
    reclaimed = repository.claim_next_run(
        worker_id="worker-b",
        lease_duration=timedelta(seconds=30),
    )
    assert reclaimed is not None
    assert reclaimed.run_id == run.run_id
    assert reclaimed.attempt_count == 2


@pytest.mark.parametrize(
    "artifact_path",
    [
        "/absolute/path",
        "../escape",
        "recipes//attempt",
        "recipes/./attempt",
        "C:/absolute/path",
        r"recipes\attempt",
    ],
)
def test_finish_rejects_unsafe_artifact_paths(tmp_path, artifact_path) -> None:
    repository, _clock, _schedule, run = _seed_repository(tmp_path)
    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    digest = HashDigest.sha256(b"artifact")

    with pytest.raises(ValueError, match="safe relative path"):
        repository.finish_run(
            "user:alice",
            "ws-1",
            run.run_id,
            worker_id="worker-a",
            lease_token="lease-1",
            status=AutomationRunStatus.SUCCEEDED,
            artifact_run_id="run_" + "a" * 32,
            artifact_path=artifact_path,
            manifest_hash=digest,
            binding_hash=digest,
        )


@pytest.mark.parametrize(
    ("status", "error_code", "error_message"),
    [
        (AutomationRunStatus.SUCCEEDED, "unexpected", "unexpected"),
        (AutomationRunStatus.CANCELLED, "unexpected", "unexpected"),
        (AutomationRunStatus.FAILED, None, None),
        (AutomationRunStatus.NEEDS_REVIEW, None, None),
        (AutomationRunStatus.FAILED, "failure", None),
    ],
)
def test_finish_requires_status_consistent_safe_errors(
    tmp_path,
    status,
    error_code,
    error_message,
) -> None:
    repository, _clock, _schedule, run = _seed_repository(tmp_path)
    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    digest = HashDigest.sha256(b"artifact")
    artifact_fields = (
        {
            "artifact_run_id": "run_" + "a" * 32,
            "artifact_path": "recipes/recipe-1/runs/attempt-a",
            "manifest_hash": digest,
            "binding_hash": digest,
        }
        if status in {
            AutomationRunStatus.SUCCEEDED,
            AutomationRunStatus.NEEDS_REVIEW,
        }
        else {}
    )
    if status is AutomationRunStatus.CANCELLED:
        repository.request_run_cancel("user:alice", "ws-1", run.run_id)

    with pytest.raises(ValueError, match="error"):
        repository.finish_run(
            "user:alice",
            "ws-1",
            run.run_id,
            worker_id="worker-a",
            lease_token="lease-1",
            status=status,
            error_code=error_code,
            error_message=error_message,
            **artifact_fields,
        )


def test_expired_cancel_request_is_closed_and_scope_is_enforced(tmp_path) -> None:
    repository, clock, _schedule, run = _seed_repository(tmp_path)
    claimed = repository.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    repository.request_run_cancel("user:alice", "ws-1", run.run_id)
    clock.advance(seconds=31)

    recovered = repository.recover_expired_runs()

    assert len(recovered) == 1
    assert recovered[0].status is AutomationRunStatus.CANCELLED
    with pytest.raises(AutomationScopeError, match="scope"):
        repository.get_run("user:mallory", "ws-1", run.run_id)
