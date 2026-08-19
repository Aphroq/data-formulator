# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace-aware orchestration for Schedule and durable Run APIs."""

from __future__ import annotations

from data_formulator.automation.models import (
    AutomationRunStatus,
    StoredAutomationRun,
    StoredSchedule,
)
from data_formulator.automation.repository import (
    AutomationRepository,
    AutomationStateError,
)
from data_formulator.recipes.binding import bind_recipe_parameters
from data_formulator.recipes.repository import (
    RecipeRepository,
    RecipeVersionStatus,
)
from data_formulator.recipes.run_store import (
    RecipeRunArtifactStore,
    RecipeRunKind,
    RecipeRunReference,
    RecipeRunStatus,
    StoredRecipeRun,
)
from data_formulator.security.code_signing import require_stable_code_signing


_ARTIFACT_STATUSES = {
    AutomationRunStatus.SUCCEEDED: RecipeRunStatus.SUCCEEDED,
    AutomationRunStatus.FAILED: RecipeRunStatus.FAILED,
    AutomationRunStatus.NEEDS_REVIEW: RecipeRunStatus.NEEDS_REVIEW,
    AutomationRunStatus.CANCELLED: RecipeRunStatus.CANCELLED,
}


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
    ) -> StoredSchedule:
        require_stable_code_signing()
        self._require_default_binding(workspace, version_id)
        return self._automation.create_schedule(
            identity_id=workspace.identity_id,
            workspace_id=workspace.workspace_id,
            version_id=version_id,
            name=name,
            cron_expression=cron_expression,
            timezone_name=timezone_name,
        )

    def enqueue_manual_run(
        self,
        workspace,
        version_id: str,
    ) -> StoredAutomationRun:
        require_stable_code_signing()
        self._require_default_binding(workspace, version_id)
        return self._automation.enqueue_manual_run(
            workspace.identity_id,
            workspace.workspace_id,
            version_id,
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

    def _require_default_binding(self, workspace, version_id: str) -> None:
        loaded = self._recipes.load_version(workspace, version_id)
        if loaded.version.status is not RecipeVersionStatus.PUBLISHED:
            raise AutomationStateError(
                "Automation requires a published RecipeVersion"
            )
        try:
            bind_recipe_parameters(loaded.compiled.spec, {})
        except (TypeError, ValueError) as exc:
            raise AutomationStateError(
                "RecipeVersion does not provide a complete default binding"
            ) from exc
