# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve an identity-scoped, read-only TrustGraph provider.

``TRUSTGRAPH_TARGETS_JSON`` maps Data Formulator workspace IDs to validated
server-owned TrustGraph routes.  It stores a credential reference, never a
bearer token; the token is resolved from the existing identity-scoped vault.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from typing import TYPE_CHECKING, Any

import requests

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextQuery,
    BusinessContextResult,
)
from data_formulator.analyst.business_context.trustgraph import (
    TrustGraphClient,
    TrustGraphTarget,
    is_trustgraph_enabled,
)
from data_formulator.analyst.skills.base import SkillAuthorization

if TYPE_CHECKING:
    from data_formulator.auth.vault.base import CredentialVault


TRUSTGRAPH_TARGETS_ENV_KEY = "TRUSTGRAPH_TARGETS_JSON"
MAX_TRUSTGRAPH_TARGETS_JSON_CHARS = 262_144

_TARGET_FIELDS = frozenset({
    "name",
    "api_base",
    "flow_id",
    "collection",
    "agent_group",
    "trustgraph_workspace",
    "credential_ref",
    "connect_timeout_seconds",
    "read_timeout_seconds",
    "max_response_chars",
    "max_context_items",
})

VaultGetter = Callable[[], "CredentialVault | None"]


def _error(category: BusinessContextErrorCategory) -> BusinessContextError:
    return BusinessContextError(category)


def _load_target(
    workspace_id: str,
    environment: Mapping[str, str],
) -> TrustGraphTarget:
    raw_json = environment.get(TRUSTGRAPH_TARGETS_ENV_KEY, "")
    if (
        not isinstance(raw_json, str)
        or not raw_json.strip()
        or len(raw_json) > MAX_TRUSTGRAPH_TARGETS_JSON_CHARS
    ):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    try:
        targets = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED) from exc
    if not isinstance(targets, dict):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    raw_target = targets.get(workspace_id)
    if not isinstance(raw_target, dict):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)
    if any(not isinstance(key, str) for key in raw_target):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)
    if set(raw_target) - _TARGET_FIELDS:
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    values: dict[str, Any] = dict(raw_target)
    values.setdefault("name", workspace_id)
    try:
        return TrustGraphTarget(**values)
    except (TypeError, ValueError) as exc:
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED) from exc


def _default_vault_getter() -> "CredentialVault | None":
    from data_formulator.auth.vault import get_credential_vault

    return get_credential_vault()


class TrustGraphProvider:
    """Official client bound to one authorized identity/workspace scope."""

    __slots__ = (
        "_bearer_token",
        "_client",
        "_identity_id",
        "_workspace_id",
    )

    def __init__(
        self,
        client: TrustGraphClient,
        *,
        bearer_token: str,
        authorization: SkillAuthorization,
    ) -> None:
        self._client = client
        self._bearer_token = bearer_token
        self._identity_id = authorization.identity_id
        self._workspace_id = authorization.workspace_id

    def _check_scope(self, request: BusinessContextQuery) -> None:
        if (
            not isinstance(request, BusinessContextQuery)
            or request.identity_id != self._identity_id
            or request.workspace_id != self._workspace_id
        ):
            raise _error(BusinessContextErrorCategory.UNAUTHORIZED)

    def query(self, request: BusinessContextQuery) -> BusinessContextResult:
        """Resolve one focused question inside the bound authorization scope."""

        self._check_scope(request)
        return self._client.query(
            request,
            bearer_token=self._bearer_token,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def resolve_trustgraph_provider(
    authorization: SkillAuthorization,
    *,
    environment: Mapping[str, str] | None = None,
    vault_getter: VaultGetter | None = None,
    session: requests.Session | None = None,
) -> TrustGraphProvider:
    """Resolve a validated target and identity-scoped bearer credential."""

    source_environment = os.environ if environment is None else environment
    if not is_trustgraph_enabled(source_environment):
        raise _error(BusinessContextErrorCategory.DISABLED)
    if not isinstance(authorization, SkillAuthorization):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    target = _load_target(authorization.workspace_id, source_environment)
    if (
        not target.credential_ref.startswith("trustgraph:")
        or len(target.credential_ref) == len("trustgraph:")
    ):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    get_vault = vault_getter or _default_vault_getter
    try:
        vault = get_vault()
        credentials = (
            vault.retrieve(authorization.identity_id, target.credential_ref)
            if vault is not None
            else None
        )
    except Exception as exc:
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED) from exc
    if not isinstance(credentials, dict):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    bearer_token = credentials.get("bearer_token")
    if not isinstance(bearer_token, str):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)
    bearer_token = bearer_token.strip()
    if not bearer_token or any(
        ord(character) < 32 or ord(character) == 127
        for character in bearer_token
    ):
        raise _error(BusinessContextErrorCategory.NOT_CONFIGURED)

    return TrustGraphProvider(
        TrustGraphClient(target, session=session),
        bearer_token=bearer_token,
        authorization=authorization,
    )


__all__ = [
    "MAX_TRUSTGRAPH_TARGETS_JSON_CHARS",
    "TRUSTGRAPH_TARGETS_ENV_KEY",
    "TrustGraphProvider",
    "resolve_trustgraph_provider",
]
