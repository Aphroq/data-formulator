# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace-scoped Schedule and durable Run REST API."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Blueprint, current_app, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from data_formulator.auth.identity import get_identity_id
from data_formulator.automation.models import (
    AutomationRunStatus,
    StoredAutomationRun,
    StoredSchedule,
)
from data_formulator.automation.repository import (
    AutomationConflictError,
    AutomationNotFoundError,
    AutomationRepository,
    AutomationRepositoryError,
    AutomationScopeError,
    AutomationStateError,
)
from data_formulator.automation.service import AutomationService
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.recipes.artifact_store import RecipeArtifactError
from data_formulator.recipes.repository import (
    RecipeNotFoundError,
    RecipeRepository,
    RecipeRepositoryError,
    RecipeScopeError,
)
from data_formulator.recipes.run_store import (
    RecipeRunArtifactError,
    RecipeRunCorruptError,
)
from data_formulator.security.code_signing import (
    CodeSigningConfigurationError,
    require_stable_code_signing,
)
from data_formulator.workspace_factory import get_workspace


automation_bp = Blueprint(
    "automation",
    __name__,
    url_prefix="/api/automation",
)

_View = TypeVar("_View", bound=Callable[..., Any])
_VERSION_ID_PATTERN = re.compile(r"^rv_[0-9a-f]{64}$")
_MAX_SAFE_INTEGER = 2**53 - 1


def _automation_errors(view: _View) -> _View:
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (AutomationNotFoundError, RecipeNotFoundError) as exc:
            raise AppError(
                ErrorCode.TABLE_NOT_FOUND,
                "Automation resource was not found in this Workspace.",
            ) from exc
        except (AutomationScopeError, RecipeScopeError) as exc:
            raise AppError(
                ErrorCode.ACCESS_DENIED,
                "Automation resource does not belong to the active Workspace.",
            ) from exc
        except CodeSigningConfigurationError as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Automation code signing is not configured on this server.",
            ) from exc
        except RecipeRunCorruptError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Run artifacts could not be verified.",
            ) from exc
        except (
            AutomationConflictError,
            AutomationStateError,
            AutomationRepositoryError,
            RecipeArtifactError,
            RecipeRunArtifactError,
            RecipeRepositoryError,
        ) as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    return wrapped  # type: ignore[return-value]


@automation_bp.before_request
def require_automation_feature() -> None:
    if not current_app.config.get("AUTOMATION_ENABLED", False):
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Automation is not enabled on this server.",
        )


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
            "Automation requires a durable local Workspace.",
        )
    automation_repository = AutomationRepository.for_data_home()
    recipe_repository = RecipeRepository.for_data_home()
    service = AutomationService(automation_repository, recipe_repository)
    return identity_id, workspace, automation_repository, service


def _json_object(*, optional: bool = False) -> dict[str, Any]:
    raw = request.get_data(cache=True)
    if not raw:
        if optional:
            return {}
        raise AppError(ErrorCode.INVALID_REQUEST, "A JSON object is required.")
    if not request.is_json:
        raise AppError(ErrorCode.INVALID_REQUEST, "A JSON object is required.")
    try:
        data = request.get_json(silent=False)
    except (BadRequest, UnsupportedMediaType) as exc:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Request body contains malformed JSON.",
        ) from exc
    if not isinstance(data, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "A JSON object is required.")
    _validate_json_numbers(data)
    return data


def _validate_json_numbers(value: Any) -> None:
    if type(value) is int:
        if abs(value) > _MAX_SAFE_INTEGER:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "JSON integer exceeds the supported safe range.",
            )
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "JSON number must be finite.",
            )
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _validate_json_numbers(item)
    elif isinstance(value, list):
        for item in value:
            _validate_json_numbers(item)


def _require_fields(
    data: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str] = frozenset(),
) -> None:
    unknown = sorted(set(data) - allowed)
    missing = sorted(required - set(data))
    if unknown:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"Unexpected request field(s): {', '.join(unknown)}.",
        )
    if missing:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"Missing request field(s): {', '.join(missing)}.",
        )


def _string_field(
    data: Mapping[str, Any],
    name: str,
    *,
    maximum: int,
) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"'{name}' must be a string.",
        )
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"'{name}' must contain 1 to {maximum} characters.",
        )
    return normalized


def _version_id(data: Mapping[str, Any]) -> str:
    value = data.get("version_id")
    if not isinstance(value, str) or not _VERSION_ID_PATTERN.fullmatch(value):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'version_id' is invalid.",
        )
    return value


def _schedule(schedule: StoredSchedule) -> dict[str, Any]:
    return {
        "schedule_id": schedule.schedule_id,
        "version_id": schedule.version_id,
        "name": schedule.name,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "enabled": schedule.enabled,
        "next_run_at": schedule.next_run_at,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def _run(run: StoredAutomationRun) -> dict[str, Any]:
    artifact = None
    if (
        run.artifact_run_id is not None
        and run.artifact_path is not None
        and run.manifest_hash is not None
        and run.binding_hash is not None
    ):
        artifact = {
            "run_id": run.artifact_run_id,
            "path": run.artifact_path,
            "manifest_hash": str(run.manifest_hash),
            "binding_hash": str(run.binding_hash),
        }
    error = None
    if run.error_code is not None and run.error_message is not None:
        error = {
            "code": run.error_code,
            "message": run.error_message,
        }
    return {
        "run_id": run.run_id,
        "version_id": run.version_id,
        "schedule_id": run.schedule_id,
        "trigger": run.trigger.value,
        "scheduled_for": run.scheduled_for,
        "status": run.status.value,
        "attempt_count": run.attempt_count,
        "available_at": run.available_at,
        "cancel_requested_at": run.cancel_requested_at,
        "artifact": artifact,
        "error": error,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


@automation_bp.route("/schedules", methods=["GET"])
@_automation_errors
def list_schedules():
    identity_id, workspace, repository, _service = _context()
    schedules = repository.list_schedules(
        identity_id,
        workspace.workspace_id,
    )
    return json_ok({"schedules": [_schedule(item) for item in schedules]})


@automation_bp.route("/schedules", methods=["POST"])
@_automation_errors
def create_schedule():
    require_stable_code_signing()
    data = _json_object()
    _require_fields(
        data,
        allowed={"version_id", "name", "cron_expression", "timezone"},
        required={"version_id", "name", "cron_expression", "timezone"},
    )
    _identity_id, workspace, _repository, service = _context()
    schedule = service.create_schedule(
        workspace,
        version_id=_version_id(data),
        name=_string_field(data, "name", maximum=200),
        cron_expression=_string_field(
            data,
            "cron_expression",
            maximum=200,
        ),
        timezone_name=_string_field(data, "timezone", maximum=100),
    )
    return json_ok({"schedule": _schedule(schedule)})


@automation_bp.route("/schedules/<schedule_id>", methods=["PATCH"])
@_automation_errors
def update_schedule(schedule_id: str):
    data = _json_object()
    _require_fields(
        data,
        allowed={"name", "cron_expression", "timezone"},
    )
    if not data:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Schedule update requires at least one field.",
        )
    identity_id, workspace, repository, _service = _context()
    schedule = repository.update_schedule(
        identity_id,
        workspace.workspace_id,
        schedule_id,
        name=(
            _string_field(data, "name", maximum=200)
            if "name" in data
            else None
        ),
        cron_expression=(
            _string_field(data, "cron_expression", maximum=200)
            if "cron_expression" in data
            else None
        ),
        timezone_name=(
            _string_field(data, "timezone", maximum=100)
            if "timezone" in data
            else None
        ),
    )
    return json_ok({"schedule": _schedule(schedule)})


def _set_schedule_enabled(schedule_id: str, *, enabled: bool):
    if request.get_data(cache=True):
        data = _json_object()
        _require_fields(data, allowed=set())
    if enabled:
        require_stable_code_signing()
    identity_id, workspace, repository, _service = _context()
    schedule = repository.set_schedule_enabled(
        identity_id,
        workspace.workspace_id,
        schedule_id,
        enabled=enabled,
    )
    return json_ok({"schedule": _schedule(schedule)})


@automation_bp.route("/schedules/<schedule_id>/enable", methods=["POST"])
@_automation_errors
def enable_schedule(schedule_id: str):
    return _set_schedule_enabled(schedule_id, enabled=True)


@automation_bp.route("/schedules/<schedule_id>/disable", methods=["POST"])
@_automation_errors
def disable_schedule(schedule_id: str):
    return _set_schedule_enabled(schedule_id, enabled=False)


@automation_bp.route("/runs/manual", methods=["POST"])
@_automation_errors
def enqueue_manual_run():
    require_stable_code_signing()
    data = _json_object()
    _require_fields(
        data,
        allowed={"version_id"},
        required={"version_id"},
    )
    _identity_id, workspace, _repository, service = _context()
    run = service.enqueue_manual_run(workspace, _version_id(data))
    return json_ok({"run": _run(run)})


def _run_query() -> tuple[int, AutomationRunStatus | None]:
    allowed = {"limit", "status"}
    unknown = sorted(set(request.args) - allowed)
    if unknown or any(len(request.args.getlist(key)) != 1 for key in request.args):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Run query parameters are invalid.",
        )
    raw_limit = request.args.get("limit", "50")
    if not raw_limit.isascii() or not raw_limit.isdecimal():
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'limit' must be an integer from 1 to 100.",
        )
    limit = int(raw_limit)
    if not 1 <= limit <= 100:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'limit' must be an integer from 1 to 100.",
        )
    raw_status = request.args.get("status")
    try:
        status = AutomationRunStatus(raw_status) if raw_status else None
    except ValueError as exc:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'status' is invalid.",
        ) from exc
    return limit, status


@automation_bp.route("/runs", methods=["GET"])
@_automation_errors
def list_runs():
    limit, status = _run_query()
    identity_id, workspace, repository, _service = _context()
    runs = repository.list_runs(
        identity_id,
        workspace.workspace_id,
        limit=limit,
        status=status,
    )
    return json_ok({"runs": [_run(item) for item in runs]})


@automation_bp.route("/runs/<run_id>", methods=["GET"])
@_automation_errors
def get_run(run_id: str):
    identity_id, workspace, repository, _service = _context()
    run = repository.get_run(identity_id, workspace.workspace_id, run_id)
    return json_ok({"run": _run(run)})


@automation_bp.route("/runs/<run_id>/cancel", methods=["POST"])
@_automation_errors
def cancel_run(run_id: str):
    if request.get_data(cache=True):
        data = _json_object()
        _require_fields(data, allowed=set())
    identity_id, workspace, repository, _service = _context()
    run = repository.request_run_cancel(
        identity_id,
        workspace.workspace_id,
        run_id,
    )
    return json_ok({"run": _run(run)})


@automation_bp.route("/runs/<run_id>/manifest", methods=["GET"])
@_automation_errors
def get_run_manifest(run_id: str):
    _identity_id, workspace, _repository, service = _context()
    stored = service.load_run_artifact(workspace, run_id)
    return json_ok({"manifest": stored.manifest})


@automation_bp.route("/runs/<run_id>/events", methods=["GET"])
@_automation_errors
def get_run_events(run_id: str):
    _identity_id, workspace, _repository, service = _context()
    stored = service.load_run_artifact(workspace, run_id)
    return json_ok({"events": list(stored.events)})
