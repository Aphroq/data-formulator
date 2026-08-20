# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from typing import Any

import pytest

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextQuery,
    BusinessContextResult,
)
from data_formulator.analyst.business_context.trustgraph_provider import (
    TrustGraphProvider,
    resolve_trustgraph_provider,
)
from data_formulator.analyst.skills import SkillAuthorization


pytestmark = [pytest.mark.backend]

_ALLOWLIST = "https://trustgraph.example/*"
_TOKEN = "trustgraph-test-token"


class _Response:
    status_code = 200

    def __init__(self, payload: Any = None) -> None:
        self.payload = payload or {"answer": "Applicable business rule."}

    def json(self) -> Any:
        return self.payload


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        return _Response()


class _Vault:
    def __init__(
        self,
        credentials: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.credentials = credentials
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def retrieve(self, identity_id: str, source_key: str) -> dict | None:
        self.calls.append((identity_id, source_key))
        if self.error is not None:
            raise self.error
        return self.credentials


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[BusinessContextQuery, str]] = []

    def query(
        self,
        request: BusinessContextQuery,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        self.calls.append((request, bearer_token))
        return BusinessContextResult(text='{"operation":"business_context"}')


def _target_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "name": "governed-business-context",
        "api_base": "https://trustgraph.example",
        "flow_id": "policy-flow",
        "collection": "governed-terms",
        "agent_group": "data-formulator-readonly",
        "trustgraph_workspace": "knowledge-workspace",
        "credential_ref": "trustgraph:governed-context",
    }
    config.update(overrides)
    return config


def _environment(targets: dict[str, Any] | None = None) -> dict[str, str]:
    return {
        "TRUSTGRAPH_ENABLED": "true",
        "TRUSTGRAPH_TARGETS_JSON": json.dumps(
            targets or {"workspace-good": _target_config()},
        ),
    }


def _authorization(
    *,
    identity_id: str = "user:42",
    workspace_id: str = "workspace-good",
) -> SkillAuthorization:
    return SkillAuthorization(
        identity_id=identity_id,
        workspace_id=workspace_id,
    )


def _query(
    *,
    identity_id: str = "user:42",
    workspace_id: str = "workspace-good",
) -> BusinessContextQuery:
    return BusinessContextQuery(
        text="Which states count as waiting for this quality calculation?",
        context=(
            "Relevant fields: state (string). "
            "Representative values: PENDING, HELD, DONE."
        ),
        identity_id=identity_id,
        workspace_id=workspace_id,
    )


def test_resolver_fails_closed_before_loading_vault_when_disabled() -> None:
    def unexpected_vault_access():
        raise AssertionError("vault must not be accessed while disabled")

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment={},
            vault_getter=unexpected_vault_access,
        )

    assert captured.value.category is BusinessContextErrorCategory.DISABLED


def test_resolver_uses_authorized_scope_server_target_and_vault_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    session = _Session()
    vault = _Vault({"bearer_token": _TOKEN})

    provider = resolve_trustgraph_provider(
        _authorization(),
        environment=_environment(),
        vault_getter=lambda: vault,
        session=session,
    )
    result = provider.query(_query())

    assert json.loads(result.text)["answer"] == "Applicable business rule."
    assert vault.calls == [("user:42", "trustgraph:governed-context")]
    assert len(session.calls) == 1
    _, kwargs = session.calls[0]
    assert kwargs["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert kwargs["json"]["workspace"] == "knowledge-workspace"
    assert kwargs["json"]["collection"] == "governed-terms"
    assert kwargs["json"]["group"] == ["data-formulator-readonly"]
    assert "user:42" not in kwargs["json"]["question"]
    assert "workspace-good" not in kwargs["json"]["question"]


def test_provider_delegates_one_provider_neutral_query() -> None:
    authorization = _authorization()
    client = _RecordingClient()
    provider = TrustGraphProvider(
        client,  # type: ignore[arg-type]
        bearer_token=_TOKEN,
        authorization=authorization,
    )
    request = _query()

    result = provider.query(request)

    assert json.loads(result.text) == {"operation": "business_context"}
    assert client.calls == [(request, _TOKEN)]
    assert repr(provider) == "TrustGraphProvider()"
    assert _TOKEN not in repr(provider)


@pytest.mark.parametrize(
    ("identity_id", "workspace_id"),
    [
        ("attacker", "workspace-good"),
        ("user:42", "workspace-attacker"),
    ],
)
def test_provider_rejects_scope_substitution_before_client_call(
    identity_id: str,
    workspace_id: str,
) -> None:
    client = _RecordingClient()
    provider = TrustGraphProvider(
        client,  # type: ignore[arg-type]
        bearer_token=_TOKEN,
        authorization=_authorization(),
    )

    with pytest.raises(BusinessContextError) as captured:
        provider.query(_query(
            identity_id=identity_id,
            workspace_id=workspace_id,
        ))

    assert captured.value.category is BusinessContextErrorCategory.UNAUTHORIZED
    assert client.calls == []


@pytest.mark.parametrize(
    "environment",
    [
        {"TRUSTGRAPH_ENABLED": "true"},
        {
            "TRUSTGRAPH_ENABLED": "true",
            "TRUSTGRAPH_TARGETS_JSON": "not-json",
        },
        _environment({"another-workspace": _target_config()}),
        _environment({"workspace-good": _target_config(
            credential_ref="inline-secret",
        )}),
        _environment({"workspace-good": _target_config(
            ontology_id="legacy-field",
        )}),
        _environment({"workspace-good": _target_config(
            max_sparql_chars=32_000,
        )}),
    ],
)
def test_invalid_or_legacy_target_mapping_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=environment,
            vault_getter=lambda: _Vault({"bearer_token": _TOKEN}),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


@pytest.mark.parametrize(
    "credentials",
    [None, {}, {"bearer_token": ""}, {"bearer_token": 42}],
)
def test_missing_or_invalid_vault_credential_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    credentials: dict | None,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=_environment(),
            vault_getter=lambda: _Vault(credentials),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


def test_vault_exception_is_replaced_with_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    secret = "should-not-escape"

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=_environment(),
            vault_getter=lambda: _Vault(error=RuntimeError(secret)),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED
    assert secret not in str(captured.value)
    assert secret not in repr(captured.value)
