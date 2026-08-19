from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pyarrow as pa
import pytest

from data_formulator.automation.models import (
    AutomationRunStatus,
    AutomationRunTrigger,
)
from data_formulator.automation.repository import (
    AutomationRepository,
    AutomationScopeError,
    AutomationStateError,
)
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.repository import (
    RecipeRepository,
    RecipeStateError,
    RecipeVersionStatus,
)
from data_formulator.recipes.service import RecipeService


pytestmark = [pytest.mark.backend]


class _ScheduleLoader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": [30, 40],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


def _publish_version(
    repository: RecipeRepository,
    workspace,
    executable_recipe: CompiledRecipe,
):
    draft = repository.save_draft(workspace, executable_recipe)
    service = RecipeService(repository)
    result = service.dry_run(
        workspace,
        draft.version_id,
        parameter_values={},
        loader_resolver=lambda _source_id: _ScheduleLoader(),
    )
    assert result.reference is not None
    return service.publish(workspace, draft.version_id)


def _create_schedule(
    repository: AutomationRepository,
    workspace,
    version_id: str,
    *,
    schedule_id: str = "sch_" + "1" * 32,
):
    return repository.create_schedule(
        identity_id=workspace.identity_id,
        workspace_id=workspace.workspace_id,
        version_id=version_id,
        name="Daily regional totals",
        cron_expression="0  9 * * *",
        timezone_name="UTC",
        next_run_at=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
        schedule_id=schedule_id,
    )


def test_schedule_requires_a_published_version_in_the_same_scope(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    automation = AutomationRepository(database_path)
    draft = recipes.save_draft(recipe_workspace, executable_recipe)

    with pytest.raises(AutomationStateError, match="published"):
        _create_schedule(automation, recipe_workspace, draft.version_id)

    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    with pytest.raises(AutomationScopeError, match="scope"):
        automation.create_schedule(
            identity_id="user:mallory",
            workspace_id=recipe_workspace.workspace_id,
            version_id=published.version_id,
            name="Cross-scope schedule",
            cron_expression="0 9 * * *",
            timezone_name="UTC",
            next_run_at=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
            schedule_id="sch_" + "2" * 32,
        )

    schedule = _create_schedule(automation, recipe_workspace, published.version_id)

    assert schedule.version_id == published.version_id
    assert schedule.identity_id == recipe_workspace.identity_id
    assert schedule.workspace_id == recipe_workspace.workspace_id
    assert schedule.cron_expression == "0 9 * * *"
    assert schedule.timezone == "UTC"
    assert schedule.enabled is True
    assert schedule.next_run_at == "2026-08-20T09:00:00.000000Z"
    assert RecipeRepository(database_path).get_version(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        published.version_id,
    ).status is RecipeVersionStatus.PUBLISHED


def test_schedule_version_is_storage_level_immutable(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    schedule = _create_schedule(
        AutomationRepository(database_path),
        recipe_workspace,
        published.version_id,
    )

    with sqlite3.connect(database_path) as connection, pytest.raises(
        sqlite3.IntegrityError,
        match="immutable",
    ):
        connection.execute(
            "UPDATE schedules SET version_id = ? WHERE schedule_id = ?",
            ("ver_" + "f" * 64, schedule.schedule_id),
        )


@pytest.mark.parametrize(
    ("cron_expression", "timezone_name", "next_run_at", "error"),
    [
        ("0 9 * *", "UTC", datetime.now(timezone.utc), "five fields"),
        ("0 9 * * *", "Not/A-Timezone", datetime.now(timezone.utc), "IANA"),
        ("0 9 * * *", "UTC", datetime(2026, 8, 20, 9), "timezone-aware"),
    ],
)
def test_schedule_rejects_ambiguous_time_configuration_before_writing(
    tmp_path,
    cron_expression,
    timezone_name,
    next_run_at,
    error,
) -> None:
    repository = AutomationRepository(tmp_path / "automation.db")

    with pytest.raises(ValueError, match=error):
        repository.create_schedule(
            identity_id="user:alice",
            workspace_id="ws-1",
            version_id="rv_" + "1" * 64,
            name="Invalid schedule",
            cron_expression=cron_expression,
            timezone_name=timezone_name,
            next_run_at=next_run_at,
        )

    with sqlite3.connect(repository.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schedules").fetchone()[0] == 0


def test_scheduled_run_enqueue_is_idempotent_for_one_planned_time(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    automation = AutomationRepository(database_path)
    schedule = _create_schedule(automation, recipe_workspace, published.version_id)
    scheduled_for = datetime(2026, 8, 20, 9, tzinfo=timezone.utc)

    first = automation.enqueue_scheduled_run(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        schedule.schedule_id,
        scheduled_for=scheduled_for,
    )
    second = automation.enqueue_scheduled_run(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        schedule.schedule_id,
        scheduled_for=scheduled_for,
    )

    assert second == first
    assert first.version_id == published.version_id
    assert first.schedule_id == schedule.schedule_id
    assert first.trigger is AutomationRunTrigger.SCHEDULED
    assert first.status is AutomationRunStatus.QUEUED
    assert first.attempt_count == 0
    assert first.artifact_run_id is None
    assert first.scheduled_for == "2026-08-20T09:00:00.000000Z"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_enabled_schedule_blocks_archive_until_explicitly_disabled(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    automation = AutomationRepository(database_path)
    schedule = _create_schedule(automation, recipe_workspace, published.version_id)

    with pytest.raises(RecipeStateError, match="Schedule"):
        recipes.archive_version(recipe_workspace, published.version_id)

    disabled = automation.set_schedule_enabled(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        schedule.schedule_id,
        enabled=False,
    )
    assert disabled.enabled is False
    archived = recipes.archive_version(recipe_workspace, published.version_id)
    assert archived.status is RecipeVersionStatus.ARCHIVED

    with pytest.raises(AutomationStateError, match="archived"):
        automation.set_schedule_enabled(
            recipe_workspace.identity_id,
            recipe_workspace.workspace_id,
            schedule.schedule_id,
            enabled=True,
        )
