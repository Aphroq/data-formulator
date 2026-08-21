# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Identity-scoped TrustGraph connection profiles.

Profiles contain only connection routing. Reader tokens remain in the existing
credential vault and are referenced by a deterministic, workspace-scoped key.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from data_formulator.analyst.business_context.trustgraph import TrustGraphTarget
from data_formulator.datalake.workspace import get_user_home


DEFAULT_FLOW_ID = "default"
DEFAULT_TOOL_GROUP = "data-formulator-readonly"
DEFAULT_TRACE_COLLECTION = "business-context-traces"
_FILENAME = "trustgraph_profiles.json"
_lock = threading.Lock()


def credential_ref_for_workspace(workspace_id: str) -> str:
    digest = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:32]
    return f"trustgraph:workspace:{digest}"


def _path(identity_id: str) -> Path:
    return get_user_home(identity_id) / _FILENAME


def _read(path: Path) -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, dict)
    }


def _write(path: Path, profiles: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{_FILENAME}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profiles, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def make_target(
    *,
    workspace_id: str,
    api_base: str,
    trustgraph_workspace: str,
    flow_id: str = DEFAULT_FLOW_ID,
    tool_group: str = DEFAULT_TOOL_GROUP,
) -> TrustGraphTarget:
    return TrustGraphTarget(
        api_base=api_base,
        flow_id=flow_id,
        trace_collection=DEFAULT_TRACE_COLLECTION,
        agent_group=tool_group,
        trustgraph_workspace=trustgraph_workspace,
        credential_ref=credential_ref_for_workspace(workspace_id),
    )


def load_workspace_profile(
    identity_id: str,
    workspace_id: str,
) -> TrustGraphTarget | None:
    with _lock:
        item = _read(_path(identity_id)).get(workspace_id)
    if item is None:
        return None
    try:
        return make_target(workspace_id=workspace_id, **item)
    except (TypeError, ValueError):
        return None


def save_workspace_profile(
    identity_id: str,
    workspace_id: str,
    *,
    api_base: str,
    trustgraph_workspace: str,
    flow_id: str = DEFAULT_FLOW_ID,
    tool_group: str = DEFAULT_TOOL_GROUP,
) -> TrustGraphTarget:
    target = make_target(
        workspace_id=workspace_id,
        api_base=api_base,
        trustgraph_workspace=trustgraph_workspace,
        flow_id=flow_id,
        tool_group=tool_group,
    )
    item = {
        "api_base": target.api_base,
        "trustgraph_workspace": target.trustgraph_workspace,
        "flow_id": target.flow_id,
        "tool_group": target.agent_group,
    }
    path = _path(identity_id)
    with _lock:
        profiles = _read(path)
        profiles[workspace_id] = item
        _write(path, profiles)
    return target


def delete_workspace_profile(identity_id: str, workspace_id: str) -> bool:
    path = _path(identity_id)
    with _lock:
        profiles = _read(path)
        existed = workspace_id in profiles
        if not existed:
            return False
        del profiles[workspace_id]
        _write(path, profiles)
    return True


def target_to_public_dict(target: TrustGraphTarget) -> dict[str, Any]:
    return {
        "api_base": target.api_base,
        "trustgraph_workspace": target.trustgraph_workspace,
        "flow_id": target.flow_id,
        "tool_group": target.agent_group,
    }


__all__ = [
    "DEFAULT_FLOW_ID",
    "DEFAULT_TOOL_GROUP",
    "credential_ref_for_workspace",
    "delete_workspace_profile",
    "load_workspace_profile",
    "make_target",
    "save_workspace_profile",
    "target_to_public_dict",
]
