from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import flask
import pyarrow as pa
import pytest

from data_formulator.automation.models import AutomationRunStatus
from data_formulator.automation.repository import AutomationRepository
from data_formulator.error_handler import register_error_handlers
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.executor import RecipeExecutor
from data_formulator.recipes.repository import RecipeRepository
from data_formulator.recipes.run_store import RecipeRunKind
from data_formulator.recipes.service import RecipeService
from data_formulator.recipes.spec import (
    BindingTarget,
    ParameterBinding,
    ParameterType,
    RecipeParameter,
)
from data_formulator.routes import automation as automation_routes
from data_formulator.routes.automation import automation_bp


pytestmark = [pytest.mark.backend]


class _ApiLoader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": [30, 40],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


@pytest.fixture
def automation_api(tmp_path, monkeypatch, recipe_workspace):
    database_path = tmp_path / "automation" / "automation.db"
    clock = _MutableClock(datetime(2026, 8, 20, 12, tzinfo=timezone.utc))
    recipes = RecipeRepository(database_path)
    automation = AutomationRepository(database_path, clock=clock)
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, AUTOMATION_ENABLED=True)
    app.register_blueprint(automation_bp)
    register_error_handlers(app)

    identity = {"value": recipe_workspace.identity_id}
    workspaces = {recipe_workspace.identity_id: recipe_workspace}
    monkeypatch.setattr(
        automation_routes,
        "get_identity_id",
        lambda: identity["value"],
    )
    monkeypatch.setattr(
        automation_routes,
        "get_workspace",
        lambda identity_id: workspaces[identity_id],
    )
    monkeypatch.setattr(
        automation_routes.AutomationRepository,
        "for_data_home",
        classmethod(lambda cls: automation),
    )
    monkeypatch.setattr(
        automation_routes.RecipeRepository,
        "for_data_home",
        classmethod(lambda cls: recipes),
    )
    return {
        "app": app,
        "client": app.test_client(),
        "automation": automation,
        "recipes": recipes,
        "clock": clock,
        "identity": identity,
        "workspaces": workspaces,
        "workspace": recipe_workspace,
    }


def _publish_version(
    recipes: RecipeRepository,
    workspace,
    compiled: CompiledRecipe,
):
    draft = recipes.save_draft(workspace, compiled)
    service = RecipeService(recipes)
    result = service.dry_run(
        workspace,
        draft.version_id,
        parameter_values={},
        loader_resolver=lambda _source_id: _ApiLoader(),
    )
    assert result.reference is not None
    return service.publish(workspace, draft.version_id)


def test_schedule_and_manual_run_api_use_server_owned_scope_and_time(
    automation_api,
    executable_recipe: CompiledRecipe,
) -> None:
    client = automation_api["client"]
    workspace = automation_api["workspace"]
    published = _publish_version(
        automation_api["recipes"],
        workspace,
        executable_recipe,
    )

    created = client.post(
        "/api/automation/schedules",
        json={
            "version_id": published.version_id,
            "name": "Daily regional totals",
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        },
    ).get_json()

    assert created["status"] == "success"
    schedule = created["data"]["schedule"]
    assert schedule["version_id"] == published.version_id
    assert schedule["next_run_at"] == "2026-08-21T09:00:00.000000Z"
    assert "identity_id" not in schedule
    assert "workspace_id" not in schedule

    listed = client.get("/api/automation/schedules").get_json()
    assert listed["data"]["schedules"] == [schedule]

    updated = client.patch(
        f"/api/automation/schedules/{schedule['schedule_id']}",
        json={
            "name": "Weekday regional totals",
            "cron_expression": "30 8 * * 1-5",
            "timezone": "America/New_York",
        },
    ).get_json()["data"]["schedule"]
    assert updated["version_id"] == published.version_id
    assert updated["name"] == "Weekday regional totals"
    assert updated["next_run_at"] == "2026-08-20T12:30:00.000000Z"

    disabled = client.post(
        f"/api/automation/schedules/{schedule['schedule_id']}/disable",
    ).get_json()["data"]["schedule"]
    assert disabled["enabled"] is False
    enabled = client.post(
        f"/api/automation/schedules/{schedule['schedule_id']}/enable",
    ).get_json()["data"]["schedule"]
    assert enabled["enabled"] is True

    queued = client.post(
        "/api/automation/runs/manual",
        json={"version_id": published.version_id},
    ).get_json()["data"]["run"]
    assert queued["trigger"] == "manual"
    assert queued["status"] == "queued"
    assert queued["scheduled_for"] == "2026-08-20T12:00:00.000000Z"
    assert queued["schedule_id"] is None
    assert queued["artifact"] is None
    assert "lease_owner" not in queued
    assert "lease_token" not in queued
    assert "lease_expires_at" not in queued

    runs = client.get("/api/automation/runs?limit=20&status=queued").get_json()
    assert runs["data"]["runs"] == [queued]

    claimed = automation_api["automation"].claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    visible = client.get(
        f"/api/automation/runs/{claimed.run_id}",
    ).get_json()["data"]["run"]
    assert visible["status"] == "running"
    assert "lease_token" not in visible

    cancellation = client.post(
        f"/api/automation/runs/{claimed.run_id}/cancel",
    ).get_json()["data"]["run"]
    assert cancellation["status"] == "running"
    assert cancellation["cancel_requested_at"] is not None


def test_run_artifact_queries_verify_the_persisted_reference(
    automation_api,
    executable_recipe: CompiledRecipe,
) -> None:
    client = automation_api["client"]
    workspace = automation_api["workspace"]
    recipes = automation_api["recipes"]
    automation = automation_api["automation"]
    published = _publish_version(recipes, workspace, executable_recipe)
    queued = automation.enqueue_manual_run(
        workspace.identity_id,
        workspace.workspace_id,
        published.version_id,
    )
    claimed = automation.claim_next_run(
        worker_id="worker-a",
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    result = RecipeExecutor(
        workspace,
        lambda _source_id: _ApiLoader(),
    ).execute(
        recipes.load_version(workspace, published.version_id).compiled.spec,
        parameter_values={},
        kind=RecipeRunKind.AUTOMATION,
        run_id="run_" + "a" * 32,
    )
    assert result.reference is not None
    reference = result.reference
    finished = automation.finish_run(
        workspace.identity_id,
        workspace.workspace_id,
        queued.run_id,
        worker_id="worker-a",
        lease_token=claimed.lease_token or "",
        status=AutomationRunStatus.SUCCEEDED,
        artifact_run_id=reference.run_id,
        artifact_path=reference.artifact_path,
        manifest_hash=reference.manifest_hash,
        binding_hash=reference.binding_hash,
    )

    detail = client.get(
        f"/api/automation/runs/{finished.run_id}",
    ).get_json()["data"]["run"]
    assert detail["artifact"] == {
        "run_id": reference.run_id,
        "path": reference.artifact_path,
        "manifest_hash": str(reference.manifest_hash),
        "binding_hash": str(reference.binding_hash),
    }

    manifest = client.get(
        f"/api/automation/runs/{finished.run_id}/manifest",
    ).get_json()
    events = client.get(
        f"/api/automation/runs/{finished.run_id}/events",
    ).get_json()
    assert manifest["status"] == "success"
    assert manifest["data"]["manifest"]["run_id"] == reference.run_id
    assert manifest["data"]["manifest"]["status"] == "succeeded"
    assert events["status"] == "success"
    assert [event["status"] for event in events["data"]["events"]] == [
        "started",
        "succeeded",
        "started",
        "succeeded",
        "started",
        "succeeded",
    ]

    manifest_path = workspace.confined_root.resolve(
        f"{reference.artifact_path}/manifest.json"
    )
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    rejected = client.get(
        f"/api/automation/runs/{finished.run_id}/manifest",
    ).get_json()
    assert rejected["status"] == "error"
    assert rejected["error"]["code"] == "VALIDATION_ERROR"
    assert rejected["error"]["message"] == (
        "Run artifacts could not be verified."
    )


@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        (
            "/api/automation/schedules",
            "post",
            {
                "version_id": "rv_" + "1" * 64,
                "name": "Schedule",
                "cron_expression": "0 9 * * *",
                "timezone": "UTC",
                "next_run_at": "2099-01-01T00:00:00Z",
            },
        ),
        (
            "/api/automation/runs/manual",
            "post",
            {"version_id": "rv_" + "1" * 64, "parameters": {"limit": 1}},
        ),
        ("/api/automation/runs?limit=0", "get", None),
        ("/api/automation/runs?limit=101", "get", None),
        ("/api/automation/runs?status=unknown", "get", None),
    ],
)
def test_automation_api_rejects_client_owned_execution_fields(
    automation_api,
    path,
    method,
    payload,
) -> None:
    client = automation_api["client"]

    response = getattr(client, method)(path, json=payload).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"


def test_schedule_and_manual_enqueue_reject_versions_without_default_binding(
    automation_api,
    executable_recipe: CompiledRecipe,
) -> None:
    workspace = automation_api["workspace"]
    recipes = automation_api["recipes"]
    parameterized = CompiledRecipe(
        spec=replace(
            executable_recipe.spec,
            parameters=(RecipeParameter(
                id="limit",
                name="Row limit",
                value_type=ParameterType.INTEGER,
                required=True,
            ),),
            bindings=(ParameterBinding(
                parameter_id="limit",
                step_id=executable_recipe.spec.steps[0].id,
                target=BindingTarget.LOAD_LIMIT,
            ),),
        ),
        workflow_markdown=executable_recipe.workflow_markdown,
    )
    draft = recipes.save_draft(workspace, parameterized)
    service = RecipeService(recipes)
    result = service.dry_run(
        workspace,
        draft.version_id,
        parameter_values={"limit": 10},
        loader_resolver=lambda _source_id: _ApiLoader(),
    )
    assert result.reference is not None
    published = service.publish(workspace, draft.version_id)
    client = automation_api["client"]

    manual = client.post(
        "/api/automation/runs/manual",
        json={"version_id": published.version_id},
    ).get_json()
    scheduled = client.post(
        "/api/automation/schedules",
        json={
            "version_id": published.version_id,
            "name": "Invalid default binding",
            "cron_expression": "0 9 * * *",
            "timezone": "UTC",
        },
    ).get_json()

    assert manual["status"] == "error"
    assert manual["error"]["code"] == "VALIDATION_ERROR"
    assert scheduled["status"] == "error"
    assert scheduled["error"]["code"] == "VALIDATION_ERROR"
    assert automation_api["automation"].list_runs(
        workspace.identity_id,
        workspace.workspace_id,
    ) == ()
    assert automation_api["automation"].list_schedules(
        workspace.identity_id,
        workspace.workspace_id,
    ) == ()


def test_automation_api_fails_closed_before_opening_storage(
    automation_api,
    monkeypatch,
) -> None:
    app = automation_api["app"]
    client = automation_api["client"]
    app.config["AUTOMATION_ENABLED"] = False
    monkeypatch.setattr(
        automation_routes,
        "get_workspace",
        lambda _identity_id: pytest.fail("disabled API opened a Workspace"),
    )

    response = client.get("/api/automation/runs").get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.parametrize(
    "path",
    [
        "/api/automation/schedules",
        "/api/automation/runs/manual",
        "/api/automation/schedules/sch_" + "1" * 32,
    ],
)
def test_automation_api_rejects_malformed_json(
    automation_api,
    path,
) -> None:
    client = automation_api["client"]
    method = client.patch if "/schedules/sch_" in path else client.post

    response = method(
        path,
        data='{"version_id":',
        content_type="application/json",
    ).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"


def test_automation_catalog_remains_readable_without_stable_signing(
    automation_api,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    client = automation_api["client"]

    schedules = client.get("/api/automation/schedules").get_json()
    runs = client.get("/api/automation/runs").get_json()

    assert schedules["status"] == "success"
    assert schedules["data"]["schedules"] == []
    assert runs["status"] == "success"
    assert runs["data"]["runs"] == []


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/automation/schedules",
            {
                "version_id": "rv_" + "1" * 64,
                "name": "Schedule",
                "cron_expression": "0 9 * * *",
                "timezone": "UTC",
            },
        ),
        (
            "/api/automation/runs/manual",
            {"version_id": "rv_" + "1" * 64},
        ),
    ],
)
def test_automation_enqueue_requires_stable_signing_before_workspace_access(
    automation_api,
    monkeypatch,
    path,
    payload,
) -> None:
    client = automation_api["client"]
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        automation_routes,
        "get_workspace",
        lambda _identity_id: pytest.fail(
            "missing signing configuration opened a Workspace"
        ),
    )

    response = client.post(path, json=payload).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_run_lookup_rejects_another_identity_scope(
    automation_api,
    executable_recipe: CompiledRecipe,
    tmp_path,
) -> None:
    client = automation_api["client"]
    workspace = automation_api["workspace"]
    published = _publish_version(
        automation_api["recipes"],
        workspace,
        executable_recipe,
    )
    queued = automation_api["automation"].enqueue_manual_run(
        workspace.identity_id,
        workspace.workspace_id,
        published.version_id,
    )
    from data_formulator.datalake.workspace import Workspace

    other = Workspace(
        "user:mallory",
        root_dir=tmp_path / "other-workspaces",
        workspace_id=workspace.workspace_id,
    )
    automation_api["workspaces"][other.identity_id] = other
    automation_api["identity"]["value"] = other.identity_id

    response = client.get(
        f"/api/automation/runs/{queued.run_id}",
    )

    assert response.status_code == 403
    body = response.get_json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "ACCESS_DENIED"
    assert body["error"]["message"] == (
        "Automation resource does not belong to the active Workspace."
    )
