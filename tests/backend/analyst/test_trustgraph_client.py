# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline contracts for the pinned TrustGraph ontology/graph Python API."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from importlib.metadata import version
from typing import Any

import pytest
import requests

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
)
from data_formulator.analyst.business_context.trustgraph import (
    PROVENANCE_GRAPH_IRI,
    TrustGraphClient,
    TrustGraphEntitySearch,
    TrustGraphRdfTerm,
    TrustGraphRowsQuery,
    TrustGraphSparqlQuery,
    TrustGraphTarget,
    TrustGraphTripleQuery,
    validate_sparql_query,
)


pytestmark = [pytest.mark.backend]

_ALLOWLIST = "https://trustgraph.example.com/*"
_TOKEN = "tg-secret-token"


@dataclass
class StubResponse:
    status_code: int = 200
    payload: Any = field(default_factory=dict)
    json_error: Exception | None = None

    def json(self) -> Any:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class RecordingSession:
    def __init__(
        self,
        *responses: StubResponse,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses) or [StubResponse()]
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


@pytest.fixture
def allow_trustgraph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)


def make_target(**overrides: Any) -> TrustGraphTarget:
    values: dict[str, Any] = {
        "name": "finance-prod",
        "api_base": "https://trustgraph.example.com/root/",
        "flow_id": "default",
        "collection": "policies",
        "trustgraph_workspace": "finance",
        "ontology_id": "finance-ontology",
        "credential_ref": "trustgraph:finance-prod",
        "max_results": 100,
    }
    values.update(overrides)
    return TrustGraphTarget(**values)


def parse_result(result) -> dict[str, Any]:
    payload = json.loads(result.text)
    assert isinstance(payload, dict)
    return payload


def test_pins_official_windows_installable_sdk() -> None:
    from trustgraph.api import Api, ConfigKey
    from trustgraph.messaging.translators.primitives import (
        TermTranslator,
        TripleTranslator,
    )

    assert version("trustgraph-base") == "2.8.14"
    assert all((Api, ConfigKey, TermTranslator, TripleTranslator))


def test_target_requires_configured_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DF_ALLOWED_API_BASES", raising=False)

    with pytest.raises(ValueError, match="allowlist"):
        make_target()


def test_target_normalizes_server_owned_fields(allow_trustgraph: None) -> None:
    target = make_target()

    assert target.api_base == "https://trustgraph.example.com/root"
    assert target.flow_id == "default"
    assert target.ontology_id == "finance-ontology"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("flow_id", "flow/escape"),
        ("flow_id", "../escape"),
        ("ontology_id", ""),
        ("max_results", 0),
        ("max_results", 1001),
        ("max_sparql_chars", 0),
        ("max_context_items", 101),
    ],
)
def test_target_rejects_unsafe_or_unbounded_fields(
    allow_trustgraph: None,
    field_name: str,
    value: Any,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_target(**{field_name: value})


def test_ontology_uses_official_config_get_and_safe_request(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "values": [{
            "type": "ontology",
            "key": "finance-ontology",
            "value": {
                "metadata": {"name": "Finance"},
                "classes": [{"id": "https://example.com/Invoice"}],
                "objectProperties": [],
                "datatypeProperties": [],
            },
        }],
    }))
    client = TrustGraphClient(make_target(), session=session)

    result = client.get_ontology(bearer_token=_TOKEN)

    payload = parse_result(result)
    assert payload["operation"] == "ontology"
    assert payload["ontology_id"] == "finance-ontology"
    assert payload["ontology"]["metadata"]["name"] == "Finance"
    assert result.context_items[0].uri == "https://example.com/Invoice"
    url, kwargs = session.calls[0]
    assert url == "https://trustgraph.example.com/root/api/v1/config"
    assert kwargs["json"] == {
        "operation": "get",
        "workspace": "finance",
        "keys": [{"type": "ontology", "key": "finance-ontology"}],
    }
    assert kwargs["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (3.0, 30.0)


def test_ontology_accepts_json_string_value(allow_trustgraph: None) -> None:
    session = RecordingSession(StubResponse(payload={
        "values": [{
            "type": "ontology",
            "key": "finance-ontology",
            "value": json.dumps({"metadata": {}, "classes": []}),
        }],
    }))

    result = TrustGraphClient(make_target(), session=session).get_ontology(
        bearer_token=_TOKEN,
    )

    assert parse_result(result)["ontology"]["classes"] == []


@pytest.mark.parametrize(
    "values",
    [
        [],
        [{
            "type": "ontology",
            "key": "finance-ontology",
            "value": None,
        }],
    ],
)
def test_ontology_missing_exact_bound_key_fails_closed(
    allow_trustgraph: None,
    values: list[dict[str, Any]],
) -> None:
    session = RecordingSession(StubResponse(payload={"values": values}))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).get_ontology(
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


def test_catalog_uses_official_sdk_and_normalizes_resources(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(
        StubResponse(payload={"flow-ids": ["default", "research"]}),
        StubResponse(payload={
            "collections": [{
                "collection": "policies",
                "name": "Policies",
                "description": "Policy collection",
                "tags": ["finance"],
            }],
        }),
        StubResponse(payload={
            "document-metadatas": [{
                "id": "doc-1",
                "kind": "application/pdf",
                "title": "Policy.pdf",
                "metadata": [],
                "tags": ["policy"],
                "document-type": "source",
            }],
        }),
        StubResponse(payload={
            "processing-metadatas": [{
                "id": "processing-1",
                "document-id": "doc-1",
                "flow": "default",
                "collection": "policies",
                "tags": ["policy"],
            }],
        }),
        StubResponse(payload={"ids": ["core-1"]}),
    )

    result = TrustGraphClient(make_target(), session=session).inspect_catalog(
        bearer_token=_TOKEN,
    )

    payload = parse_result(result)
    assert payload == {
        "operation": "catalog",
        "active": {
            "flow_id": "default",
            "collection": "policies",
            "ontology_id": "finance-ontology",
        },
        "flows": ["default", "research"],
        "collections": [{
            "id": "policies",
            "name": "Policies",
            "description": "Policy collection",
            "tags": ["finance"],
        }],
        "documents": [{
            "id": "doc-1",
            "title": "Policy.pdf",
            "kind": "application/pdf",
            "tags": ["policy"],
            "parent_id": None,
            "document_type": "source",
            "created_at": None,
        }],
        "processing": [{
            "id": "processing-1",
            "document_id": "doc-1",
            "flow": "default",
            "collection": "policies",
            "tags": ["policy"],
            "started_at": None,
        }],
        "knowledge_cores": ["core-1"],
    }
    assert [url.rsplit("/api/v1/", 1)[1] for url, _ in session.calls] == [
        "flow",
        "collection-management",
        "librarian",
        "librarian",
        "knowledge",
    ]
    assert [kwargs["json"] for _, kwargs in session.calls] == [
        {"operation": "list-flows", "workspace": "finance"},
        {"operation": "list-collections", "workspace": "finance"},
        {
            "operation": "list-documents",
            "workspace": "finance",
            "include-children": False,
        },
        {"operation": "list-processing", "workspace": "finance"},
        {"operation": "list-kg-cores", "workspace": "finance"},
    ]


def test_catalog_maps_sdk_shape_drift_to_protocol_error(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={"flows": []}))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).inspect_catalog(
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


def test_catalog_accepts_empty_official_resource_lists(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(
        StubResponse(payload={"flow-ids": []}),
        StubResponse(payload={"collections": []}),
        StubResponse(payload={"document-metadatas": []}),
        StubResponse(payload={"processing-metadatas": []}),
        StubResponse(payload={"ids": []}),
    )

    payload = parse_result(
        TrustGraphClient(make_target(), session=session).inspect_catalog(
            bearer_token=_TOKEN,
        ),
    )

    assert payload["flows"] == []
    assert payload["collections"] == []
    assert payload["documents"] == []
    assert payload["processing"] == []
    assert payload["knowledge_cores"] == []


def test_entity_search_uses_official_embedding_services_and_decodes_terms(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(
        StubResponse(payload={"vectors": [[0.25, -0.5, 1.0]]}),
        StubResponse(payload={
            "entities": [
                {
                    "entity": {
                        "t": "i",
                        "i": "https://example.com/invoice/1",
                    },
                    "score": 0.97,
                },
                {
                    "entity": {"t": "l", "v": "Invoice", "ln": "en"},
                    "score": 0.75,
                },
                {
                    "entity": {"t": "i", "i": "urn:ignored"},
                    "score": 0.5,
                },
            ],
        }),
    )
    client = TrustGraphClient(make_target(), session=session)

    result = client.search_entities(
        TrustGraphEntitySearch(query="overdue invoices", limit=2),
        bearer_token=_TOKEN,
    )

    payload = parse_result(result)
    assert payload == {
        "operation": "entity_search",
        "query": "overdue invoices",
        "entities": [
            {
                "entity": {
                    "type": "iri",
                    "value": "https://example.com/invoice/1",
                },
                "score": 0.97,
            },
            {
                "entity": {
                    "type": "literal",
                    "value": "Invoice",
                    "language": "en",
                },
                "score": 0.75,
            },
        ],
        "truncated": True,
    }
    assert result.truncated is True
    assert result.context_items[0].uri == "https://example.com/invoice/1"
    assert session.calls[0][0].endswith(
        "/api/v1/flow/default/service/embeddings",
    )
    assert session.calls[0][1]["json"] == {
        "workspace": "finance",
        "texts": ["overdue invoices"],
    }
    assert session.calls[1][0].endswith(
        "/api/v1/flow/default/service/graph-embeddings",
    )
    assert session.calls[1][1]["json"] == {
        "workspace": "finance",
        "vector": [0.25, -0.5, 1.0],
        "collection": "policies",
        "limit": 2,
    }


@pytest.mark.parametrize(
    "values",
    [None, [], [[]], [["bad"]], [[math.nan]], [[[0.5]]]],
)
def test_entity_search_rejects_malformed_embedding_vectors(
    allow_trustgraph: None,
    values: Any,
) -> None:
    session = RecordingSession(StubResponse(payload={"vectors": values}))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).search_entities(
            TrustGraphEntitySearch(query="invoice", limit=2),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"entities": "not-a-list"},
        {
            "entities": [{
                "entity": {"t": "i", "i": "urn:invoice"},
                "score": "high",
            }],
        },
    ],
)
def test_entity_search_rejects_malformed_results(
    allow_trustgraph: None,
    payload: dict[str, Any],
) -> None:
    session = RecordingSession(
        StubResponse(payload={"vectors": [[0.5]]}),
        StubResponse(payload=payload),
    )

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).search_entities(
            TrustGraphEntitySearch(query="invoice", limit=2),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


def test_entity_search_accepts_no_matches(allow_trustgraph: None) -> None:
    session = RecordingSession(
        StubResponse(payload={"vectors": [[0.5]]}),
        StubResponse(payload={"entities": []}),
    )

    result = TrustGraphClient(make_target(), session=session).search_entities(
        TrustGraphEntitySearch(query="unknown concept", limit=3),
        bearer_token=_TOKEN,
    )

    assert parse_result(result)["entities"] == []
    assert result.truncated is False


def test_entity_search_respects_bound_target_result_limit(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession()

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(
            make_target(max_results=2),
            session=session,
        ).search_entities(
            TrustGraphEntitySearch(query="invoice", limit=3),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.INVALID_REQUEST
    assert session.calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": "invoice", "limit": 0},
        {"query": "invoice", "limit": 1001},
        {"query": "invoice", "limit": True},
    ],
)
def test_entity_search_value_object_rejects_invalid_queries(
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        TrustGraphEntitySearch(**kwargs)


def test_rows_query_uses_official_sdk_and_preserves_graphql_result(
    allow_trustgraph: None,
) -> None:
    graphql = """
        query ListInvoices($status: String!) {
          invoices(status: $status) { id amount source }
        }
    """
    session = RecordingSession(StubResponse(payload={
        "data": {
            "invoices": [{
                "id": "INV-1",
                "amount": 42.5,
                "source": "https://example.com/invoice/1",
            }],
        },
        "extensions": {"query_id": "query-1"},
    }))

    result = TrustGraphClient(make_target(), session=session).query_rows(
        TrustGraphRowsQuery(
            query=graphql,
            variables={"status": "open"},
            operation_name="ListInvoices",
        ),
        bearer_token=_TOKEN,
    )

    payload = parse_result(result)
    assert payload == {
        "operation": "rows",
        "data": {
            "invoices": [{
                "id": "INV-1",
                "amount": 42.5,
                "source": "https://example.com/invoice/1",
            }],
        },
        "errors": [],
        "extensions": {"query_id": "query-1"},
    }
    assert result.context_items[0].uri == "https://example.com/invoice/1"
    url, kwargs = session.calls[0]
    assert url.endswith("/api/v1/flow/default/service/rows")
    assert kwargs["json"] == {
        "workspace": "finance",
        "query": graphql.strip(),
        "collection": "policies",
        "variables": {"status": "open"},
        "operation_name": "ListInvoices",
    }


def test_rows_query_returns_graphql_errors_as_structured_evidence(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "errors": [{
            "message": "Unknown field",
            "path": ["invoices"],
        }],
    }))

    result = TrustGraphClient(make_target(), session=session).query_rows(
        TrustGraphRowsQuery(query="{ invoices { missing } }"),
        bearer_token=_TOKEN,
    )

    payload = parse_result(result)
    assert payload["data"] is None
    assert payload["errors"] == [{
        "message": "Unknown field",
        "path": ["invoices"],
    }]
    assert payload["extensions"] is None


def test_rows_query_maps_missing_graphql_schema_to_not_configured(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "error": {
            "type": "rows-query-error",
            "message": (
                "No GraphQL schema available for workspace finance "
                "- no schemas loaded"
            ),
        },
    }))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).query_rows(
            TrustGraphRowsQuery(query="query Smoke { __typename }"),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.NOT_CONFIGURED


def test_rows_query_keeps_other_service_errors_unavailable(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "error": {
            "type": "rows-query-error",
            "message": "Rows query processor failed",
        },
    }))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).query_rows(
            TrustGraphRowsQuery(query="query Smoke { __typename }"),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.UNAVAILABLE


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": []},
        {"errors": "not-a-list"},
        {"data": {}, "extensions": [{"unexpected": True}]},
    ],
)
def test_rows_query_rejects_malformed_graphql_results(
    allow_trustgraph: None,
    response: dict[str, Any],
) -> None:
    session = RecordingSession(StubResponse(payload=response))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).query_rows(
            TrustGraphRowsQuery(query="{ invoices { id } }"),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": "{ invoices { id } }", "variables": []},
        {"query": "{ invoices { id } }", "variables": {1: "bad"}},
        {"query": "{ invoices { id } }", "variables": {"bad": {1, 2}}},
        {"query": "{ invoices { id } }", "operation_name": ""},
    ],
)
def test_rows_query_value_object_rejects_invalid_arguments(
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        TrustGraphRowsQuery(**kwargs)


def test_triples_query_preserves_typed_literal_and_default_graph(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "response": [{
            "s": {"t": "i", "i": "https://example.com/invoice/1"},
            "p": {"t": "i", "i": "https://example.com/amount"},
            "o": {
                "t": "l",
                "v": "42.50",
                "dt": "http://www.w3.org/2001/XMLSchema#decimal",
            },
        }],
    }))
    client = TrustGraphClient(make_target(), session=session)
    query = TrustGraphTripleQuery(
        subject="https://example.com/invoice/1",
        predicate="https://example.com/amount",
        object=TrustGraphRdfTerm(
            kind="literal",
            value="42.50",
            datatype="http://www.w3.org/2001/XMLSchema#decimal",
        ),
        graph="knowledge",
        limit=10,
    )

    result = client.query_triples(query, bearer_token=_TOKEN)

    payload = parse_result(result)
    assert payload["graph"] == "knowledge"
    assert payload["triples"][0]["object"] == {
        "type": "literal",
        "value": "42.50",
        "datatype": "http://www.w3.org/2001/XMLSchema#decimal",
    }
    url, kwargs = session.calls[0]
    assert url.endswith("/api/v1/flow/default/service/triples")
    assert kwargs["json"] == {
        "workspace": "finance",
        "collection": "policies",
        "limit": 10,
        "streaming": False,
        "g": "",
        "s": {"t": "i", "i": "https://example.com/invoice/1"},
        "p": {"t": "i", "i": "https://example.com/amount"},
        "o": {
            "t": "l",
            "v": "42.50",
            "dt": "http://www.w3.org/2001/XMLSchema#decimal",
        },
    }


def test_triples_query_binds_provenance_named_graph(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={"response": []}))
    client = TrustGraphClient(make_target(), session=session)

    result = client.query_triples(
        TrustGraphTripleQuery(graph="provenance", limit=5),
        bearer_token=_TOKEN,
    )

    assert parse_result(result)["named_graph"] == PROVENANCE_GRAPH_IRI
    assert session.calls[0][1]["json"]["g"] == PROVENANCE_GRAPH_IRI


def test_triples_response_preserves_language_blank_quoted_triple_and_graph(
    allow_trustgraph: None,
) -> None:
    quoted = {
        "t": "t",
        "tr": {
            "s": {"t": "i", "i": "urn:entity:one"},
            "p": {"t": "i", "i": "urn:predicate:label"},
            "o": {"t": "l", "v": "发票", "ln": "zh"},
        },
    }
    session = RecordingSession(StubResponse(payload={
        "response": [{
            "s": {"t": "b", "d": "_:source"},
            "p": {"t": "i", "i": "urn:predicate:asserts"},
            "o": quoted,
            "g": PROVENANCE_GRAPH_IRI,
        }],
    }))

    result = TrustGraphClient(make_target(), session=session).query_triples(
        TrustGraphTripleQuery(graph="provenance", limit=5),
        bearer_token=_TOKEN,
    )

    triple = parse_result(result)["triples"][0]
    assert triple["subject"] == {"type": "blank_node", "value": "_:source"}
    assert triple["object"]["type"] == "quoted_triple"
    assert triple["object"]["triple"]["object"] == {
        "type": "literal",
        "value": "发票",
        "language": "zh",
    }
    assert triple["graph"] == PROVENANCE_GRAPH_IRI


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <urn:s> <urn:p> <urn:o> }",
        "DELETE WHERE { ?s ?p ?o }",
        "SELECT * WHERE { SERVICE <https://example.com/sparql> { ?s ?p ?o } }",
        "SELECT WHERE {",
    ],
)
def test_sparql_validation_rejects_writes_service_and_bad_syntax(
    query: str,
) -> None:
    with pytest.raises(ValueError):
        validate_sparql_query(query, max_chars=8_000)


@pytest.mark.parametrize(
    ("query", "query_type"),
    [
        ("SELECT * WHERE { ?s ?p ?o }", "select"),
        ("ASK { <urn:s> ?p ?o }", "ask"),
        ("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "construct"),
        ("DESCRIBE <urn:s>", "describe"),
    ],
)
def test_sparql_validation_accepts_read_query_forms(
    query: str,
    query_type: str,
) -> None:
    assert validate_sparql_query(query, max_chars=8_000) == query_type


def test_sparql_uses_official_sdk_endpoint_and_normalizes_bindings(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "query-type": "select",
        "variables": ["s", "label"],
        "bindings": [{
            "values": [
                {"t": "i", "i": "https://example.com/invoice/1"},
                {"t": "l", "v": "发票", "ln": "zh"},
            ],
        }],
    }))
    client = TrustGraphClient(make_target(), session=session)

    result = client.query_sparql(
        TrustGraphSparqlQuery(
            query="SELECT ?s ?label WHERE { ?s <urn:label> ?label }",
            limit=20,
        ),
        bearer_token=_TOKEN,
    )

    payload = parse_result(result)
    assert payload["query_type"] == "select"
    assert payload["rows"] == [{
        "s": {"type": "iri", "value": "https://example.com/invoice/1"},
        "label": {"type": "literal", "value": "发票", "language": "zh"},
    }]
    url, kwargs = session.calls[0]
    assert url.endswith("/api/v1/flow/default/service/sparql")
    assert kwargs["json"]["workspace"] == "finance"
    assert kwargs["json"]["collection"] == "policies"
    assert kwargs["json"]["limit"] == 20


def test_sparql_rejects_result_type_different_from_parsed_query(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "query-type": "ask",
        "ask-result": True,
    }))

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).query_sparql(
            TrustGraphSparqlQuery(
                query="SELECT * WHERE { ?s ?p ?o }",
                limit=10,
            ),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


def test_response_row_and_size_limits_are_applied_after_server_limit(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "response": [{
            "s": {"t": "i", "i": f"urn:s:{index}"},
            "p": {"t": "i", "i": "urn:p"},
            "o": {"t": "l", "v": "x" * 200},
        } for index in range(5)],
    }))
    client = TrustGraphClient(
        make_target(max_results=2, max_response_chars=220),
        session=session,
    )

    result = client.query_triples(
        TrustGraphTripleQuery(limit=2),
        bearer_token=_TOKEN,
    )

    assert result.truncated is True
    assert len(result.text) <= 220
    assert parse_result(result)["truncated"] is True


@pytest.mark.parametrize(
    ("response", "error", "category"),
    [
        (StubResponse(status_code=401), None, BusinessContextErrorCategory.UNAUTHORIZED),
        (StubResponse(status_code=403), None, BusinessContextErrorCategory.UNAUTHORIZED),
        (StubResponse(status_code=429), None, BusinessContextErrorCategory.UNAVAILABLE),
        (StubResponse(status_code=503), None, BusinessContextErrorCategory.UNAVAILABLE),
        (StubResponse(status_code=302), None, BusinessContextErrorCategory.PROTOCOL_ERROR),
        (
            StubResponse(json_error=ValueError("secret response")),
            None,
            BusinessContextErrorCategory.PROTOCOL_ERROR,
        ),
        (
            StubResponse(),
            requests.ConnectTimeout("secret endpoint"),
            BusinessContextErrorCategory.TIMEOUT,
        ),
        (
            StubResponse(),
            requests.ConnectionError("secret endpoint"),
            BusinessContextErrorCategory.UNAVAILABLE,
        ),
    ],
)
def test_transport_maps_failures_to_secret_free_categories(
    allow_trustgraph: None,
    response: StubResponse,
    error: Exception | None,
    category: BusinessContextErrorCategory,
) -> None:
    session = RecordingSession(response, error=error)

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).query_triples(
            TrustGraphTripleQuery(limit=1),
            bearer_token=_TOKEN,
        )

    assert exc_info.value.category is category
    assert "secret" not in str(exc_info.value).lower()


def test_invalid_token_never_reaches_official_api(allow_trustgraph: None) -> None:
    session = RecordingSession()

    with pytest.raises(BusinessContextError) as exc_info:
        TrustGraphClient(make_target(), session=session).query_triples(
            TrustGraphTripleQuery(limit=1),
            bearer_token="\n",
        )

    assert exc_info.value.category is BusinessContextErrorCategory.NOT_CONFIGURED
    assert session.calls == []
