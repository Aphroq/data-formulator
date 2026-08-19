# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from typing import Any

import pytest

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextResult,
)
from data_formulator.analyst.business_context.trustgraph import (
    TrustGraphEntitySearch,
    TrustGraphRowsQuery,
    TrustGraphSparqlQuery,
    TrustGraphTripleQuery,
)
from data_formulator.analyst.business_context.trustgraph_provider import (
    TrustGraphProvider,
    resolve_trustgraph_provider,
)
from data_formulator.analyst.skills import SkillAuthorization


pytestmark = [pytest.mark.backend]

_ALLOWLIST = "https://trustgraph.example/*"
_TOKEN = "trustgraph-secret-token"


class _Response:
    status_code = 200

    def __init__(self, payload: Any = None) -> None:
        self.payload = payload or {
            "values": [{
                "type": "ontology",
                "key": "finance-ontology",
                "value": {"metadata": {}, "classes": []},
            }],
        }

    def json(self) -> Any:
        return self.payload


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        return _Response()


class _Vault:
    def __init__(self, credentials: dict | None = None) -> None:
        self.credentials = credentials
        self.calls: list[tuple[str, str]] = []

    def retrieve(self, identity_id: str, source_key: str) -> dict | None:
        self.calls.append((identity_id, source_key))
        return self.credentials


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str]] = []

    def inspect_catalog(self, *, bearer_token: str) -> BusinessContextResult:
        self.calls.append(("catalog", None, bearer_token))
        return BusinessContextResult(text='{"operation":"catalog"}')

    def search_entities(
        self,
        query: TrustGraphEntitySearch,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        self.calls.append(("entities", query, bearer_token))
        return BusinessContextResult(text='{"operation":"entity_search"}')

    def query_rows(
        self,
        query: TrustGraphRowsQuery,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        self.calls.append(("rows", query, bearer_token))
        return BusinessContextResult(text='{"operation":"rows"}')


def _target_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "name": "finance-policy",
        "api_base": "https://trustgraph.example",
        "flow_id": "policy-flow",
        "collection": "finance",
        "trustgraph_workspace": "policy-workspace",
        "ontology_id": "finance-ontology",
        "credential_ref": "trustgraph:finance-policy",
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


def test_resolver_uses_authorized_workspace_identity_and_bound_ontology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    session = _Session()
    vault = _Vault({"bearer_token": _TOKEN})
    environment = _environment({
        "workspace-good": _target_config(),
        "workspace-attacker": _target_config(
            name="attacker",
            flow_id="attacker-flow",
            ontology_id="attacker-ontology",
            credential_ref="trustgraph:attacker",
        ),
    })

    provider = resolve_trustgraph_provider(
        _authorization(),
        environment=environment,
        vault_getter=lambda: vault,
        session=session,
    )
    result = provider.get_ontology(_authorization())

    assert isinstance(provider, TrustGraphProvider)
    assert json.loads(result.text)["ontology_id"] == "finance-ontology"
    assert vault.calls == [("user:42", "trustgraph:finance-policy")]
    url, kwargs = session.calls[0]
    assert url.endswith("/api/v1/config")
    assert kwargs["json"]["workspace"] == "policy-workspace"
    assert kwargs["json"]["keys"] == [{
        "type": "ontology",
        "key": "finance-ontology",
    }]
    assert kwargs["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert repr(provider) == "TrustGraphProvider()"
    assert _TOKEN not in repr(provider)
    assert "finance-policy" not in repr(provider)


def test_provider_delegates_discovery_and_rows_queries_with_bound_token() -> None:
    client = _RecordingClient()
    provider = TrustGraphProvider(
        client,
        bearer_token=_TOKEN,
        authorization=_authorization(),
    )
    query = TrustGraphEntitySearch(query="invoice", limit=4)
    rows_query = TrustGraphRowsQuery(query="{ invoices { id } }")

    catalog = provider.inspect_catalog(_authorization())
    entities = provider.search_entities(query, _authorization())
    rows = provider.query_rows(rows_query, _authorization())

    assert json.loads(catalog.text)["operation"] == "catalog"
    assert json.loads(entities.text)["operation"] == "entity_search"
    assert json.loads(rows.text)["operation"] == "rows"
    assert client.calls == [
        ("catalog", None, _TOKEN),
        ("entities", query, _TOKEN),
        ("rows", rows_query, _TOKEN),
    ]


@pytest.mark.parametrize(
    "operation",
    ["catalog", "entities", "rows", "ontology", "triples", "sparql"],
)
def test_bound_provider_rejects_scope_mismatch_without_http(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    session = _Session()
    provider = resolve_trustgraph_provider(
        _authorization(),
        environment=_environment(),
        vault_getter=lambda: _Vault({"bearer_token": _TOKEN}),
        session=session,
    )
    attacker = _authorization(workspace_id="workspace-attacker")

    with pytest.raises(BusinessContextError) as captured:
        if operation == "catalog":
            provider.inspect_catalog(attacker)
        elif operation == "entities":
            provider.search_entities(
                TrustGraphEntitySearch(query="invoice", limit=1),
                attacker,
            )
        elif operation == "rows":
            provider.query_rows(
                TrustGraphRowsQuery(query="{ invoices { id } }"),
                attacker,
            )
        elif operation == "ontology":
            provider.get_ontology(attacker)
        elif operation == "triples":
            provider.query_triples(TrustGraphTripleQuery(limit=1), attacker)
        else:
            provider.query_sparql(
                TrustGraphSparqlQuery(query="ASK { <urn:s> ?p ?o }", limit=1),
                attacker,
            )

    assert captured.value.category is BusinessContextErrorCategory.UNAUTHORIZED
    assert session.calls == []


@pytest.mark.parametrize(
    ("targets", "credentials"),
    [
        ({"another-workspace": _target_config()}, {"bearer_token": _TOKEN}),
        ({"workspace-good": _target_config()}, None),
        ({"workspace-good": _target_config()}, {}),
        ({"workspace-good": _target_config()}, {"access_token": _TOKEN}),
        ({
            "workspace-good": _target_config(
                credential_ref="github-copilot",
            ),
        }, {"bearer_token": _TOKEN}),
    ],
)
def test_resolver_fails_closed_for_missing_mapping_or_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    targets: dict[str, Any],
    credentials: dict | None,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=_environment(targets),
            vault_getter=lambda: _Vault(credentials),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


@pytest.mark.parametrize(
    "raw_targets",
    [
        "not-json",
        "[]",
        json.dumps({"workspace-good": "not-an-object"}),
        json.dumps({
            "workspace-good": _target_config(
                api_base="https://leaked-token@trustgraph.example",
            ),
        }),
        json.dumps({
            "workspace-good": _target_config(graph_rag_tuning={}),
        }),
        "x" * 262_145,
    ],
    ids=[
        "invalid-json",
        "not-object",
        "target-not-object",
        "target-with-userinfo",
        "unknown-legacy-field",
        "oversized",
    ],
)
def test_resolver_rejects_malformed_target_config_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    raw_targets: str,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)
    environment = {
        "TRUSTGRAPH_ENABLED": "true",
        "TRUSTGRAPH_TARGETS_JSON": raw_targets,
    }

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=environment,
            vault_getter=lambda: _Vault({"bearer_token": _TOKEN}),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED
    rendered = f"{captured.value!s} {captured.value!r}"
    assert "leaked-token" not in rendered
    assert _TOKEN not in rendered


def test_resolver_cleans_vault_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)

    class FailingVault:
        def retrieve(self, identity_id: str, source_key: str) -> dict | None:
            raise RuntimeError("vault-secret internal failure")

    with pytest.raises(BusinessContextError) as captured:
        resolve_trustgraph_provider(
            _authorization(),
            environment=_environment(),
            vault_getter=lambda: FailingVault(),
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED
    rendered = f"{captured.value!s} {captured.value!r}"
    assert "vault-secret" not in rendered
    assert "internal failure" not in rendered
