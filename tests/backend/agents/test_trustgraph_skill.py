# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from data_formulator.analyst.agent import AnalystAgent
from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextResult,
    ContextItem,
)
from data_formulator.analyst.business_context.trustgraph import (
    TrustGraphEntitySearch,
    TrustGraphRowsQuery,
    TrustGraphSparqlQuery,
    TrustGraphTripleQuery,
)
from data_formulator.analyst.skills import (
    SkillAuthorization,
    SkillContext,
    SkillRegistry,
    build_registry,
)
from data_formulator.analyst.skills.trustgraph.skill import TrustGraphSkill


pytestmark = [pytest.mark.backend]

_TOOLS = (
    "inspect_trustgraph_catalog",
    "search_trustgraph_entities",
    "query_trustgraph_rows",
    "inspect_trustgraph_ontology",
    "query_trustgraph_triples",
    "query_trustgraph_sparql",
)


class _Provider:
    def __init__(
        self,
        result: BusinessContextResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or BusinessContextResult(
            text=json.dumps({"operation": "triples", "triples": []}),
        )
        self.error = error
        self.calls: list[tuple[str, object, SkillAuthorization]] = []

    def _return(self):
        if self.error is not None:
            raise self.error
        return self.result

    def get_ontology(self, authorization):
        self.calls.append(("ontology", None, authorization))
        return self._return()

    def inspect_catalog(self, authorization):
        self.calls.append(("catalog", None, authorization))
        return self._return()

    def search_entities(self, query, authorization):
        self.calls.append(("entities", query, authorization))
        return self._return()

    def query_rows(self, query, authorization):
        self.calls.append(("rows", query, authorization))
        return self._return()

    def query_triples(self, query, authorization):
        self.calls.append(("triples", query, authorization))
        return self._return()

    def query_sparql(self, query, authorization):
        self.calls.append(("sparql", query, authorization))
        return self._return()


class _RecordingLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def log(self, step_type: str, **kwargs) -> None:
        self.entries.append({"step_type": step_type, **kwargs})


def _authorization() -> SkillAuthorization:
    return SkillAuthorization("user:42", "workspace-good")


def _context(authorization: SkillAuthorization | None = None) -> SkillContext:
    return SkillContext(
        client=None,
        workspace=object(),
        authorization=authorization,
    )


def _skill(provider: _Provider) -> TrustGraphSkill:
    return TrustGraphSkill(provider_resolver=lambda authorization: provider)


def _registry(skill: TrustGraphSkill) -> SkillRegistry:
    registry = build_registry(environment={"TRUSTGRAPH_ENABLED": "true"})
    registry.skills["trustgraph"] = skill
    return registry


def _response(*, content: str = "", tool_calls=None, finish_reason: str = "stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=content,
                tool_calls=tool_calls,
                reasoning_content=None,
            ),
            finish_reason=finish_reason,
        )],
    )


def _run_agent_tool(
    skill: TrustGraphSkill,
    *,
    raw_arguments: str | None = None,
):
    agent = AnalystAgent(
        client=None,
        workspace=MagicMock(user_home=None),
        skill_registry=_registry(skill),
        identity_id="user:42",
        workspace_id="workspace-good",
    )
    agent._loaded_skills = {"trustgraph"}
    agent._run_payload = {
        "identity_id": "attacker",
        "workspace_id": "workspace-attacker",
    }
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="query_trustgraph_triples",
            arguments=(
                raw_arguments
                if raw_arguments is not None
                else json.dumps({
                    "subject": "urn:invoice:1",
                    "graph": "knowledge",
                    "limit": 5,
                })
            ),
        ),
    )
    responses = [
        _response(tool_calls=[tool_call], finish_reason="tool_calls"),
        _response(content="local fallback answer"),
    ]

    def fake_stream_llm(messages, tools):
        if False:
            yield None
        return responses.pop(0)

    agent._stream_llm = fake_stream_llm
    messages: list[dict] = []
    recording_log = _RecordingLog()
    events = list(agent._tool_loop(
        messages, 2, 1, 0, 0, recording_log, [], 1,
    ))
    return events, messages, recording_log


def test_registry_does_not_import_or_expose_trustgraph_when_disabled() -> None:
    with patch(
        "data_formulator.analyst.skills.importlib.import_module",
        wraps=importlib.import_module,
    ) as importer:
        registry = build_registry(environment={})

    assert not registry.has("trustgraph")
    assert "trustgraph" not in registry.gated_skill_names()
    assert "trustgraph" not in registry.render_registry_block().lower()
    assert all(
        not str(call.args[0]).endswith(".trustgraph.skill")
        for call in importer.call_args_list
    )


def test_registry_exposes_six_read_only_tools_when_enabled() -> None:
    registry = build_registry(environment={"TRUSTGRAPH_ENABLED": "true"})

    assert registry.has("trustgraph")
    meta = registry.metas["trustgraph"]
    assert meta.always_on is False
    assert meta.tool_names == _TOOLS
    assert meta.action_names == ()
    tools = registry.tools_for(["trustgraph"])
    assert tuple(tool["function"]["name"] for tool in tools) == _TOOLS
    for tool in tools:
        parameters = tool["function"]["parameters"]
        assert parameters["additionalProperties"] is False
        assert not {
            "api_base",
            "flow_id",
            "collection",
            "workspace",
            "ontology_id",
            "credential_ref",
        } & set(parameters.get("properties", {}))


def test_registry_guidance_triggers_on_material_task_meaning_not_jargon() -> None:
    registry = build_registry(environment={"TRUSTGRAPH_ENABLED": "true"})

    catalog = registry.render_registry_block()
    body = registry.load_body("trustgraph")
    normalized_body = " ".join(body.split())

    assert "analysis, data preparation, cleaning, transformation" in catalog
    assert "unresolved term, status, category, identifier, measure" in catalog
    assert "does not need to ask a knowledge question or mention TrustGraph" in catalog
    assert "semantic checkpoint inside the user's original task" in normalized_body
    assert "Never require the user to know or supply" in normalized_body
    assert "Do not query merely because a word or column label appears" in normalized_body
    assert "After every result, reassess the original evidence gap" in normalized_body
    assert "do not call all tools mechanically" in normalized_body
    assert "Apply the supported meaning or rule to the original analysis" in normalized_body


def test_skill_inspects_bound_knowledge_catalog_without_arguments() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({
            "operation": "catalog",
            "flows": ["default"],
            "collections": [],
        }),
    ))

    result = _skill(provider).handle_tool(
        "inspect_trustgraph_catalog",
        {},
        _context(_authorization()),
    )

    assert provider.calls == [("catalog", None, _authorization())]
    assert result.public_summary == "TrustGraph knowledge catalog retrieved."
    framed = json.loads(result.text.split("\n", 2)[2])
    assert framed["operation"] == "catalog"
    assert framed["data"]["flows"] == ["default"]


def test_skill_builds_entity_search_from_authorized_context() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({
            "operation": "entity_search",
            "entities": [],
        }),
    ))

    result = _skill(provider).handle_tool(
        "search_trustgraph_entities",
        {"query": "overdue invoice", "limit": 7},
        _context(_authorization()),
    )

    operation, query, authorization = provider.calls[0]
    assert operation == "entities"
    assert isinstance(query, TrustGraphEntitySearch)
    assert query.query == "overdue invoice"
    assert query.limit == 7
    assert authorization == _authorization()
    assert result.public_summary == "TrustGraph entities retrieved."


def test_skill_builds_read_only_graphql_rows_query_without_workspace_writes() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({
            "operation": "rows",
            "data": {"invoices": [{"id": "INV-1"}]},
            "errors": [],
            "extensions": None,
        }),
    ))

    class WorkspaceMustNotBeTouched:
        def __getattr__(self, name):
            raise AssertionError(f"workspace access is forbidden: {name}")

    result = _skill(provider).handle_tool(
        "query_trustgraph_rows",
        {
            "query": "query Find($id: ID!) { invoice(id: $id) { id } }",
            "variables": {"id": "INV-1"},
            "operation_name": "Find",
        },
        SkillContext(
            client=None,
            workspace=WorkspaceMustNotBeTouched(),
            authorization=_authorization(),
        ),
    )

    operation, query, authorization = provider.calls[0]
    assert operation == "rows"
    assert isinstance(query, TrustGraphRowsQuery)
    assert query.variables == {"id": "INV-1"}
    assert query.operation_name == "Find"
    assert authorization == _authorization()
    assert result.public_summary == "TrustGraph rows retrieved."
    framed = json.loads(result.text.split("\n", 2)[2])
    assert framed["operation"] == "rows"


def test_skill_reads_bound_ontology_without_model_arguments() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({
            "operation": "ontology",
            "ontology_id": "finance",
            "ontology": {"classes": []},
        }),
    ))

    result = _skill(provider).handle_tool(
        "inspect_trustgraph_ontology",
        {},
        _context(_authorization()),
    )

    assert provider.calls == [("ontology", None, _authorization())]
    assert result.public_summary == "TrustGraph ontology retrieved."
    assert result.text.startswith("[UNTRUSTED_TRUSTGRAPH_DATA]")
    framed = json.loads(result.text.split("\n", 2)[2])
    assert framed["operation"] == "ontology"
    assert framed["data"]["ontology_id"] == "finance"


def test_skill_builds_typed_triples_query_from_authorized_context() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({"operation": "triples", "triples": []}),
        context_items=(ContextItem(
            uri="urn:invoice:1",
            provider="trustgraph",
        ),),
        truncated=True,
    ))

    result = _skill(provider).handle_tool(
        "query_trustgraph_triples",
        {
            "subject": "urn:invoice:1",
            "predicate": "urn:amount",
            "object": {
                "kind": "literal",
                "value": "42.5",
                "datatype": "http://www.w3.org/2001/XMLSchema#decimal",
            },
            "graph": "provenance",
            "limit": 10,
        },
        _context(_authorization()),
    )

    operation, query, authorization = provider.calls[0]
    assert operation == "triples"
    assert isinstance(query, TrustGraphTripleQuery)
    assert query.subject == "urn:invoice:1"
    assert query.object.kind == "literal"
    assert query.graph == "provenance"
    assert authorization == _authorization()
    assert result.context_items == provider.result.context_items
    assert result.public_summary == "TrustGraph triples retrieved."
    assert json.loads(result.text.split("\n", 2)[2])["truncated"] is True


def test_skill_builds_sparql_query_without_target_fields() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({"operation": "sparql", "query_type": "ask"}),
    ))

    result = _skill(provider).handle_tool(
        "query_trustgraph_sparql",
        {"query": "ASK { <urn:s> ?p ?o }", "limit": 3},
        _context(_authorization()),
    )

    operation, query, authorization = provider.calls[0]
    assert operation == "sparql"
    assert isinstance(query, TrustGraphSparqlQuery)
    assert query.query == "ASK { <urn:s> ?p ?o }"
    assert query.limit == 3
    assert authorization == _authorization()
    assert result.public_summary == "TrustGraph SPARQL results retrieved."


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("inspect_trustgraph_catalog", {"collection": "attacker"}),
        ("search_trustgraph_entities", {
            "query": "invoice",
            "flow_id": "attacker",
        }),
        ("query_trustgraph_rows", {
            "query": "{ invoices { id } }",
            "collection": "attacker",
        }),
        ("inspect_trustgraph_ontology", {"ontology_id": "attacker"}),
        ("query_trustgraph_triples", {"flow_id": "attacker"}),
        (
            "query_trustgraph_sparql",
            {
                "query": "ASK { <urn:s> ?p ?o }",
                "workspace": "attacker",
            },
        ),
    ],
)
def test_skill_rejects_target_override_fields(
    tool_name: str,
    args: dict,
) -> None:
    provider = _Provider()

    result = _skill(provider).handle_tool(
        tool_name,
        args,
        _context(_authorization()),
    )

    assert provider.calls == []
    assert result.error_code == "business_context.invalid_request"


def test_skill_rejects_non_string_rdf_term_fields_before_provider() -> None:
    malformed_objects = (
        {"kind": None, "value": "42"},
        {"kind": "literal", "value": 42},
        {"kind": "literal", "value": "42", "datatype": None},
        {"kind": "literal", "value": "42", "language": None},
    )

    for rdf_object in malformed_objects:
        provider = _Provider()
        result = _skill(provider).handle_tool(
            "query_trustgraph_triples",
            {"object": rdf_object},
            _context(_authorization()),
        )

        assert provider.calls == []
        assert result.error_code == "business_context.invalid_request"


def test_skill_fails_closed_without_authorization() -> None:
    result = _skill(_Provider()).handle_tool(
        "inspect_trustgraph_ontology",
        {},
        _context(),
    )

    assert "not_configured" in result.text
    assert result.context_items == ()
    assert result.public_summary == "TrustGraph unavailable (not_configured)."
    assert result.error_code == "business_context.not_configured"


@pytest.mark.parametrize(
    "category",
    [
        BusinessContextErrorCategory.TIMEOUT,
        BusinessContextErrorCategory.NOT_CONFIGURED,
        BusinessContextErrorCategory.UNAUTHORIZED,
    ],
)
def test_agent_recovers_from_stable_business_context_errors(category) -> None:
    provider = _Provider(error=BusinessContextError(category))

    events, messages, recording_log = _run_agent_tool(_skill(provider))

    assert not any(event["type"] == "context_info" for event in events)
    tool_event = next(event for event in events if event["type"] == "tool_result")
    assert tool_event["stdout"] == f"TrustGraph unavailable ({category.value})."
    assert tool_event["status"] == "error"
    assert tool_event["error"] == tool_event["stdout"]
    assert messages[-2]["role"] == "tool"
    assert category.value in messages[-2]["content"]
    assert events[-1]["final_text"] == "local fallback answer"
    serialized_log = json.dumps(recording_log.entries)
    assert category.value in serialized_log
    assert "urn:invoice:1" not in serialized_log
    tool_log = next(
        entry for entry in recording_log.entries
        if entry["step_type"] == "tool_execution"
    )
    assert tool_log["error_code"] == f"business_context.{category.value}"


def test_agent_keeps_no_source_data_out_of_events_and_logs() -> None:
    provider = _Provider(BusinessContextResult(
        text=json.dumps({"sensitive": "no-source answer"}),
    ))

    events, messages, recording_log = _run_agent_tool(_skill(provider))

    assert not any(event["type"] == "context_info" for event in events)
    tool_event = next(event for event in events if event["type"] == "tool_result")
    assert tool_event["stdout"] == "TrustGraph triples retrieved."
    assert "no-source answer" in messages[-2]["content"]
    assert "no-source answer" not in json.dumps({
        "events": events,
        "logs": recording_log.entries,
    })


def test_agent_cleans_unexpected_provider_exception() -> None:
    provider = _Provider(error=RuntimeError("secret-token response body"))

    events, messages, recording_log = _run_agent_tool(_skill(provider))

    serialized = json.dumps({
        "events": events,
        "messages": messages,
        "logs": recording_log.entries,
    })
    assert "secret-token" not in serialized
    assert "response body" not in serialized
    assert "unavailable" in messages[-2]["content"]


def test_agent_rejects_non_object_tool_arguments_and_continues() -> None:
    provider = _Provider()

    events, messages, _ = _run_agent_tool(
        _skill(provider),
        raw_arguments="[]",
    )

    assert provider.calls == []
    assert "invalid_request" in messages[-2]["content"]
    assert events[-1]["final_text"] == "local fallback answer"
