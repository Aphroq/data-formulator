# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""One-shot, request-independent execution for one durable Automation Run."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from data_formulator.automation.models import (
    AutomationRunStatus,
    StoredAutomationRun,
    validate_run_id,
)
from data_formulator.automation.repository import (
    AutomationRepository,
    AutomationStateError,
)
from data_formulator.recipes.executor import (
    RecipeExecutionAborted,
    RecipeExecutionError,
    RecipeExecutionResult,
    RecipeExecutor,
)
from data_formulator.recipes.openers import (
    ExplicitConnectorOpener,
    LocalWorkspaceOpener,
    WorkspaceOpenError,
)
from data_formulator.recipes.repository import (
    RecipeRepository,
    RecipeRepositoryError,
    RecipeVersionStatus,
)
from data_formulator.recipes.run_store import (
    RecipeRunKind,
    RecipeRunReference,
    RecipeRunStatus,
)
from data_formulator.security.code_signing import (
    CodeSigningConfigurationError,
    require_stable_code_signing,
)


Clock = Callable[[], datetime]
AttemptIdFactory = Callable[[], UUID]
EnabledCheck = Callable[[], bool]


class AutomationWorkerError(RuntimeError):
    """Base class for one-shot Worker orchestration failures."""


class AutomationWorkerDisabledError(AutomationWorkerError):
    """Automation is disabled and queue state must remain untouched."""


class AutomationWorkerLeaseLostError(AutomationWorkerError):
    """The attempt lost its fenced lease and may not commit terminal state."""


@dataclass(frozen=True, slots=True)
class _WorkerFailure:
    code: str
    message: str
    retryable: bool = False


class AutomationWorker:
    """Claim and execute at most one Run without Flask request state."""

    DEFAULT_LEASE_DURATION = timedelta(seconds=30)
    DEFAULT_RETRY_DELAYS = (
        timedelta(seconds=5),
        timedelta(seconds=30),
    )

    def __init__(
        self,
        repository: AutomationRepository,
        recipe_repository: RecipeRepository,
        workspace_opener: LocalWorkspaceOpener,
        connector_opener: ExplicitConnectorOpener,
        *,
        worker_id: str,
        enabled: bool | EnabledCheck = False,
        clock: Clock | None = None,
        lease_duration: timedelta = DEFAULT_LEASE_DURATION,
        retry_delays: Sequence[timedelta] = DEFAULT_RETRY_DELAYS,
        attempt_id_factory: AttemptIdFactory | None = None,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id cannot be empty")
        if (
            not isinstance(lease_duration, timedelta)
            or lease_duration <= timedelta(0)
        ):
            raise ValueError("lease_duration must be a positive timedelta")
        delays = tuple(retry_delays)
        if not delays or any(
            not isinstance(delay, timedelta) or delay < timedelta(0)
            for delay in delays
        ):
            raise ValueError("retry_delays must contain non-negative timedeltas")
        if isinstance(enabled, bool):
            enabled_check: EnabledCheck = lambda: enabled
        elif callable(enabled):
            enabled_check = enabled
        else:
            raise TypeError("enabled must be a bool or callable")

        self._repository = repository
        self._recipe_repository = recipe_repository
        self._workspace_opener = workspace_opener
        self._connector_opener = connector_opener
        self._worker_id = worker_id.strip()
        self._enabled = enabled_check
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lease_duration = lease_duration
        self._retry_delays = delays
        self._attempt_id_factory = attempt_id_factory or uuid4
        self._validate_database_paths()

    @classmethod
    def for_data_home(
        cls,
        data_home: Path | str,
        *,
        worker_id: str,
        enabled: bool | EnabledCheck = False,
        storage_backend: str = "local",
        connector_opener: ExplicitConnectorOpener | None = None,
        **kwargs: Any,
    ) -> "AutomationWorker":
        resolved_home = Path(data_home).resolve()
        database_path = resolved_home / "automation" / "automation.db"
        return cls(
            AutomationRepository(database_path),
            RecipeRepository(database_path),
            LocalWorkspaceOpener(
                resolved_home,
                storage_backend=storage_backend,
            ),
            connector_opener or ExplicitConnectorOpener(),
            worker_id=worker_id,
            enabled=enabled,
            **kwargs,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        worker_id: str,
        **kwargs: Any,
    ) -> "AutomationWorker":
        from data_formulator.datalake.workspace import get_data_formulator_home

        if not _automation_enabled_from_environment():
            raise AutomationWorkerDisabledError(
                "Automation Worker is disabled by AUTOMATION_ENABLED."
            )
        require_stable_code_signing()
        return cls.for_data_home(
            get_data_formulator_home(),
            worker_id=worker_id,
            enabled=True,
            storage_backend=os.getenv("WORKSPACE_BACKEND", "local"),
            **kwargs,
        )

    @property
    def database_path(self) -> Path:
        return Path(self._repository.database_path).resolve()

    @property
    def data_home(self) -> Path:
        return Path(self._workspace_opener.data_home).resolve()

    def run_once(self) -> StoredAutomationRun | None:
        """Claim, execute, and persist at most one logical Run."""
        if self._enabled() is not True:
            raise AutomationWorkerDisabledError(
                "Automation Worker is disabled."
            )
        # This check deliberately precedes claim so configuration failures do
        # not consume an attempt or strand a leased Run.
        require_stable_code_signing()
        claimed = self._repository.claim_next_run(
            worker_id=self._worker_id,
            lease_duration=self._lease_duration,
        )
        if claimed is None:
            return None
        if claimed.lease_token is None:
            raise AutomationWorkerLeaseLostError(
                "Claimed Automation Run has no fenced lease token."
            )

        try:
            attempt_run_id = self._new_attempt_run_id()
            workspace = self._workspace_opener.open(
                claimed.identity_id,
                claimed.workspace_id,
            )
            loaded = self._recipe_repository.load_version(
                workspace,
                claimed.version_id,
            )
            if loaded.version.status not in {
                RecipeVersionStatus.PUBLISHED,
                RecipeVersionStatus.ARCHIVED,
            }:
                raise ValueError(
                    "Queued Run does not reference an executable RecipeVersion"
                )
            executor = RecipeExecutor(
                workspace,
                loader_resolver=lambda source_id: self._connector_opener.open(
                    claimed.identity_id,
                    source_id,
                ),
            )
            execution = executor.execute(
                loaded.compiled.spec,
                parameter_values={},
                kind=RecipeRunKind.AUTOMATION,
                run_id=attempt_run_id,
                checkpoint=self._checkpoint(claimed),
            )
        except RecipeExecutionAborted as exc:
            raise AutomationWorkerLeaseLostError(
                "Automation Worker lease checkpoint failed."
            ) from exc
        except Exception as exc:
            return self._record_setup_failure(claimed, _classify_failure(exc))

        return self._record_execution(claimed, execution)

    def _checkpoint(self, claimed: StoredAutomationRun) -> Callable[[], bool]:
        lease_token = claimed.lease_token
        if lease_token is None:
            raise AutomationWorkerLeaseLostError(
                "Claimed Automation Run has no fenced lease token."
            )

        def checkpoint() -> bool:
            try:
                renewed = self._repository.renew_run_lease(
                    claimed.identity_id,
                    claimed.workspace_id,
                    claimed.run_id,
                    worker_id=self._worker_id,
                    lease_token=lease_token,
                    lease_duration=self._lease_duration,
                )
            except Exception as exc:
                # Without a successful fenced checkpoint, the attempt cannot
                # safely finalize an immutable artifact or logical Run row.
                raise RecipeExecutionAborted(
                    "Automation Worker lease checkpoint failed"
                ) from exc
            return renewed.cancel_requested_at is not None

        return checkpoint

    def _record_execution(
        self,
        claimed: StoredAutomationRun,
        execution: RecipeExecutionResult,
    ) -> StoredAutomationRun:
        reference = execution.reference
        if execution.status is RecipeRunStatus.SUCCEEDED:
            return self._finish(
                claimed,
                AutomationRunStatus.SUCCEEDED,
                reference=reference,
            )
        if execution.status is RecipeRunStatus.CANCELLED:
            return self._finish(
                claimed,
                AutomationRunStatus.CANCELLED,
                reference=reference,
            )

        error = execution.error or RecipeExecutionError(
            code="execution_error",
            exception_type="RecipeExecutionFailure",
            message="Recipe execution failed.",
        )
        error_code = error.automation_code or error.code
        error_message = error.automation_message or error.message
        if execution.status is RecipeRunStatus.NEEDS_REVIEW:
            return self._finish(
                claimed,
                AutomationRunStatus.NEEDS_REVIEW,
                reference=reference,
                error_code=error_code,
                error_message=error_message,
            )
        if (
            error.retryable
            and claimed.attempt_count < self._repository.MAX_ATTEMPTS
        ):
            return self._repository.fail_run(
                claimed.identity_id,
                claimed.workspace_id,
                claimed.run_id,
                worker_id=self._worker_id,
                lease_token=self._lease_token(claimed),
                retryable=True,
                error_code=error_code,
                error_message=error_message,
                retry_at=self._retry_at(claimed.attempt_count),
            )
        return self._finish(
            claimed,
            AutomationRunStatus.FAILED,
            reference=reference,
            error_code=error_code,
            error_message=error_message,
        )

    def _record_setup_failure(
        self,
        claimed: StoredAutomationRun,
        failure: _WorkerFailure,
    ) -> StoredAutomationRun:
        return self._repository.fail_run(
            claimed.identity_id,
            claimed.workspace_id,
            claimed.run_id,
            worker_id=self._worker_id,
            lease_token=self._lease_token(claimed),
            retryable=failure.retryable,
            error_code=failure.code,
            error_message=failure.message,
            retry_at=(
                self._retry_at(claimed.attempt_count)
                if failure.retryable
                else None
            ),
        )

    def _finish(
        self,
        claimed: StoredAutomationRun,
        status: AutomationRunStatus,
        *,
        reference: RecipeRunReference | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> StoredAutomationRun:
        artifact: dict[str, Any] = {}
        if reference is not None:
            artifact = {
                "artifact_run_id": reference.run_id,
                "artifact_path": reference.artifact_path,
                "manifest_hash": reference.manifest_hash,
                "binding_hash": reference.binding_hash,
            }
        return self._repository.finish_run(
            claimed.identity_id,
            claimed.workspace_id,
            claimed.run_id,
            worker_id=self._worker_id,
            lease_token=self._lease_token(claimed),
            status=status,
            error_code=error_code,
            error_message=error_message,
            **artifact,
        )

    def _retry_at(self, attempt_count: int) -> datetime:
        delay_index = min(max(attempt_count - 1, 0), len(self._retry_delays) - 1)
        return self._clock() + self._retry_delays[delay_index]

    def _new_attempt_run_id(self) -> str:
        value = self._attempt_id_factory()
        if not isinstance(value, UUID):
            raise TypeError("attempt_id_factory must return a UUID")
        return validate_run_id(f"run_{value.hex}")

    @staticmethod
    def _lease_token(claimed: StoredAutomationRun) -> str:
        if claimed.lease_token is None:
            raise AutomationWorkerLeaseLostError(
                "Claimed Automation Run has no fenced lease token."
            )
        return claimed.lease_token

    def _validate_database_paths(self) -> None:
        automation_path = getattr(self._repository, "database_path", None)
        recipe_path = getattr(self._recipe_repository, "database_path", None)
        workspace_home = getattr(self._workspace_opener, "data_home", None)
        if (
            isinstance(automation_path, (str, Path))
            and isinstance(recipe_path, (str, Path))
            and Path(automation_path).resolve() != Path(recipe_path).resolve()
        ):
            raise ValueError(
                "Automation and Recipe repositories must share one database path"
            )
        if (
            isinstance(automation_path, (str, Path))
            and isinstance(workspace_home, (str, Path))
            and Path(automation_path).resolve()
            != Path(workspace_home).resolve() / "automation" / "automation.db"
        ):
            raise ValueError(
                "Automation database and Workspace opener must share one data home"
            )


def _automation_enabled_from_environment() -> bool:
    return os.getenv("AUTOMATION_ENABLED", "false").strip().lower() == "true"


def _classify_failure(error: Exception) -> _WorkerFailure:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__

    for item in chain:
        if isinstance(item, sqlite3.OperationalError) and any(
            marker in str(item).lower() for marker in ("locked", "busy")
        ):
            return _WorkerFailure(
                code="SQLITE_BUSY",
                message="Automation storage is temporarily busy.",
                retryable=True,
            )
    if any(isinstance(item, WorkspaceOpenError) for item in chain):
        return _WorkerFailure(
            code="WORKSPACE_OPEN_FAILED",
            message="The Automation Workspace could not be opened.",
        )
    if any(isinstance(item, RecipeRepositoryError) for item in chain):
        return _WorkerFailure(
            code="RECIPE_VERSION_INVALID",
            message="The fixed RecipeVersion could not be verified.",
        )
    if any(isinstance(item, CodeSigningConfigurationError) for item in chain):
        return _WorkerFailure(
            code="SIGNING_CONFIGURATION_ERROR",
            message="Stable Recipe code signing is unavailable.",
        )
    if any(isinstance(item, AutomationStateError) for item in chain):
        return _WorkerFailure(
            code="AUTOMATION_STATE_INVALID",
            message="The Automation Run state is invalid.",
        )
    return _WorkerFailure(
        code="WORKER_EXECUTION_FAILED",
        message="Automation Worker execution failed.",
    )
