# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace-scoped REST API for deterministic Recipe lifecycle actions."""

from __future__ import annotations

from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Blueprint, current_app, request

from data_formulator.auth.identity import get_identity_id
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.recipes.artifact_store import RecipeArtifactError
from data_formulator.recipes.compiler import RecipeCompileError, RecipeCompiler
from data_formulator.recipes.executor import RecipeExecutionResult
from data_formulator.recipes.lineage import ArtifactLineageError
from data_formulator.recipes.openers import ExplicitConnectorOpener
from data_formulator.recipes.repository import (
    RecipeNotFoundError,
    RecipeRepository,
    RecipeRepositoryError,
    RecipeScopeError,
    StoredRecipe,
    StoredRecipeVersion,
)
from data_formulator.recipes.run_store import RecipeRunArtifactError
from data_formulator.recipes.service import RecipeService
from data_formulator.workspace_factory import get_workspace


recipes_bp = Blueprint("recipes", __name__, url_prefix="/api/recipes")

_View = TypeVar("_View", bound=Callable[..., Any])


def _recipe_errors(view: _View) -> _View:
    """Translate expected Recipe-domain failures into the shared API envelope."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except RecipeNotFoundError as exc:
            raise AppError(ErrorCode.TABLE_NOT_FOUND, str(exc)) from exc
        except RecipeScopeError as exc:
            raise AppError(
                ErrorCode.ACCESS_DENIED,
                "Recipe does not belong to the active Workspace.",
            ) from exc
        except (
            RecipeCompileError,
            ArtifactLineageError,
            RecipeArtifactError,
            RecipeRunArtifactError,
            RecipeRepositoryError,
        ) as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except ValueError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    return wrapped  # type: ignore[return-value]


def _require_enabled() -> None:
    if not current_app.config.get("AUTOMATION_ENABLED", False):
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Recipe automation is not enabled on this server.",
        )


@recipes_bp.before_request
def require_recipe_feature() -> None:
    """Keep every current and future endpoint behind the default-off flag."""
    _require_enabled()


def _context():
    identity_id = get_identity_id()
    workspace = get_workspace(identity_id)
    capabilities = workspace.storage_capabilities
    if (
        capabilities.storage_backend != "local"
        or not capabilities.durable
        or not capabilities.supports_durable_artifacts
    ):
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Recipes require a durable local Workspace.",
        )
    return identity_id, workspace, RecipeRepository.for_data_home()


def _json_object(*, optional: bool = False) -> dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None and optional:
        return {}
    if not isinstance(data, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "A JSON object is required.")
    return data


def _parameter_values(data: Mapping[str, Any]) -> Mapping[str, Any]:
    values = data.get("parameters", {})
    if not isinstance(values, dict):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'parameters' must be a JSON object.",
        )
    return values


def _stored_recipe(recipe: StoredRecipe) -> dict[str, Any]:
    return {
        "recipe_id": recipe.recipe_id,
        "name": recipe.name,
        "description": recipe.description,
        "created_by": recipe.created_by,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
    }


def _stored_version(version: StoredRecipeVersion) -> dict[str, Any]:
    return {
        "version_id": version.version_id,
        "recipe_id": version.recipe_id,
        "recipe_hash": str(version.recipe_hash),
        "status": version.status.value,
        "created_at": version.created_at,
        "validated_at": version.validated_at,
        "published_at": version.published_at,
        "archived_at": version.archived_at,
        "validation_run_id": version.validation_run_id,
    }


def _execution_result(result: RecipeExecutionResult) -> dict[str, Any]:
    reference = result.reference
    return {
        "status": result.status.value,
        "run": (
            {
                "run_id": reference.run_id,
                "kind": reference.kind.value,
                "status": reference.status.value,
                "manifest_hash": str(reference.manifest_hash),
            }
            if reference is not None
            else None
        ),
        "steps": [
            {
                "step_id": step.step_id,
                "kind": step.kind.value,
                "content_hash": str(step.content_hash),
                "schema_hash": str(step.schema_hash),
                "output_path": step.output_path,
                "duration_ms": step.duration_ms,
            }
            for step in result.step_results
        ],
        "error": result.error.to_dict() if result.error is not None else None,
    }


def _loader_resolver(identity_id: str):
    opener = ExplicitConnectorOpener(initialize_registry=False)
    return lambda source_id: opener.open(identity_id, source_id)


@recipes_bp.route("/compile", methods=["POST"])
@_recipe_errors
def compile_recipe():
    identity_id, workspace, repository = _context()
    data = _json_object()
    targets = data.get("target_artifact_ids")
    name = data.get("name")
    description = data.get("description", "")
    if (
        not isinstance(targets, list)
        or not targets
        or len(targets) > 20
        or any(not isinstance(item, str) or not item for item in targets)
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'target_artifact_ids' must contain 1 to 20 artifact ids.",
        )
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'name' must contain 1 to 200 characters.",
        )
    if not isinstance(description, str) or len(description) > 2000:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'description' must be a string of at most 2000 characters.",
        )
    compiled = RecipeCompiler.for_workspace(workspace).compile(
        target_artifact_ids=targets,
        name=name.strip(),
        description=description.strip(),
        created_by=identity_id,
    )
    version = repository.save_draft(workspace, compiled)
    return json_ok({
        "version": _stored_version(version),
        "spec": compiled.spec.to_dict(),
        "workflow_markdown": compiled.workflow_markdown,
    })


@recipes_bp.route("", methods=["GET"])
@_recipe_errors
def list_recipes():
    identity_id, workspace, repository = _context()
    recipes = repository.list_recipes(identity_id, workspace.workspace_id)
    versions = repository.list_versions(identity_id, workspace.workspace_id)
    versions_by_recipe: dict[str, list[dict[str, Any]]] = {}
    for version in versions:
        versions_by_recipe.setdefault(version.recipe_id, []).append(
            _stored_version(version)
        )
    return json_ok({
        "recipes": [
            {
                **_stored_recipe(recipe),
                "versions": versions_by_recipe.get(recipe.recipe_id, []),
            }
            for recipe in recipes
        ],
    })


@recipes_bp.route("/versions/<version_id>", methods=["GET"])
@_recipe_errors
def get_recipe_version(version_id: str):
    identity_id, workspace, repository = _context()
    loaded = repository.load_version(workspace, version_id)
    recipes = {
        recipe.recipe_id: recipe
        for recipe in repository.list_recipes(identity_id, workspace.workspace_id)
    }
    recipe = recipes.get(loaded.version.recipe_id)
    if recipe is None:
        raise RecipeNotFoundError("Recipe was not found in this Workspace")
    return json_ok({
        "recipe": _stored_recipe(recipe),
        "version": _stored_version(loaded.version),
        "spec": loaded.compiled.spec.to_dict(),
        "workflow_markdown": loaded.compiled.workflow_markdown,
    })


@recipes_bp.route("/versions/<version_id>/dry-run", methods=["POST"])
@_recipe_errors
def dry_run_recipe(version_id: str):
    identity_id, workspace, repository = _context()
    data = _json_object(optional=True)
    result = RecipeService(repository).dry_run(
        workspace,
        version_id,
        parameter_values=_parameter_values(data),
        loader_resolver=_loader_resolver(identity_id),
    )
    version = repository.get_version(
        identity_id,
        workspace.workspace_id,
        version_id,
    )
    return json_ok({
        "result": _execution_result(result),
        "version": _stored_version(version),
    })


@recipes_bp.route("/versions/<version_id>/publish", methods=["POST"])
@_recipe_errors
def publish_recipe(version_id: str):
    _identity_id, workspace, repository = _context()
    version = RecipeService(repository).publish(workspace, version_id)
    return json_ok({"version": _stored_version(version)})


@recipes_bp.route("/versions/<version_id>/run", methods=["POST"])
@_recipe_errors
def run_recipe(version_id: str):
    identity_id, workspace, repository = _context()
    data = _json_object(optional=True)
    result = RecipeService(repository).run_manual(
        workspace,
        version_id,
        parameter_values=_parameter_values(data),
        loader_resolver=_loader_resolver(identity_id),
    )
    return json_ok({"result": _execution_result(result)})


@recipes_bp.route("/versions/<version_id>/archive", methods=["POST"])
@_recipe_errors
def archive_recipe(version_id: str):
    _identity_id, workspace, repository = _context()
    version = repository.archive_version(workspace, version_id)
    return json_ok({"version": _stored_version(version)})
