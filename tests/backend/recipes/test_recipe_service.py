from __future__ import annotations

from unittest.mock import patch

import pyarrow as pa
import pytest

from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.repository import (
    RecipeRepository,
    RecipeStateError,
    RecipeVersionStatus,
)
from data_formulator.recipes.run_store import RecipeRunStatus
from data_formulator.recipes.service import RecipeService
from data_formulator.security.code_signing import CodeSigningConfigurationError


pytestmark = [pytest.mark.backend]


class _ServiceLoader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": [30, 40],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


def test_service_dry_runs_saved_version_and_manual_runs_only_after_publish(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    service = RecipeService(repository)
    resolver = lambda _source_id: _ServiceLoader()

    with pytest.raises(RecipeStateError, match="published"):
        service.run_manual(
            recipe_workspace,
            draft.version_id,
            parameter_values={},
            loader_resolver=resolver,
        )

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Recipe runs must not call an LLM"),
    ):
        dry_run = service.dry_run(
            recipe_workspace,
            draft.version_id,
            parameter_values={},
            loader_resolver=resolver,
        )
        published = service.publish(
            recipe_workspace,
            draft.version_id,
        )
        manual = service.run_manual(
            recipe_workspace,
            draft.version_id,
            parameter_values={},
            loader_resolver=resolver,
        )

    assert dry_run.status is RecipeRunStatus.SUCCEEDED
    assert published.status is RecipeVersionStatus.PUBLISHED
    assert manual.status is RecipeRunStatus.SUCCEEDED
    assert manual.reference.version_id == draft.version_id


@pytest.mark.parametrize("action", ["dry_run", "publish", "run_manual"])
def test_service_requires_stable_signing_before_lifecycle_actions(
    tmp_path,
    monkeypatch,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
    action: str,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    service = RecipeService(repository)
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    with pytest.raises(CodeSigningConfigurationError, match="stable"):
        if action == "dry_run":
            service.dry_run(
                recipe_workspace,
                draft.version_id,
                parameter_values={},
                loader_resolver=lambda _source_id: _ServiceLoader(),
            )
        elif action == "publish":
            service.publish(recipe_workspace, draft.version_id)
        else:
            service.run_manual(
                recipe_workspace,
                draft.version_id,
                parameter_values={},
                loader_resolver=lambda _source_id: _ServiceLoader(),
            )
