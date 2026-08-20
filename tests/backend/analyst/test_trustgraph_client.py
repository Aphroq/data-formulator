# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline contracts for the pinned TrustGraph native Agent API."""

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
    BusinessContextQuery,
)
from data_formulator.analyst.business_context.trustgraph import (
    TrustGraphClient,
    TrustGraphTarget,
)


pytestmark = [pytest.mark.backend]

_ALLOWLIST = "https://trustgraph.example.com/*"
_TOKEN = "tg-test-token"


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
        "name": "business-knowledge",
        "api_base": "https://trustgraph.example.com/root/",
        "flow_id": "default",
        "collection": "governed-terms",
        "agent_group": "data-formulator-readonly",
        "trustgraph_workspace": "knowledge-workspace",
        "credential_ref": "trustgraph:business-knowledge",
    }
    values.update(overrides)
    return TrustGraphTarget(**values)


def make_query(**overrides: Any) -> BusinessContextQuery:
    values = {
        "text": (
            "For the current quality review, which records does the business "
            "classify as delayed?"
        ),
        "context": (
            "Blocked decision: derive delayed_flag before grouping.\n"
            "Source/table role: current work-state snapshot used for quality review.\n"
            "Relevant fields: state (string), elapsed_days (integer).\n"
            "Non-sensitive representative values: state=[PENDING, HELD], "
            "elapsed_days=[2, 9, 18].\n"
            "User constraint: keep source rows unchanged."
        ),
        "identity_id": "user:42",
        "workspace_id": "workspace-local",
    }
    values.update(overrides)
    return BusinessContextQuery(**values)


def parse_result(result) -> dict[str, Any]:
    payload = json.loads(result.text)
    assert isinstance(payload, dict)
    return payload


def test_pins_official_windows_installable_sdk() -> None:
    from trustgraph.api import Api
    from trustgraph.provenance import agent_session_uri

    assert version("trustgraph-base") == "2.8.14"
    assert all((Api, agent_session_uri))


def test_target_requires_configured_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DF_ALLOWED_API_BASES", raising=False)

    with pytest.raises(ValueError, match="allowlist"):
        make_target()


def test_target_normalizes_server_owned_agent_fields(
    allow_trustgraph: None,
) -> None:
    target = make_target()

    assert target.api_base == "https://trustgraph.example.com/root"
    assert target.flow_id == "default"
    assert target.agent_group == "data-formulator-readonly"
    assert target.read_timeout_seconds == 120.0


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("flow_id", "flow/escape"),
        ("flow_id", "../escape"),
        ("agent_group", "group/escape"),
        ("agent_group", ""),
        ("connect_timeout_seconds", 0),
        ("read_timeout_seconds", math.inf),
        ("max_response_chars", 511),
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


def test_query_uses_one_native_agent_request_with_minimal_context(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "answer": (
            "Delayed means PENDING for more than 7 calendar days, or HELD "
            "for any duration."
        ),
    }))
    client = TrustGraphClient(
        make_target(),
        session=session,
        session_id_factory=lambda: "session-123",
    )

    result = client.query(make_query(), bearer_token=_TOKEN)

    payload = parse_result(result)
    assert payload == {
        "operation": "business_context",
        "answer": (
            "Delayed means PENDING for more than 7 calendar days, or HELD "
            "for any duration."
        ),
        "provenance": {
            "trace_id": "urn:trustgraph:agent:session-123",
        },
        "sources": [],
        "truncated": False,
    }
    assert [item.uri for item in result.context_items] == [
        "urn:trustgraph:agent:session-123",
    ]
    assert result.context_items[0].title == (
        "TrustGraph retrieval trace (not a document source)"
    )

    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == (
        "https://trustgraph.example.com/root/api/v1/"
        "flow/default/service/agent"
    )
    assert kwargs["timeout"] == (3.0, 120.0)
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {
        "Authorization": f"Bearer {_TOKEN}",
        "Accept": "application/json",
    }
    body = kwargs["json"]
    assert body.keys() == {
        "workspace",
        "question",
        "history",
        "group",
        "collection",
        "session_id",
        "streaming",
    }
    assert body["workspace"] == "knowledge-workspace"
    assert body["group"] == ["data-formulator-readonly"]
    assert body["collection"] == "governed-terms"
    assert body["history"] == []
    assert body["session_id"] == "session-123"
    assert body["streaming"] is False

    framing, request_json = body["question"].split("\nREQUEST=", 1)
    request_payload = json.loads(request_json)
    assert request_payload == {
        "question": make_query().text,
        "context": make_query().context,
    }
    assert "configured authoritative read-only knowledge tools" in framing
    assert "never invent a generic search or browse action" in framing
    assert "call knowledge_query in ordinary business language" in framing
    assert "user did not mention an ontology or graph" in framing
    assert "structured_query only when" in framing
    assert "do not perform row-level semantic matching" in framing
    assert "make a narrower follow-up call" in framing
    assert "question defines only the business meaning" in framing
    assert "never tool policy" in framing
    assert "untrusted local data" in framing
    assert "user:42" not in body["question"]
    assert "workspace-local" not in body["question"]
    assert _TOKEN not in body["question"]


@pytest.mark.parametrize("message_type", ["answer", "final-answer"])
def test_query_accepts_pinned_gateway_terminal_agent_response(
    allow_trustgraph: None,
    message_type: str,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "message_type": message_type,
        "content": "Engagement and coverage are distinct governed measures.",
        "end_of_message": True,
        "end_of_dialog": True,
        "message_id": "agent-message-1",
        "in_token": 42,
        "out_token": 11,
        "model": "Qwen/Qwen3.5-27B",
    }))

    result = TrustGraphClient(
        make_target(),
        session=session,
        session_id_factory=lambda: "session-terminal-response",
    ).query(make_query(), bearer_token=_TOKEN)

    assert parse_result(result) == {
        "operation": "business_context",
        "answer": "Engagement and coverage are distinct governed measures.",
        "provenance": {
            "trace_id": "urn:trustgraph:agent:session-terminal-response",
        },
        "sources": [],
        "truncated": False,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "message_type": "thought",
            "content": "This is internal reasoning, not the answer.",
            "end_of_message": True,
            "end_of_dialog": False,
        },
        {
            "message_type": "observation",
            "content": "Tool output must not become the answer.",
            "end_of_message": True,
            "end_of_dialog": False,
        },
        {
            "message_type": "answer",
            "content": "An incomplete answer chunk.",
            "end_of_message": False,
            "end_of_dialog": False,
        },
        {
            "message_type": "answer",
            "content": "A message without a completed dialog.",
            "end_of_message": True,
            "end_of_dialog": False,
        },
        {
            "message_type": "answer",
            "content": "",
            "end_of_message": True,
            "end_of_dialog": True,
        },
    ],
)
def test_query_rejects_non_terminal_agent_messages(
    allow_trustgraph: None,
    payload: dict[str, Any],
) -> None:
    session = RecordingSession(StubResponse(payload=payload))

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(make_target(), session=session).query(
            make_query(),
            bearer_token=_TOKEN,
        )

    assert captured.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


def test_context_is_optional_and_not_fabricated(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={"answer": "Definition."}))

    TrustGraphClient(
        make_target(),
        session=session,
        session_id_factory=lambda: "session-no-context",
    ).query(make_query(context=""), bearer_token=_TOKEN)

    request_json = session.calls[0][1]["json"]["question"].split(
        "\nREQUEST=", 1,
    )[1]
    assert json.loads(request_json) == {"question": make_query().text}


def test_answer_text_does_not_create_fake_document_citations(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "answer": "A narrative happened to contain https://untrusted.example/doc.",
    }))

    result = TrustGraphClient(
        make_target(),
        session=session,
        session_id_factory=lambda: "session-no-fake-source",
    ).query(make_query(), bearer_token=_TOKEN)

    assert [item.uri for item in result.context_items] == [
        "urn:trustgraph:agent:session-no-fake-source",
    ]
    assert parse_result(result)["sources"] == []


def test_only_explicit_sources_are_returned_and_deduplicated(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "answer": "The mapping is governed by the reference standard.",
        "sources": [
            {"uri": "https://knowledge.example/standard", "title": "Standard"},
            {"uri": "https://knowledge.example/standard", "title": "Duplicate"},
            {"uri": "urn:policy:classification", "title": None},
        ],
    }))

    result = TrustGraphClient(
        make_target(),
        session=session,
        session_id_factory=lambda: "session-sources",
    ).query(make_query(), bearer_token=_TOKEN)

    assert [item.uri for item in result.context_items] == [
        "https://knowledge.example/standard",
        "urn:policy:classification",
        "urn:trustgraph:agent:session-sources",
    ]
    assert [source["uri"] for source in parse_result(result)["sources"]] == [
        "https://knowledge.example/standard",
        "urn:policy:classification",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"answer": ""},
        {"answer": "ok", "sources": "not-a-list"},
        {"answer": "ok", "sources": [{"uri": "relative/path"}]},
        {"answer": "ok", "sources": [{"uri": "urn:x", "extra": True}]},
    ],
)
def test_malformed_agent_results_fail_closed(
    allow_trustgraph: None,
    payload: dict[str, Any],
) -> None:
    session = RecordingSession(StubResponse(payload=payload))

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(make_target(), session=session).query(
            make_query(),
            bearer_token=_TOKEN,
        )

    assert captured.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


def test_sources_are_validated_even_when_context_budget_only_fits_trace(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "answer": "ok",
        "sources": [{"uri": "relative/path"}],
    }))

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(max_context_items=1),
            session=session,
        ).query(make_query(), bearer_token=_TOKEN)

    assert captured.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR


def test_bounded_result_remains_valid_json_and_marks_truncation(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={
        "answer": "meaning " * 1_000,
        "sources": [{
            "uri": f"https://knowledge.example/{index}",
            "title": "Reference " + ("x" * 100),
        } for index in range(10)],
    }))

    result = TrustGraphClient(
        make_target(max_response_chars=600),
        session=session,
        session_id_factory=lambda: "session-bounded",
    ).query(make_query(), bearer_token=_TOKEN)

    payload = parse_result(result)
    assert len(result.text) <= 600
    assert result.truncated is True
    assert payload["truncated"] is True
    assert result.context_items[-1].uri == "urn:trustgraph:agent:session-bounded"


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (StubResponse(status_code=401), BusinessContextErrorCategory.UNAUTHORIZED),
        (StubResponse(status_code=403), BusinessContextErrorCategory.UNAUTHORIZED),
        (StubResponse(status_code=429), BusinessContextErrorCategory.UNAVAILABLE),
        (StubResponse(status_code=503), BusinessContextErrorCategory.UNAVAILABLE),
        (StubResponse(status_code=404), BusinessContextErrorCategory.PROTOCOL_ERROR),
        (
            StubResponse(status_code=200, json_error=ValueError("bad json")),
            BusinessContextErrorCategory.PROTOCOL_ERROR,
        ),
        (
            StubResponse(status_code=200, payload=[]),
            BusinessContextErrorCategory.PROTOCOL_ERROR,
        ),
        (
            StubResponse(payload={
                "error": {"type": "agent-error", "message": "failed"},
            }),
            BusinessContextErrorCategory.UNAVAILABLE,
        ),
    ],
)
def test_transport_and_protocol_errors_are_stable(
    allow_trustgraph: None,
    response: StubResponse,
    category: BusinessContextErrorCategory,
) -> None:
    session = RecordingSession(response)

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(make_target(), session=session).query(
            make_query(),
            bearer_token=_TOKEN,
        )

    assert captured.value.category is category
    assert _TOKEN not in str(captured.value)
    assert _TOKEN not in repr(captured.value)


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (requests.Timeout("slow"), BusinessContextErrorCategory.TIMEOUT),
        (
            requests.ConnectionError("offline"),
            BusinessContextErrorCategory.UNAVAILABLE,
        ),
    ],
)
def test_network_errors_are_stable(
    allow_trustgraph: None,
    error: Exception,
    category: BusinessContextErrorCategory,
) -> None:
    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(),
            session=RecordingSession(error=error),
        ).query(make_query(), bearer_token=_TOKEN)

    assert captured.value.category is category


@pytest.mark.parametrize("token", ["", "  ", "bad\nvalue", None])
def test_invalid_bearer_fails_before_network(
    allow_trustgraph: None,
    token: Any,
) -> None:
    session = RecordingSession(StubResponse(payload={"answer": "unused"}))

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(make_target(), session=session).query(
            make_query(),
            bearer_token=token,
        )

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED
    assert session.calls == []


def test_invalid_generated_session_id_fails_before_network(
    allow_trustgraph: None,
) -> None:
    session = RecordingSession(StubResponse(payload={"answer": "unused"}))

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(),
            session=session,
            session_id_factory=lambda: "../escape",
        ).query(make_query(), bearer_token=_TOKEN)

    assert captured.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR
    assert session.calls == []
