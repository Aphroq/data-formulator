# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flask
import pytest

from data_formulator.analyst.agent import AnalystAgent
from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextProgress,
    BusinessContextResult,
    ContextItem,
)
from data_formulator.analyst.business_context.trustgraph import TrustGraphClient


pytestmark = [pytest.mark.backend]


def _model_response(*, content: str = "", tool_name: str | None = None, args=None):
    tool_calls = None
    finish_reason = "stop"
    if tool_name is not None:
        finish_reason = "tool_calls"
        tool_calls = [SimpleNamespace(
            id=f"call-{tool_name}",
            function=SimpleNamespace(
                name=tool_name,
                arguments=json.dumps(args or {}),
            ),
        )]
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=None,
        ),
        finish_reason=finish_reason,
    )])


def _workspace(tmp_path: Path):
    return SimpleNamespace(
        user_home=None,
        confined_scratch=SimpleNamespace(root=tmp_path / "scratch"),
    )


def _trustgraph_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTGRAPH_ENABLED", "true")
    monkeypatch.setenv("DF_ALLOWED_API_BASES", "https://trustgraph.example/*")
    monkeypatch.setenv("TRUSTGRAPH_TARGETS_JSON", json.dumps({
        "default": {
            "api_base": "https://trustgraph.example",
            "flow_id": "policy-flow",
            "trace_collection": "business-context-traces",
            "agent_group": "data-formulator-readonly",
            "trustgraph_workspace": "knowledge-workspace",
            "credential_ref": "trustgraph:reader",
        },
    }))


def _event_lines(response) -> list[dict]:
    return [
        json.loads(line)
        for line in response.data.decode("utf-8").splitlines()
    ]


@pytest.fixture()
def agents_client():
    from data_formulator.routes.agents import agent_bp

    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    app.config["CLI_ARGS"] = {}
    app.register_blueprint(agent_bp)
    return app.test_client()


def test_analyst_uses_backend_authorized_workspace_not_request_payload(
    agents_client,
) -> None:
    workspace = SimpleNamespace(user_home=None)

    with (
        patch(
            "data_formulator.routes.agents.get_identity_id",
            return_value="user:42",
        ),
        patch(
            "data_formulator.routes.agents.get_workspace",
            return_value=workspace,
        ),
        patch(
            "data_formulator.routes.agents.get_client",
            return_value=object(),
        ),
        patch("data_formulator.routes.agents.AnalystAgent") as analyst_agent,
    ):
        analyst_agent.return_value.run.return_value = iter([{
            "type": "completion",
            "message": "done",
        }])
        response = agents_client.post(
            "/api/agent/analyst-streaming",
            headers={"X-Workspace-Id": "workspace-authorized"},
            json={
                "model": {},
                "input_tables": [],
                "user_question": "question",
                "workspace_id": "workspace-attacker",
                "identity_id": "identity-attacker",
            },
        )

    assert response.status_code == 200
    assert json.loads(response.data.decode("utf-8").strip())["type"] == "completion"
    constructor_kwargs = analyst_agent.call_args.kwargs
    assert constructor_kwargs["identity_id"] == "user:42"
    assert constructor_kwargs["workspace_id"] == "workspace-authorized"


def test_business_context_status_is_hidden_when_feature_is_disabled(
    agents_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTGRAPH_ENABLED", raising=False)

    response = agents_client.get(
        "/api/agent/business-context-status",
        headers={"X-Workspace-Id": "workspace-status"},
    )

    assert response.get_json()["data"] == {"status": "disabled"}


def test_business_context_status_reports_request_scope_configuration_without_querying(
    agents_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trustgraph_environment(monkeypatch)

    class Vault:
        def retrieve(self, identity_id: str, source_key: str):
            assert identity_id == "user:42"
            assert source_key == "trustgraph:reader"
            return {"bearer_token": "reader-token"}

    with (
        patch("data_formulator.routes.agents.get_identity_id", return_value="user:42"),
        patch(
            "data_formulator.analyst.business_context.trustgraph_provider._default_vault_getter",
            return_value=Vault(),
        ),
        patch.object(TrustGraphClient, "query") as query,
    ):
        response = agents_client.get(
            "/api/agent/business-context-status",
            headers={"X-Workspace-Id": "workspace-status"},
        )

    assert response.get_json()["data"] == {"status": "configured"}
    query.assert_not_called()


def test_business_context_status_is_unconfigured_without_reader_credential(
    agents_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trustgraph_environment(monkeypatch)
    vault = SimpleNamespace(retrieve=lambda identity_id, source_key: None)

    with (
        patch("data_formulator.routes.agents.get_identity_id", return_value="user:42"),
        patch(
            "data_formulator.analyst.business_context.trustgraph_provider._default_vault_getter",
            return_value=vault,
        ),
    ):
        response = agents_client.get(
            "/api/agent/business-context-status",
            headers={"X-Workspace-Id": "workspace-status"},
        )

    assert response.get_json()["data"] == {"status": "unconfigured"}


def test_full_user_request_discovers_then_uses_ready_business_context_skill(
    agents_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _trustgraph_environment(monkeypatch)
    vault_calls: list[tuple[str, str]] = []
    provider_queries = []
    llm_rounds: list[dict] = []

    class Vault:
        def retrieve(self, identity_id: str, source_key: str):
            vault_calls.append((identity_id, source_key))
            return {"bearer_token": "reader-token"}

    def query_stream(self, request, *, bearer_token: str):
        provider_queries.append((request, bearer_token))
        yield BusinessContextProgress(1, "searching")
        yield BusinessContextProgress(1, "completed")
        return BusinessContextResult(
            text=json.dumps({
                "operation": "business_context",
                "answer": "Code X7 belongs to the Review classification.",
                "sources": [{"uri": "https://example.com/classification"}],
            }),
            context_items=(
                ContextItem(
                    uri="https://example.com/classification",
                    title="Classification standard",
                    provider="trustgraph",
                ),
                ContextItem(
                    uri="urn:trustgraph:agent:session-user-flow",
                    title="TrustGraph retrieval trace",
                    provider="trustgraph",
                    kind="trace",
                ),
            ),
        )

    responses = [
        _model_response(tool_name="load_skill", args={"name": "trustgraph"}),
        _model_response(
            tool_name="query_business_context",
            args={
                "question": "Which governed classification should code X7 use?",
                "context": (
                    "Blocked operation: standardize category_code before grouping. "
                    "Source role: coded observations. Relevant field: "
                    "category_code (string). Representative values: X7, Q2."
                ),
            },
        ),
        _model_response(content=(
            "已核对业务知识：X7 应归入 Review 分类；后续分组应使用该映射。"
        )),
    ]

    def scripted_stream(self, messages, tools):
        if False:
            yield None
        llm_rounds.append({
            "system": messages[0]["content"],
            "tool_names": [tool["function"]["name"] for tool in tools],
            "messages": [dict(message) for message in messages],
        })
        return responses.pop(0)

    with (
        patch("data_formulator.routes.agents.get_identity_id", return_value="user:42"),
        patch("data_formulator.routes.agents.get_workspace", return_value=_workspace(tmp_path)),
        patch(
            "data_formulator.routes.agents.get_client",
            return_value=SimpleNamespace(model="scripted-model"),
        ),
        patch(
            "data_formulator.analyst.business_context.trustgraph_provider._default_vault_getter",
            return_value=Vault(),
        ),
        patch.object(TrustGraphClient, "query_stream", new=query_stream),
        patch.object(AnalystAgent, "_stream_llm", new=scripted_stream),
    ):
        response = agents_client.post(
            "/api/agent/analyst-streaming",
            headers={"X-Workspace-Id": "workspace-user-flow"},
            json={
                "model": {},
                "input_tables": [],
                "user_question": (
                    "清洗 category_code 后按类别汇总；X7 的业务归类我不确定。"
                ),
            },
        )
        events = _event_lines(response)

    assert response.status_code == 200
    assert "trustgraph" in llm_rounds[0]["system"].lower()
    assert "query_business_context" not in llm_rounds[0]["tool_names"]
    assert "query_business_context" in llm_rounds[1]["tool_names"]
    assert any(
        "UNTRUSTED_TRUSTGRAPH_DATA" in str(message.get("content", ""))
        for message in llm_rounds[2]["messages"]
    )
    assert len(provider_queries) == 1
    assert provider_queries[0][0].identity_id == "user:42"
    assert provider_queries[0][0].workspace_id == "workspace-user-flow"
    assert provider_queries[0][1] == "reader-token"
    assert vault_calls == [
        ("user:42", "trustgraph:reader"),
        ("user:42", "trustgraph:reader"),
    ]
    loaded = next(event for event in events if event["type"] == "skill_loaded")
    assert loaded["tools"] == ["query_business_context"]
    assert [
        (event["query_index"], event["phase"])
        for event in events
        if event["type"] == "tool_progress"
    ] == [(1, "searching"), (1, "completed")]
    context_event = next(event for event in events if event.get("tool") == "query_business_context" and event["type"] == "context_info")
    assert [item["kind"] for item in context_event["context_items"]] == [
        "source",
        "trace",
    ]
    assert events[-1]["type"] == "completion"
    assert "Review" in events[-1]["content"]["summary"]


@pytest.mark.parametrize("user_question", [
    "按我给定的规则把 X7 固定映射为 Alpha，不需要解释业务含义。",
    "只把字段 category_code 重命名为 category，不改变任何值。",
])
def test_full_user_request_skips_lookup_for_explicit_or_mechanical_rules(
    agents_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    user_question: str,
) -> None:
    _trustgraph_environment(monkeypatch)
    llm_rounds: list[dict] = []

    class Vault:
        def retrieve(self, identity_id: str, source_key: str):
            return {"bearer_token": "reader-token"}

    def scripted_stream(self, messages, tools):
        if False:
            yield None
        llm_rounds.append({
            "system": messages[0]["content"],
            "tool_names": [tool["function"]["name"] for tool in tools],
        })
        return _model_response(content="已按用户明确规则处理，无需查询业务知识。")

    with (
        patch("data_formulator.routes.agents.get_identity_id", return_value="user:42"),
        patch("data_formulator.routes.agents.get_workspace", return_value=_workspace(tmp_path)),
        patch(
            "data_formulator.routes.agents.get_client",
            return_value=SimpleNamespace(model="scripted-model"),
        ),
        patch(
            "data_formulator.analyst.business_context.trustgraph_provider._default_vault_getter",
            return_value=Vault(),
        ),
        patch.object(TrustGraphClient, "query") as query,
        patch.object(AnalystAgent, "_stream_llm", new=scripted_stream),
    ):
        response = agents_client.post(
            "/api/agent/analyst-streaming",
            headers={"X-Workspace-Id": "workspace-user-flow"},
            json={
                "model": {},
                "input_tables": [],
                "user_question": user_question,
            },
        )
        events = _event_lines(response)

    assert len(llm_rounds) == 1
    assert "trustgraph" in llm_rounds[0]["system"].lower()
    assert "query_business_context" not in llm_rounds[0]["tool_names"]
    query.assert_not_called()
    assert not any(event["type"] == "skill_loaded" for event in events)
    assert events[-1]["type"] == "completion"


def test_full_user_request_does_not_invent_when_ready_provider_becomes_unavailable(
    agents_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _trustgraph_environment(monkeypatch)

    class Vault:
        def retrieve(self, identity_id: str, source_key: str):
            return {"bearer_token": "reader-token"}

    responses = [
        _model_response(tool_name="load_skill", args={"name": "trustgraph"}),
        _model_response(
            tool_name="query_business_context",
            args={"question": "What governed meaning does code X7 have?"},
        ),
        _model_response(content=(
            "业务知识服务当前不可用，无法可靠确定 X7 的含义；我不会据此改值。"
        )),
    ]

    def scripted_stream(self, messages, tools):
        if False:
            yield None
        return responses.pop(0)

    def unavailable(self, request, *, bearer_token: str):
        raise BusinessContextError(BusinessContextErrorCategory.UNAVAILABLE)

    with (
        patch("data_formulator.routes.agents.get_identity_id", return_value="user:42"),
        patch("data_formulator.routes.agents.get_workspace", return_value=_workspace(tmp_path)),
        patch(
            "data_formulator.routes.agents.get_client",
            return_value=SimpleNamespace(model="scripted-model"),
        ),
        patch(
            "data_formulator.analyst.business_context.trustgraph_provider._default_vault_getter",
            return_value=Vault(),
        ),
        patch.object(TrustGraphClient, "query", new=unavailable),
        patch.object(AnalystAgent, "_stream_llm", new=scripted_stream),
    ):
        response = agents_client.post(
            "/api/agent/analyst-streaming",
            headers={"X-Workspace-Id": "workspace-user-flow"},
            json={
                "model": {},
                "input_tables": [],
                "user_question": "清洗 code 字段，但 X7 的业务含义不明确。",
            },
        )
        events = _event_lines(response)

    failure = next(
        event for event in events
        if event.get("tool") == "query_business_context"
        and event["type"] == "tool_result"
    )
    assert failure["status"] == "error"
    assert "unavailable" in failure["error"]
    assert events[-1]["type"] == "completion"
    assert "不会据此改值" in events[-1]["content"]["summary"]
