# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Current-workspace TrustGraph connection routes."""

from __future__ import annotations

import os

from flask import Blueprint, request

from data_formulator.auth.identity import get_identity_id
from data_formulator.error_handler import json_ok
from data_formulator.errors import AppError, ErrorCode
from data_formulator.workspace_factory import get_active_workspace_id


trustgraph_connection_bp = Blueprint(
    "trustgraph_connection",
    __name__,
    url_prefix="/api/agent",
)


def _enabled() -> bool:
    from data_formulator.analyst.business_context.trustgraph import (
        is_trustgraph_enabled,
    )

    return is_trustgraph_enabled()


def _scope() -> tuple[str, str]:
    identity_id = get_identity_id()
    workspace_id = get_active_workspace_id()
    if not identity_id:
        raise AppError(ErrorCode.AUTH_REQUIRED, "Identity ID required")
    if not workspace_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "Active workspace required")
    return identity_id, workspace_id


def _configured_target(identity_id: str, workspace_id: str):
    from data_formulator.analyst.business_context.trustgraph_profiles import (
        load_workspace_profile,
    )
    from data_formulator.analyst.business_context.trustgraph_provider import (
        load_server_target,
    )

    target = load_workspace_profile(identity_id, workspace_id)
    if target is not None:
        return target, "workspace"
    try:
        return load_server_target(workspace_id, os.environ), "server"
    except Exception:
        return None, None


def _vault():
    from data_formulator.auth.vault import get_credential_vault

    vault = get_credential_vault()
    if vault is None:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Credential storage is unavailable",
        )
    return vault


def _stored_token(vault, identity_id: str, credential_ref: str) -> str | None:
    credentials = vault.retrieve(identity_id, credential_ref)
    if not isinstance(credentials, dict):
        return None
    token = credentials.get("bearer_token")
    if not isinstance(token, str) or not token.strip():
        return None
    return token.strip()


@trustgraph_connection_bp.route("/business-context-status", methods=["GET"])
def business_context_status():
    """Return request-local TrustGraph configuration without network I/O."""

    if not _enabled():
        return json_ok({"status": "disabled"})
    workspace_id = get_active_workspace_id()
    if not workspace_id:
        return json_ok({"status": "unconfigured"})

    try:
        from data_formulator.analyst.business_context.trustgraph_provider import (
            resolve_trustgraph_provider,
        )
        from data_formulator.analyst.skills.base import SkillAuthorization

        resolve_trustgraph_provider(SkillAuthorization(
            identity_id=get_identity_id(),
            workspace_id=workspace_id,
        ))
    except Exception:
        return json_ok({"status": "unconfigured"})
    return json_ok({"status": "configured"})


@trustgraph_connection_bp.route("/business-context-connection", methods=["GET"])
def get_connection():
    """Return the current workspace's non-secret TrustGraph connection."""

    if not _enabled():
        return json_ok({"status": "disabled", "connection": None})
    identity_id, workspace_id = _scope()
    target, source = _configured_target(identity_id, workspace_id)
    if target is None:
        return json_ok({"status": "unconfigured", "connection": None})

    from data_formulator.analyst.business_context.trustgraph_profiles import (
        target_to_public_dict,
    )

    try:
        has_credential = _stored_token(
            _vault(), identity_id, target.credential_ref,
        ) is not None
    except Exception:
        has_credential = False
    return json_ok({
        "status": "configured" if has_credential else "unconfigured",
        "source": source,
        "connection": {
            **target_to_public_dict(target),
            "has_credential": has_credential,
        },
    })


def _connection_payload(content: object, workspace_id: str):
    if not isinstance(content, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid connection configuration")
    from data_formulator.analyst.business_context.trustgraph_profiles import make_target

    try:
        return make_target(
            workspace_id=workspace_id,
            api_base=content.get("api_base", ""),
            trustgraph_workspace=content.get("trustgraph_workspace", ""),
            flow_id=content.get("flow_id", "default"),
            tool_group=content.get("tool_group", "data-formulator-readonly"),
        )
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Invalid TrustGraph connection configuration",
        ) from exc


def _payload_token(content: dict) -> str | None:
    value = content.get("bearer_token")
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid reader API key")
    token = value.strip()
    if not token or any(
        ord(character) < 32 or ord(character) == 127
        for character in token
    ):
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid reader API key")
    return token


def _connection_token(content: dict, identity_id: str, workspace_id: str, target) -> str:
    token = _payload_token(content)
    if token:
        return token
    vault = _vault()
    token = _stored_token(vault, identity_id, target.credential_ref)
    if token:
        return token
    current, _ = _configured_target(identity_id, workspace_id)
    if (
        current is not None
        and current.api_base == target.api_base
        and current.trustgraph_workspace == target.trustgraph_workspace
    ):
        token = _stored_token(vault, identity_id, current.credential_ref)
    if not token:
        raise AppError(ErrorCode.INVALID_REQUEST, "Reader API key required")
    return token


@trustgraph_connection_bp.route("/business-context-connection", methods=["PUT"])
def save_connection():
    """Save an exact current-workspace connection and its reader token."""

    if not _enabled():
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "TrustGraph is disabled")
    if not request.is_json:
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid request format")
    identity_id, workspace_id = _scope()
    content = request.get_json()
    target = _connection_payload(content, workspace_id)
    token = _connection_token(content, identity_id, workspace_id, target)
    vault = _vault()
    vault.store(identity_id, target.credential_ref, {"bearer_token": token})

    from data_formulator.analyst.business_context.trustgraph_profiles import (
        save_workspace_profile,
        target_to_public_dict,
    )

    saved = save_workspace_profile(
        identity_id,
        workspace_id,
        api_base=target.api_base,
        trustgraph_workspace=target.trustgraph_workspace,
        flow_id=target.flow_id,
        tool_group=target.agent_group,
    )
    return json_ok({
        "status": "configured",
        "source": "workspace",
        "connection": {**target_to_public_dict(saved), "has_credential": True},
    })


@trustgraph_connection_bp.route("/business-context-connection", methods=["DELETE"])
def delete_connection():
    """Remove only the current user's exact workspace override."""

    identity_id, workspace_id = _scope()
    from data_formulator.analyst.business_context.trustgraph_profiles import (
        credential_ref_for_workspace,
        delete_workspace_profile,
    )

    deleted = delete_workspace_profile(identity_id, workspace_id)
    _vault().delete(identity_id, credential_ref_for_workspace(workspace_id))
    target, _ = _configured_target(identity_id, workspace_id)
    status = "unconfigured"
    if target is not None:
        try:
            if _stored_token(_vault(), identity_id, target.credential_ref):
                status = "configured"
        except Exception:
            pass
    return json_ok({"deleted": deleted, "status": status})


@trustgraph_connection_bp.route("/business-context-connection/test", methods=["POST"])
def test_connection():
    """List flows through the official SDK without mutating the profile."""

    if not _enabled():
        raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "TrustGraph is disabled")
    if not request.is_json:
        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid request format")
    identity_id, workspace_id = _scope()
    content = request.get_json()
    target = _connection_payload(content, workspace_id)
    token = _connection_token(content, identity_id, workspace_id, target)

    from trustgraph.api import Api
    from trustgraph.api.exceptions import ProtocolException

    try:
        values = Api(
            url=target.api_base,
            timeout=20,
            token=token,
            workspace=target.trustgraph_workspace,
        ).flow().list()
    except ProtocolException as exc:
        if str(exc).lower().startswith("auth failure:"):
            raise AppError(
                ErrorCode.ACCESS_DENIED,
                "TrustGraph rejected the reader API key",
            ) from exc
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "TrustGraph connection test failed",
            retry=True,
        ) from exc
    except (OSError, TimeoutError) as exc:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "TrustGraph connection test timed out",
            retry=True,
        ) from exc
    except Exception as exc:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "TrustGraph connection test failed",
            retry=True,
        ) from exc

    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "TrustGraph returned an invalid flow list",
        )
    flows = sorted({value.strip() for value in values if value.strip()})
    return json_ok({"flows": flows})


@trustgraph_connection_bp.after_request
def _set_cors(response):
    origin = os.environ.get("CORS_ORIGIN", "")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, PUT, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


__all__ = ["trustgraph_connection_bp"]
