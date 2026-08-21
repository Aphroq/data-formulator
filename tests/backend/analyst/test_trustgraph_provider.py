# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from typing import Any

import pytest
from trustgraph.api.types import AgentAnswer

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextProgress,
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


class _ExplainFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, str, str]] = []
        self.closed = 0

    def __call__(self, target, token, question, session_id):
        self.calls.append((target, token, question, session_id))

        def close() -> None:
            self.closed += 1

        return iter([AgentAnswer(
            content="Applicable business rule.",
            end_of_message=True,
            end_of_dialog=True,
        )]), close


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
        self.stream_calls: list[tuple[BusinessContextQuery, str]] = []

    def query(
        self,
        request: BusinessContextQuery,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        self.calls.append((request, bearer_token))
        return BusinessContextResult(text='{"operation":"business_context"}')

    def query_stream(
        self,
        request: BusinessContextQuery,
        *,
        bearer_token: str,
    ):
        self.stream_calls.append((request, bearer_token))
        yield BusinessContextProgress(1, "searching")
        return BusinessContextResult(text='{"operation":"business_context"}')


def _target_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "api_base": "https://trustgraph.example",
        "flow_id": "policy-flow",
        "trace_collection": "business-context-traces",
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
    factory = _ExplainFactory()
    vault = _Vault({"bearer_token": _TOKEN})

    provider = resolve_trustgraph_provider(
        _authorization(),
        environment=_environment(),
        vault_getter=lambda: vault,
        explain_iterator_factory=factory,
    )
    result = provider.query(_query())

    assert json.loads(result.text)["answer"] == "Applicable business rule."
    assert vault.calls == [("user:42", "trustgraph:governed-context")]
    assert len(factory.calls) == 1
    target, token, question, _ = factory.calls[0]
    assert token == _TOKEN
    assert target.trustgraph_workspace == "knowledge-workspace"
    assert target.trace_collection == "business-context-traces"
    assert target.agent_group == "data-formulator-readonly"
    assert "user:42" not in question
    assert "workspace-good" not in question
    assert factory.closed == 1


def test_resolver_uses_default_target_when_workspace_has_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    vault = _Vault({"bearer_token": _TOKEN})

    provider = resolve_trustgraph_provider(
        _authorization(workspace_id="workspace-without-override"),
        environment=_environment({"default": _target_config(
            credential_ref="trustgraph:default-context",
        )}),
        vault_getter=lambda: vault,
    )

    assert isinstance(provider, TrustGraphProvider)
    assert vault.calls == [
        ("user:42", "trustgraph:default-context"),
    ]


def test_resolver_prefers_exact_workspace_target_over_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    vault = _Vault({"bearer_token": _TOKEN})

    provider = resolve_trustgraph_provider(
        _authorization(),
        environment=_environment({
            "default": _target_config(
                credential_ref="trustgraph:default-context",
            ),
            "workspace-good": _target_config(
                credential_ref="trustgraph:workspace-context",
            ),
        }),
        vault_getter=lambda: vault,
    )

    assert isinstance(provider, TrustGraphProvider)
    assert vault.calls == [
        ("user:42", "trustgraph:workspace-context"),
    ]


def test_resolver_rejects_collection_instead_of_treating_it_as_an_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    target = _target_config()
    target["collection"] = target.pop("trace_collection")

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=_environment({"workspace-good": target}),
            vault_getter=lambda: _Vault({"bearer_token": _TOKEN}),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


def test_resolver_requires_trace_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    target = _target_config()
    target.pop("trace_collection")

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=_environment({"workspace-good": target}),
            vault_getter=lambda: _Vault({"bearer_token": _TOKEN}),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


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


def test_provider_delegates_progress_and_stream_result() -> None:
    authorization = _authorization()
    client = _RecordingClient()
    provider = TrustGraphProvider(
        client,  # type: ignore[arg-type]
        bearer_token=_TOKEN,
        authorization=authorization,
    )
    request = _query()
    stream = provider.query_stream(request)

    assert next(stream) == BusinessContextProgress(1, "searching")
    with pytest.raises(StopIteration) as completed:
        next(stream)

    assert json.loads(completed.value.value.text) == {
        "operation": "business_context",
    }
    assert client.stream_calls == [(request, _TOKEN)]


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
        _environment({"workspace-good": _target_config(
            name="legacy-name",
        )}),
        _environment({"workspace-good": _target_config(
            connect_timeout_seconds=3,
        )}),
        _environment({"workspace-good": _target_config(
            read_timeout_seconds=120,
        )}),
        _environment({"workspace-good": _target_config(
            max_context_items=50,
        )}),
    ],
)
def test_invalid_target_mapping_fails_closed(
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
