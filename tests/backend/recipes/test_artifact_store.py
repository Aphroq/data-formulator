from __future__ import annotations

import json

import pytest

from data_formulator.recipes.artifact_store import (
    RecipeArtifactConflictError,
    RecipeArtifactCorruptError,
    RecipeArtifactStore,
)
from data_formulator.recipes.compiler import CompiledRecipe


pytestmark = [pytest.mark.backend]


def test_recipe_artifact_store_publishes_and_verifies_immutable_files(
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    store = RecipeArtifactStore.for_workspace(recipe_workspace)

    reference = store.publish(compiled_recipe)
    restored = store.load(
        compiled_recipe.spec.recipe_id,
        compiled_recipe.spec.version_id,
        expected_manifest_hash=reference.manifest_hash,
    )

    assert restored.compiled == compiled_recipe
    assert restored.reference == reference
    assert reference.artifact_path.startswith("artifacts/recipes/")
    assert "scratch" not in reference.artifact_path
    version_dir = recipe_workspace.confined_root.resolve(reference.artifact_path)
    assert (version_dir / "recipe.json").read_bytes() == (
        compiled_recipe.spec.canonical_bytes()
    )
    manifest = json.loads((version_dir / "manifest.json").read_text("utf-8"))
    assert manifest["recipe_hash"] == str(compiled_recipe.spec.recipe_hash)
    assert set(manifest["files"]) == {"recipe.json", "workflow.md"}


def test_recipe_artifact_store_is_idempotent_but_rejects_same_version_changes(
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    store = RecipeArtifactStore.for_workspace(recipe_workspace)
    first = store.publish(compiled_recipe)

    assert store.publish(compiled_recipe) == first
    changed_workflow = CompiledRecipe(
        spec=compiled_recipe.spec,
        workflow_markdown="# Different workflow\n",
    )
    with pytest.raises(RecipeArtifactConflictError, match="immutable"):
        store.publish(changed_workflow)


def test_recipe_artifact_store_fails_closed_on_file_tampering(
    recipe_workspace,
    compiled_recipe: CompiledRecipe,
) -> None:
    store = RecipeArtifactStore.for_workspace(recipe_workspace)
    reference = store.publish(compiled_recipe)
    recipe_path = recipe_workspace.confined_root.resolve(
        f"{reference.artifact_path}/recipe.json"
    )
    recipe_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RecipeArtifactCorruptError, match="hash"):
        store.load(
            compiled_recipe.spec.recipe_id,
            compiled_recipe.spec.version_id,
            expected_manifest_hash=reference.manifest_hash,
        )
