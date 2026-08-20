from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pyarrow as pa
import pytest

from data_formulator.automation.models import (
    AutomationRunStatus,
    AutomationRunTrigger,
)
from data_formulator.automation.parameters import resolve_schedule_parameter_policy
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
    parameter_policy=None,
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
        parameter_policy=parameter_policy or {},
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
        ("61 9 * * *", "UTC", datetime.now(timezone.utc), "Cron"),
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
    assert first.parameter_values == {}
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_scheduled_run_freezes_resolved_parameters_before_schedule_edits(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    automation = AutomationRepository(database_path)
    schedule = _create_schedule(
        automation,
        recipe_workspace,
        published.version_id,
        parameter_policy={
            "as_of": {"source": "scheduled_date", "offset_days": -1},
            "region": {"source": "literal", "value": "west"},
        },
    )

    queued = automation.enqueue_scheduled_run(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        schedule.schedule_id,
        scheduled_for=datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
    )
    updated = automation.update_schedule(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        schedule.schedule_id,
        parameter_policy={
            "as_of": {"source": "scheduled_date", "offset_days": 0},
            "region": {"source": "literal", "value": "east"},
        },
    )

    assert schedule.parameter_policy["region"]["value"] == "west"
    assert updated.parameter_policy["region"]["value"] == "east"
    assert queued.parameter_values == {
        "as_of": "2026-08-19",
        "region": "west",
    }
    assert queued.parameter_values == resolve_schedule_parameter_policy(
        schedule.parameter_policy,
        scheduled_for=queued.scheduled_for,
        timezone_name=schedule.timezone,
    )

    with sqlite3.connect(database_path) as connection, pytest.raises(
        sqlite3.IntegrityError,
        match="immutable",
    ):
        connection.execute(
            "UPDATE runs SET parameter_values_json = '{}' WHERE run_id = ?",
            (queued.run_id,),
        )


def test_manual_runs_are_distinct_and_listed_only_inside_their_scope(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    current = datetime(2026, 8, 20, 9, tzinfo=timezone.utc)
    automation = AutomationRepository(database_path, clock=lambda: current)

    first = automation.enqueue_manual_run(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        published.version_id,
        parameter_values={"region": "west"},
    )
    current += timedelta(seconds=1)
    second = automation.enqueue_manual_run(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        published.version_id,
        parameter_values={"region": "east"},
    )

    assert first.run_id != second.run_id
    assert first.parameter_values == {"region": "west"}
    assert second.parameter_values == {"region": "east"}
    assert first.schedule_id is None
    assert first.trigger is AutomationRunTrigger.MANUAL
    assert first.status is AutomationRunStatus.QUEUED
    assert first.scheduled_for == "2026-08-20T09:00:00.000000Z"
    assert second.scheduled_for == "2026-08-20T09:00:01.000000Z"
    assert automation.list_runs(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        limit=1,
    ) == (second,)
    assert automation.list_runs(
        recipe_workspace.identity_id,
        recipe_workspace.workspace_id,
        status=AutomationRunStatus.QUEUED,
    ) == (second, first)
    assert automation.list_runs("user:mallory", "ws-1") == ()


def test_schedule_can_compute_its_first_occurrence_from_the_repository_clock(
    tmp_path,
    recipe_workspace,
    executable_recipe: CompiledRecipe,
) -> None:
    database_path = tmp_path / "automation.db"
    recipes = RecipeRepository(database_path)
    published = _publish_version(recipes, recipe_workspace, executable_recipe)
    automation = AutomationRepository(
        database_path,
        clock=lambda: datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    schedule = automation.create_schedule(
        identity_id=recipe_workspace.identity_id,
        workspace_id=recipe_workspace.workspace_id,
        version_id=published.version_id,
        name="Next daily run",
        cron_expression="0 9 * * *",
        timezone_name="UTC",
    )

    assert schedule.next_run_at == "2026-08-21T09:00:00.000000Z"


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
