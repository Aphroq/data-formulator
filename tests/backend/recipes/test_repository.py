from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.repository import (
    RecipeIntegrityError,
    RecipeNotFoundError,
    RecipeRepository,
    RecipeScopeError,
    RecipeVersionStatus,
)


pytestmark = [pytest.mark.backend]


def test_repository_factory_uses_the_shared_automation_database(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path / "data-home"))

    repository = RecipeRepository.for_data_home()

    assert repository.database_path == (
        tmp_path / "data-home" / "automation" / "automation.db"
    ).resolve()


def test_repository_saves_and_reopens_draft_without_copying_recipe_json(
    tmp_path,
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "home" / "automation" / "automation.db"
    repository = RecipeRepository(database_path)

    first = repository.save_draft(recipe_workspace, compiled_recipe)
    second = repository.save_draft(recipe_workspace, compiled_recipe)
    reopened = RecipeRepository(database_path)
    restored = reopened.load_version(
        recipe_workspace,
        compiled_recipe.spec.version_id,
    )

    assert first == second
    assert first.status is RecipeVersionStatus.DRAFT
    assert restored.compiled == compiled_recipe
    assert restored.version == first
    assert reopened.list_recipes(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
    )[0].recipe_id == compiled_recipe.spec.recipe_id

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(recipe_versions)")
        }
        assert "recipe_json" not in columns
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute(
            "PRAGMA foreign_key_list(recipe_versions)"
        ).fetchall()


def test_repository_scopes_every_version_lookup(
    tmp_path,
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    repository.save_draft(recipe_workspace, compiled_recipe)
    other_workspace = Workspace(
        "user:bob",
        root_dir=tmp_path / "other-workspaces",
        workspace_id="ws-2",
    )

    with pytest.raises(RecipeNotFoundError):
        repository.get_version(
            other_workspace.identity_id,
            other_workspace.workspace_id,
            compiled_recipe.spec.version_id,
        )
    with pytest.raises(RecipeNotFoundError):
        repository.load_version(
            other_workspace,
            compiled_recipe.spec.version_id,
        )
    with pytest.raises(RecipeScopeError):
        repository.save_draft(other_workspace, compiled_recipe)


def test_idempotent_old_version_retry_does_not_revert_recipe_catalog_metadata(
    tmp_path,
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    repository.save_draft(recipe_workspace, compiled_recipe)
    renamed = CompiledRecipe(
        spec=replace(
            compiled_recipe.spec,
            name="Current orders recipe",
            description="The current description.",
        ),
        workflow_markdown="# Current orders recipe\n",
    )

    repository.save_draft(recipe_workspace, renamed)
    repository.save_draft(recipe_workspace, compiled_recipe)

    stored = repository.list_recipes(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
    )[0]
    assert stored.name == "Current orders recipe"
    assert stored.description == "The current description."


def test_repository_detects_artifact_manifest_divergence(
    tmp_path,
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    version = repository.save_draft(recipe_workspace, compiled_recipe)

    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(
            "UPDATE recipe_versions SET manifest_hash = ? WHERE version_id = ?",
            ("sha256:" + "0" * 64, version.version_id),
        )

    with pytest.raises(RecipeIntegrityError, match="artifact reference"):
        repository.load_version(recipe_workspace, version.version_id)
