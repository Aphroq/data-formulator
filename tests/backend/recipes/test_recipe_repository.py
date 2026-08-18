from __future__ import annotations

import sqlite3
from dataclasses import replace

import pyarrow as pa
import pytest

from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.binding import bind_recipe_parameters
from data_formulator.recipes.repository import (
    RecipeConflictError,
    RecipeIntegrityError,
    RecipeNotFoundError,
    RecipeRepository,
    RecipeScopeError,
    RecipeStateError,
    RecipeVersionStatus,
)
from data_formulator.recipes.executor import RecipeExecutor
from data_formulator.recipes.run_store import (
    RecipeRunArtifactStore,
    RecipeRunKind,
    RecipeRunStatus,
)


pytestmark = [pytest.mark.backend]


class _LifecycleLoader:
    def __init__(self, *, drift: bool = False):
        self.drift = drift

    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": (["30", "40"] if self.drift else [30, 40]),
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


def test_repository_factory_uses_the_shared_automation_database(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path / "data-home"))

    repository = RecipeRepository.for_data_home()

    assert repository.database_path == (
        tmp_path / "data-home" / "automation" / "automation.db"
    ).resolve()


def test_repository_migrates_existing_v1_catalog_in_place(tmp_path) -> None:
    database_path = tmp_path / "automation.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE automation_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        RecipeRepository._apply_schema_v1(connection)
        connection.execute(
            """
            INSERT INTO automation_schema_migrations (version, applied_at)
            VALUES (1, '2026-08-18T00:00:00Z')
            """
        )

    RecipeRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(recipe_versions)")
        }
        assert {
            "validation_artifact_path",
            "validation_binding_hash",
        }.issubset(columns)
        assert connection.execute(
            "SELECT version FROM automation_schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]


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
        assert {
            "validation_artifact_path",
            "validation_binding_hash",
        }.issubset(columns)
        assert connection.execute(
            "SELECT version FROM automation_schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]


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


def test_repository_validates_publishes_and_archives_with_verified_run(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    run = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _LifecycleLoader(),
    ).execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )

    validated = repository.mark_validated(
        recipe_workspace,
        draft.version_id,
        run.reference,
    )
    idempotent = repository.mark_validated(
        recipe_workspace,
        draft.version_id,
        run.reference,
    )
    published = RecipeRepository(repository.database_path).publish_version(
        recipe_workspace,
        draft.version_id,
    )
    published_again = repository.publish_version(
        recipe_workspace,
        draft.version_id,
    )
    with pytest.raises(RecipeStateError, match="draft"):
        repository.mark_validated(
            recipe_workspace,
            draft.version_id,
            run.reference,
        )
    archived = repository.archive_version(
        recipe_workspace,
        draft.version_id,
    )

    assert run.status is RecipeRunStatus.SUCCEEDED
    assert validated == idempotent
    assert validated.status is RecipeVersionStatus.VALIDATED
    assert validated.validation_run_id == run.reference.run_id
    assert validated.validation_manifest_hash == run.reference.manifest_hash
    assert validated.validation_artifact_path == run.reference.artifact_path
    assert validated.validation_binding_hash == run.reference.binding_hash
    assert published.status is RecipeVersionStatus.PUBLISHED
    assert published == published_again
    assert archived.status is RecipeVersionStatus.ARCHIVED


def test_repository_rejects_failed_validation_and_invalid_transitions(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    drifted = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _LifecycleLoader(drift=True),
    ).execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )

    assert drifted.status is RecipeRunStatus.NEEDS_REVIEW
    with pytest.raises(RecipeStateError, match="successful dry run"):
        repository.mark_validated(
            recipe_workspace,
            draft.version_id,
            drifted.reference,
        )
    with pytest.raises(RecipeStateError, match="validated"):
        repository.publish_version(recipe_workspace, draft.version_id)
    with pytest.raises(RecipeStateError, match="published"):
        repository.archive_version(recipe_workspace, draft.version_id)


def test_repository_rejects_success_manifest_without_step_evidence(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    writer = RecipeRunArtifactStore.for_workspace(recipe_workspace).begin(
        executable_recipe.spec,
        bind_recipe_parameters(executable_recipe.spec, {}),
        RecipeRunKind.DRY_RUN,
    )
    empty_success = writer.finalize(RecipeRunStatus.SUCCEEDED)

    with pytest.raises(RecipeIntegrityError, match="step evidence"):
        repository.mark_validated(
            recipe_workspace,
            draft.version_id,
            empty_success,
        )


def test_repository_rejects_changed_validation_evidence(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    first = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _LifecycleLoader(),
    ).execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )
    second = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _LifecycleLoader(),
    ).execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )
    repository.mark_validated(
        recipe_workspace,
        draft.version_id,
        first.reference,
    )

    with pytest.raises(RecipeConflictError, match="validation evidence"):
        repository.mark_validated(
            recipe_workspace,
            draft.version_id,
            second.reference,
        )


def test_publish_reverifies_validation_manifest(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    repository = RecipeRepository(tmp_path / "automation.db")
    draft = repository.save_draft(recipe_workspace, executable_recipe)
    run = RecipeExecutor(
        recipe_workspace,
        loader_resolver=lambda _source_id: _LifecycleLoader(),
    ).execute(
        executable_recipe.spec,
        parameter_values={},
        kind=RecipeRunKind.DRY_RUN,
    )
    repository.mark_validated(
        recipe_workspace,
        draft.version_id,
        run.reference,
    )
    run_dir = recipe_workspace.confined_root.resolve(run.reference.artifact_path)
    (run_dir / "events.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RecipeIntegrityError, match="validation run"):
        repository.publish_version(recipe_workspace, draft.version_id)
