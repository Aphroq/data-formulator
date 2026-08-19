"""Explicit GitHub Copilot device authorization API.

The blueprint is registered only when ``GITHUB_COPILOT_ENABLED`` is true.
Every handler checks the flag again so a directly registered blueprint still
fails closed, and every operation resolves identity exclusively on the server.
"""

from __future__ import annotations

import threading
from typing import Any

from flask import Blueprint, request

from data_formulator.auth.identity import get_identity_id
from data_formulator.auth.vault import get_credential_vault
from data_formulator.copilot.device_flow import (
    CopilotDeviceFlowService,
    is_github_copilot_enabled,
)
from data_formulator.copilot.capabilities import copilot_capability_store
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode


copilot_auth_bp = Blueprint(
    "copilot_auth",
    __name__,
    url_prefix="/api/copilot/auth",
)

_service: CopilotDeviceFlowService | None = None
_service_vault: object | None = None
_service_lock = threading.Lock()


def get_copilot_device_flow_service() -> CopilotDeviceFlowService:
    """Return the process-local pending-flow service for the active vault."""

    vault = get_credential_vault()
    if vault is None:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Credential vault is required for GitHub Copilot",
            retry=False,
        )

    global _service, _service_vault
    with _service_lock:
        if _service is None or _service_vault is not vault:
            _service = CopilotDeviceFlowService(vault=vault)
            _service_vault = vault
        return _service


def _require_enabled() -> None:
    if not is_github_copilot_enabled():
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub Copilot is not enabled",
            retry=False,
        )


def _json_object() -> dict[str, Any]:
    if not request.is_json:
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid request format")
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid request format")
    return value


def _authorization_id() -> str:
    value = _json_object().get("authorization_id")
    if not isinstance(value, str) or not value.strip():
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "authorization_id is required",
        )
    return value.strip()


@copilot_auth_bp.route("/status", methods=["GET"])
def copilot_status():
    _require_enabled()
    identity_id = get_identity_id()
    result = get_copilot_device_flow_service().status(identity_id)
    if not result.get("connected"):
        copilot_capability_store.invalidate_identity(identity_id)
    return json_ok(result)


@copilot_auth_bp.route("/device/start", methods=["POST"])
def start_copilot_device_flow():
    _require_enabled()
    _json_object()
    result = get_copilot_device_flow_service().start(get_identity_id())
    return json_ok(result)


@copilot_auth_bp.route("/device/poll", methods=["POST"])
def poll_copilot_device_flow():
    _require_enabled()
    authorization_id = _authorization_id()
    identity_id = get_identity_id()
    result = get_copilot_device_flow_service().poll(
        identity_id,
        authorization_id,
    )
    if result.get("status") == "connected":
        copilot_capability_store.invalidate_identity(identity_id)
    return json_ok(result)


@copilot_auth_bp.route("/device/cancel", methods=["POST"])
def cancel_copilot_device_flow():
    _require_enabled()
    authorization_id = _authorization_id()
    result = get_copilot_device_flow_service().cancel(
        get_identity_id(),
        authorization_id,
    )
    return json_ok(result)


@copilot_auth_bp.route("/disconnect", methods=["POST"])
def disconnect_copilot():
    _require_enabled()
    _json_object()
    identity_id = get_identity_id()
    result = get_copilot_device_flow_service().disconnect(identity_id)
    copilot_capability_store.invalidate_identity(identity_id)
    return json_ok(result)
