from __future__ import annotations

import flask
import pyarrow as pa
import pytest

from data_formulator.error_handler import register_error_handlers
from data_formulator.recipes.repository import RecipeRepository
from data_formulator.routes import recipes as recipe_routes
from data_formulator.routes.recipes import recipes_bp


pytestmark = [pytest.mark.backend]


class _ApiLoader:
    def fetch_data_as_arrow(self, source_table: str, import_options: dict):
        return pa.table({
            "region": ["west", "east"],
            "amount": [10, 20],
        })

    def get_safe_params(self):
        return {}

    def get_column_types(self, source_table: str):
        raise NotImplementedError


@pytest.fixture
def recipe_api(tmp_path, monkeypatch, recipe_workspace):
    repository = RecipeRepository(tmp_path / "automation" / "automation.db")
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, AUTOMATION_ENABLED=True)
    app.register_blueprint(recipes_bp)
    register_error_handlers(app)

    monkeypatch.setattr(
        recipe_routes,
        "get_identity_id",
        lambda: recipe_workspace.identity_id,
    )
    monkeypatch.setattr(
        recipe_routes,
        "get_workspace",
        lambda _identity_id: recipe_workspace,
    )
    monkeypatch.setattr(
        recipe_routes.RecipeRepository,
        "for_data_home",
        classmethod(lambda cls: repository),
    )
    monkeypatch.setattr(
        recipe_routes,
        "_loader_resolver",
        lambda _identity_id: lambda _source_id: _ApiLoader(),
    )
    return app, app.test_client(), repository


def test_recipe_api_runs_the_persisted_version_lifecycle(
    recipe_api,
    executable_recipe,
) -> None:
    _app, client, _repository = recipe_api
    target_id = executable_recipe.spec.target_artifact_ids[0]

    compiled_response = client.post(
        "/api/recipes/compile",
        json={
            "target_artifact_ids": [target_id],
            "name": "Regional totals",
            "description": "Refresh and chart regional totals.",
        },
    ).get_json()
    assert compiled_response["status"] == "success"
    version_id = compiled_response["data"]["version"]["version_id"]
    assert compiled_response["data"]["version"]["status"] == "draft"
    assert [step["kind"] for step in compiled_response["data"]["spec"]["steps"]] == [
        "load",
        "transform",
        "chart",
    ]

    listed = client.get("/api/recipes").get_json()["data"]["recipes"]
    assert len(listed) == 1
    assert listed[0]["name"] == "Regional totals"
    assert listed[0]["versions"][0]["version_id"] == version_id

    detail = client.get(f"/api/recipes/versions/{version_id}").get_json()
    assert detail["data"]["spec"] == compiled_response["data"]["spec"]
    assert detail["data"]["workflow_markdown"].startswith("# Regional totals")

    dry_run = client.post(
        f"/api/recipes/versions/{version_id}/dry-run",
        json={"parameters": {}},
    ).get_json()
    assert dry_run["data"]["result"]["status"] == "succeeded"
    assert dry_run["data"]["result"]["run"]["kind"] == "dry_run"
    assert dry_run["data"]["version"]["status"] == "validated"

    published = client.post(
        f"/api/recipes/versions/{version_id}/publish",
    ).get_json()
    assert published["data"]["version"]["status"] == "published"

    manual = client.post(
        f"/api/recipes/versions/{version_id}/run",
        json={"parameters": {}},
    ).get_json()
    assert manual["data"]["result"]["status"] == "succeeded"
    assert manual["data"]["result"]["run"]["kind"] == "manual"

    archived = client.post(
        f"/api/recipes/versions/{version_id}/archive",
    ).get_json()
    assert archived["data"]["version"]["status"] == "archived"

    rejected = client.post(
        f"/api/recipes/versions/{version_id}/run",
        json={"parameters": {}},
    ).get_json()
    assert rejected["status"] == "error"
    assert rejected["error"]["code"] == "VALIDATION_ERROR"


def test_recipe_api_is_unavailable_when_feature_flag_is_off(
    recipe_api,
    monkeypatch,
) -> None:
    app, client, _repository = recipe_api
    app.config["AUTOMATION_ENABLED"] = False
    monkeypatch.setattr(
        recipe_routes,
        "get_workspace",
        lambda _identity_id: pytest.fail("disabled API opened a Workspace"),
    )

    response = client.get("/api/recipes")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["message"] == (
        "Recipe automation is not enabled on this server."
    )
    assert body["error"]["retry"] is False


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/recipes/compile",
            {
                "target_artifact_ids": ["art_" + "a" * 64],
                "name": "Recipe",
            },
        ),
        ("/api/recipes/versions/ver_missing/dry-run", {}),
        ("/api/recipes/versions/ver_missing/publish", {}),
        ("/api/recipes/versions/ver_missing/run", {}),
    ],
)
def test_recipe_lifecycle_requires_stable_signing_before_workspace_access(
    recipe_api,
    monkeypatch,
    path,
    payload,
) -> None:
    _app, client, _repository = recipe_api
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        recipe_routes,
        "get_workspace",
        lambda _identity_id: pytest.fail(
            "missing signing configuration opened a Workspace"
        ),
    )

    response = client.post(path, json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["message"] == (
        "Recipe code signing is not configured on this server."
    )
    assert body["error"]["retry"] is False
    assert body["error"]["request_id"]


def test_recipe_catalog_remains_readable_without_stable_signing(
    recipe_api,
    monkeypatch,
) -> None:
    _app, client, _repository = recipe_api
    monkeypatch.delenv("DF_CODE_SIGNING_SECRET", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    body = client.get("/api/recipes").get_json()

    assert body["status"] == "success"
    assert body["data"]["recipes"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"target_artifact_ids": [], "name": "Recipe"},
        {"target_artifact_ids": ["artifact"], "name": ""},
        {"target_artifact_ids": ["artifact"], "name": "Recipe", "description": []},
    ],
)
def test_compile_recipe_rejects_invalid_requests(recipe_api, payload) -> None:
    _app, client, _repository = recipe_api

    response = client.post("/api/recipes/compile", json=payload).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "target",
    [
        "artifact",
        "art_" + "g" * 64,
        "art_" + "a" * 63,
        "art_" + "a" * 65,
    ],
)
def test_compile_recipe_requires_exact_artifact_id(recipe_api, target) -> None:
    _app, client, _repository = recipe_api

    response = client.post(
        "/api/recipes/compile",
        json={"target_artifact_ids": [target], "name": "Recipe"},
    ).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "path",
    [
        "/api/recipes/compile",
        "/api/recipes/versions/rv_" + "a" * 64 + "/dry-run",
        "/api/recipes/versions/rv_" + "a" * 64 + "/run",
    ],
)
def test_recipe_api_rejects_malformed_json_before_action(
    recipe_api,
    monkeypatch,
    path,
) -> None:
    _app, client, _repository = recipe_api
    monkeypatch.setattr(
        recipe_routes.RecipeService,
        "dry_run",
        lambda *_args, **_kwargs: pytest.fail("malformed JSON started a dry run"),
    )
    monkeypatch.setattr(
        recipe_routes.RecipeService,
        "run_manual",
        lambda *_args, **_kwargs: pytest.fail("malformed JSON started a manual run"),
    )

    response = client.post(
        path,
        data='{"parameters":',
        content_type="application/json",
    ).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"


def test_recipe_api_rejects_unsafe_integer_before_action(
    recipe_api,
    monkeypatch,
) -> None:
    _app, client, _repository = recipe_api
    monkeypatch.setattr(
        recipe_routes.RecipeService,
        "run_manual",
        lambda *_args, **_kwargs: pytest.fail("unsafe JSON number started a run"),
    )

    response = client.post(
        "/api/recipes/versions/rv_" + "a" * 64 + "/run",
        json={"parameters": {"limit": 2**63}},
    ).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"
