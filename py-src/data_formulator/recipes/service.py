# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle-aware orchestration for persisted RecipeVersions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data_formulator.recipes.executor import (
    LoaderResolver,
    RecipeExecutionResult,
    RecipeExecutor,
)
from data_formulator.recipes.repository import (
    RecipeRepository,
    RecipeStateError,
    RecipeVersionStatus,
    StoredRecipeVersion,
)
from data_formulator.recipes.run_store import RecipeRunKind, RecipeRunStatus
from data_formulator.sandbox.local_sandbox import LocalSandbox


class RecipeService:
    """Execute only versions reopened from the durable Recipe repository."""

    def __init__(self, repository: RecipeRepository) -> None:
        self._repository = repository

    def dry_run(
        self,
        workspace,
        version_id: str,
        *,
        parameter_values: Mapping[str, Any],
        loader_resolver: LoaderResolver,
        sandbox: LocalSandbox | None = None,
    ) -> RecipeExecutionResult:
        loaded = self._repository.load_version(workspace, version_id)
        if loaded.version.status is not RecipeVersionStatus.DRAFT:
            raise RecipeStateError(
                "Only a draft RecipeVersion can start validation"
            )
        result = RecipeExecutor(
            workspace,
            loader_resolver,
            sandbox=sandbox,
        ).execute(
            loaded.compiled.spec,
            parameter_values=parameter_values,
            kind=RecipeRunKind.DRY_RUN,
        )
        if result.status is RecipeRunStatus.SUCCEEDED:
            if result.reference is None:  # pragma: no cover - executor invariant
                raise RecipeStateError(
                    "Successful dry run did not produce validation evidence"
                )
            self._repository.mark_validated(
                workspace,
                version_id,
                result.reference,
            )
        return result

    def publish(self, workspace, version_id: str) -> StoredRecipeVersion:
        return self._repository.publish_version(workspace, version_id)

    def run_manual(
        self,
        workspace,
        version_id: str,
        *,
        parameter_values: Mapping[str, Any],
        loader_resolver: LoaderResolver,
        sandbox: LocalSandbox | None = None,
    ) -> RecipeExecutionResult:
        loaded = self._repository.load_version(workspace, version_id)
        if loaded.version.status is not RecipeVersionStatus.PUBLISHED:
            raise RecipeStateError(
                "Only a published RecipeVersion can run manually"
            )
        return RecipeExecutor(
            workspace,
            loader_resolver,
            sandbox=sandbox,
        ).execute(
            loaded.compiled.spec,
            parameter_values=parameter_values,
            kind=RecipeRunKind.MANUAL,
        )
