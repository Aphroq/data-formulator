# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workspace-scoped Schedule and durable Run REST API."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable, TypeVar
from urllib.parse import quote

from flask import Blueprint, Response, current_app, request, stream_with_context
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
from data_formulator.automation.report_analysis import (
    AutomationReportAnalysisError,
    analyze_automation_report,
)
from data_formulator.automation.service import AutomationService
from data_formulator.error_handler import classify_and_wrap_llm_error, json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.recipes.artifact_store import RecipeArtifactError
from data_formulator.recipes.canonical import thaw_json
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
from data_formulator.routes.tables import (
    _build_parquet_sample_sql,
    _column_type_map,
    _dedup_dataframe_columns,
    _stream_csv_from_duckdb,
)
from data_formulator.datalake.parquet_utils import df_to_safe_records
from data_formulator.routes.agents import _get_ui_lang, get_client
from data_formulator.workspace_factory import get_workspace


automation_bp = Blueprint(
    "automation",
    __name__,
    url_prefix="/api/automation",
)
logger = logging.getLogger(__name__)

_View = TypeVar("_View", bound=Callable[..., Any])
_VERSION_ID_PATTERN = re.compile(r"^rv_[0-9a-f]{64}$")
_MAX_SAFE_INTEGER = 2**53 - 1
_MAX_RESULT_SAMPLE_ROWS = 1000
_MAX_RESULT_SEARCH_CHARS = 500
_MAX_RESULT_FILTERS = 50


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


def _object_field(
    data: Mapping[str, Any],
    name: str,
    *,
    default: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    value = data.get(name, default if default is not None else {})
    if not isinstance(value, dict):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"'{name}' must be a JSON object.",
        )
    return value


def _schedule(schedule: StoredSchedule) -> dict[str, Any]:
    return {
        "schedule_id": schedule.schedule_id,
        "version_id": schedule.version_id,
        "name": schedule.name,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "parameter_policy": thaw_json(schedule.parameter_policy),
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
        "parameters": thaw_json(run.parameter_values),
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
        allowed={
            "version_id",
            "name",
            "cron_expression",
            "timezone",
            "parameter_policy",
        },
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
        parameter_policy=_object_field(data, "parameter_policy", default={}),
    )
    return json_ok({"schedule": _schedule(schedule)})


@automation_bp.route("/schedules/<schedule_id>", methods=["PATCH"])
@_automation_errors
def update_schedule(schedule_id: str):
    data = _json_object()
    _require_fields(
        data,
        allowed={"name", "cron_expression", "timezone", "parameter_policy"},
    )
    if not data:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Schedule update requires at least one field.",
        )
    _identity_id, workspace, _repository, service = _context()
    schedule = service.update_schedule(
        workspace,
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
        parameter_policy=(
            _object_field(data, "parameter_policy")
            if "parameter_policy" in data
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
        allowed={"version_id", "parameters"},
        required={"version_id"},
    )
    _identity_id, workspace, _repository, service = _context()
    run = service.enqueue_manual_run(
        workspace,
        _version_id(data),
        _object_field(data, "parameters", default={}),
    )
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


@automation_bp.route("/runs/<run_id>/result", methods=["GET"])
@_automation_errors
def get_run_result(run_id: str):
    _identity_id, workspace, _repository, service = _context()
    result = service.load_run_result(workspace, run_id)
    return json_ok({
        "result": {
            "manifest": result.artifact.manifest,
            "events": list(result.artifact.events),
            "report": result.report,
            "outputs": list(result.outputs),
        },
    })


@automation_bp.route("/runs/<run_id>/analysis", methods=["POST"])
@_automation_errors
def analyze_run_result(run_id: str):
    """Explicitly interpret one verified successful Run with the selected model."""
    data = _json_object()
    if set(data) - {"model", "timeout_seconds"}:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Unsupported report analysis field.",
        )
    model = data.get("model")
    if (
        not isinstance(model, dict)
        or not isinstance(model.get("endpoint"), str)
        or not model["endpoint"].strip()
        or not isinstance(model.get("model"), str)
        or not model["model"].strip()
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "A valid model configuration is required.",
        )
    timeout_seconds = data.get("timeout_seconds", 120)
    if (
        type(timeout_seconds) not in {int, float}
        or not 1 <= timeout_seconds <= 300
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'timeout_seconds' must be between 1 and 300.",
        )

    identity_id, workspace, repository, service = _context()
    run = repository.get_run(identity_id, workspace.workspace_id, run_id)
    if run.status is not AutomationRunStatus.SUCCEEDED:
        raise AutomationStateError(
            "AI analysis is available only for successful Runs"
        )
    result = service.load_run_result(workspace, run_id)
    try:
        analysis = analyze_automation_report(
            get_client(model),
            report=result.report,
            outputs=result.outputs,
            parameter_values=thaw_json(run.parameter_values),
            language_code=_get_ui_lang(),
            timeout_seconds=timeout_seconds,
        )
    except AppError:
        raise
    except AutomationReportAnalysisError as exc:
        logger.warning("Model returned invalid Automation report analysis")
        raise AppError(
            ErrorCode.AGENT_ERROR,
            "The model could not analyze this saved result. The Run is unchanged.",
        ) from exc
    except Exception as exc:
        raise classify_and_wrap_llm_error(exc) from exc
    return json_ok({"analysis": analysis.to_dict()})


def _result_sample_request() -> dict[str, Any]:
    data = _json_object(optional=True)
    _require_fields(
        data,
        allowed={
            "size",
            "offset",
            "method",
            "order_by_fields",
            "select_fields",
            "aggregate_fields_and_functions",
            "filters",
            "search",
        },
    )
    size = data.get("size", 500)
    offset = data.get("offset", 0)
    method = data.get("method", "head")
    order_by_fields = data.get("order_by_fields", [])
    select_fields = data.get("select_fields", [])
    aggregate_fields = data.get("aggregate_fields_and_functions", [])
    filters = data.get("filters") or None
    search = data.get("search") or None
    if type(size) is not int or not 1 <= size <= _MAX_RESULT_SAMPLE_ROWS:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"'size' must be an integer from 1 to {_MAX_RESULT_SAMPLE_ROWS}.",
        )
    if type(offset) is not int or offset < 0 or offset > _MAX_SAFE_INTEGER:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'offset' must be a non-negative safe integer.",
        )
    if method not in {"head", "bottom", "random"}:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'method' must be 'head', 'bottom', or 'random'.",
        )
    if (
        not isinstance(order_by_fields, list)
        or len(order_by_fields) > 50
        or any(not isinstance(item, str) for item in order_by_fields)
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'order_by_fields' must be a list of at most 50 strings.",
        )
    if (
        not isinstance(select_fields, list)
        or len(select_fields) > 50
        or any(not isinstance(item, str) for item in select_fields)
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'select_fields' must be a list of at most 50 strings.",
        )
    valid_aggregates = {"count", "avg", "average", "mean", "sum", "min", "max"}
    if (
        not isinstance(aggregate_fields, list)
        or len(aggregate_fields) > 50
        or any(
            not isinstance(item, list)
            or len(item) != 2
            or (item[0] is not None and not isinstance(item[0], str))
            or not isinstance(item[1], str)
            or item[1].lower() not in valid_aggregates
            for item in aggregate_fields
        )
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'aggregate_fields_and_functions' must contain valid field/function pairs.",
        )
    if (
        filters is not None
        and (
            not isinstance(filters, list)
            or len(filters) > _MAX_RESULT_FILTERS
            or any(not isinstance(item, Mapping) for item in filters)
        )
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"'filters' must contain at most {_MAX_RESULT_FILTERS} objects.",
        )
    if search is not None and (
        not isinstance(search, str) or len(search) > _MAX_RESULT_SEARCH_CHARS
    ):
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"'search' must contain at most {_MAX_RESULT_SEARCH_CHARS} characters.",
        )
    return {
        "size": size,
        "offset": offset,
        "method": method,
        "order_by_fields": order_by_fields,
        "select_fields": select_fields,
        "aggregate_fields_and_functions": aggregate_fields,
        "filters": filters,
        "search": search,
    }


@automation_bp.route(
    "/runs/<run_id>/tables/<path:table_name>/sample",
    methods=["POST"],
)
@_automation_errors
def sample_run_result_table(run_id: str, table_name: str):
    """Page, sort, filter, and search one verified final-output table."""
    query = _result_sample_request()
    _identity_id, workspace, _repository, service = _context()
    opened = service.open_run_result_table(workspace, run_id, table_name)
    schema_info = opened.workspace.get_parquet_schema(opened.name)
    columns = [item["name"] for item in schema_info.get("columns", [])]
    column_types = _column_type_map(schema_info.get("columns", []))
    main_sql, count_sql = _build_parquet_sample_sql(
        columns,
        query["aggregate_fields_and_functions"],
        query["select_fields"],
        query["method"],
        query["order_by_fields"],
        query["size"],
        query["offset"],
        filters=query["filters"],
        column_types=column_types,
        search=query["search"],
    )
    total_row_count = int(
        opened.workspace.run_parquet_sql(opened.name, count_sql).iloc[0, 0]
    )
    frame = opened.workspace.run_parquet_sql(opened.name, main_sql)
    frame = _dedup_dataframe_columns(frame)
    return json_ok({
        "rows": df_to_safe_records(frame),
        "total_row_count": total_row_count,
    })


@automation_bp.route(
    "/runs/<run_id>/tables/<path:table_name>/download",
    methods=["POST"],
)
@_automation_errors
def download_run_result_table(run_id: str, table_name: str):
    """Download the complete verified final-output table as CSV or TSV."""
    data = _json_object(optional=True)
    _require_fields(data, allowed={"delimiter"})
    delimiter = data.get("delimiter", ",")
    if delimiter not in {",", "\t"}:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "'delimiter' must be ',' or '\\t'.",
        )
    _identity_id, workspace, _repository, service = _context()
    opened = service.open_run_result_table(workspace, run_id, table_name)
    extension = "tsv" if delimiter == "\t" else "csv"
    mime = "text/tab-separated-values" if delimiter == "\t" else "text/csv"
    ascii_name = opened.name.encode("ascii", "replace").decode("ascii")
    utf8_name = quote(opened.name)
    disposition = (
        f'attachment; filename="{ascii_name}.{extension}"; '
        f"filename*=UTF-8''{utf8_name}.{extension}"
    )
    return Response(
        stream_with_context(
            _stream_csv_from_duckdb(
                opened.workspace,
                opened.name,
                delimiter,
            )
        ),
        mimetype=mime,
        headers={"Content-Disposition": disposition},
    )
