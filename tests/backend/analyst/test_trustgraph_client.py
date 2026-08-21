# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline contracts for the pinned TrustGraph Agent explain stream."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from importlib.metadata import version
from typing import Any

import pytest
from trustgraph.api.exceptions import ProtocolException, TrustGraphException
from trustgraph.api.explainability import (
    Analysis,
    Conclusion,
    Exploration,
    Focus,
    Grounding,
    Observation,
    Question,
    Reflection,
    Synthesis,
)
from trustgraph.api.types import (
    AgentAnswer,
    AgentObservation,
    AgentThought,
    ProvenanceEvent,
)
from trustgraph.provenance import RDF_TYPE, TG_ACTION, TG_ANALYSIS

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextProgress,
    BusinessContextQuery,
    BusinessContextResult,
)
from data_formulator.analyst.business_context.trustgraph import (
    TrustGraphClient,
    TrustGraphTarget,
)


pytestmark = [pytest.mark.backend]

_ALLOWLIST = "https://trustgraph.example.com/*"
_TOKEN = "tg-test-token"


def make_target(**overrides: Any) -> TrustGraphTarget:
    values: dict[str, Any] = {
        "api_base": "https://trustgraph.example.com/root/",
        "flow_id": "default",
        "trace_collection": "business-context-traces",
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


def provenance(entity: object, event_type: str = "") -> ProvenanceEvent:
    return ProvenanceEvent(
        explain_id="urn:explain:event",
        explain_graph="urn:explain:graph",
        event_type=event_type,
        entity=entity,
        triples=[("secret-subject", "secret-predicate", "secret-object")],
    )


def agent_tool_use_provenance(action: str) -> ProvenanceEvent:
    """Match the wire shape emitted by the pinned Agent runtime."""

    explain_id = "urn:trustgraph:agent:iteration:test"
    subject = {"t": "i", "i": explain_id}
    return ProvenanceEvent(
        explain_id=explain_id,
        explain_graph="urn:graph:retrieval",
        entity=Reflection(uri=explain_id, document="hidden reflection"),
        triples=[
            {
                "s": subject,
                "p": {"t": "i", "i": RDF_TYPE},
                "o": {"t": "i", "i": TG_ANALYSIS},
            },
            {
                "s": subject,
                "p": {"t": "i", "i": TG_ACTION},
                "o": {"t": "l", "v": action},
            },
        ],
    )


def terminal_answer(content: str) -> AgentAnswer:
    return AgentAnswer(
        content=content,
        end_of_message=True,
        end_of_dialog=True,
        message_id="answer-final",
    )


def drain_stream(
    stream: Iterator[BusinessContextProgress],
) -> tuple[list[BusinessContextProgress], BusinessContextResult]:
    progress: list[BusinessContextProgress] = []
    while True:
        try:
            progress.append(next(stream))
        except StopIteration as stop:
            assert isinstance(stop.value, BusinessContextResult)
            return progress, stop.value


class RecordingExplainFactory:
    def __init__(
        self,
        events: list[object] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.events = list(events or [])
        self.error = error
        self.calls: list[tuple[TrustGraphTarget, str, str, str]] = []
        self.close_count = 0

    def __call__(
        self,
        target: TrustGraphTarget,
        token: str,
        question: str,
        session_id: str,
    ) -> tuple[Iterator[object], Any]:
        self.calls.append((target, token, question, session_id))

        def iterator() -> Iterator[object]:
            yield from self.events
            if self.error is not None:
                raise self.error

        def close() -> None:
            self.close_count += 1

        return iterator(), close


@pytest.fixture
def allow_trustgraph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DF_ALLOWED_API_BASES", _ALLOWLIST)


def test_pins_official_windows_installable_sdk_with_agent_explain() -> None:
    from trustgraph.api import Api
    from trustgraph.provenance import agent_session_uri

    assert version("trustgraph-base") == "2.8.14"
    assert callable(Api.socket)
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
    assert target.trace_collection == "business-context-traces"
    assert target.agent_group == "data-formulator-readonly"
    assert target.socket_timeout_seconds == 120.0


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("flow_id", "flow/escape"),
        ("flow_id", "../escape"),
        ("agent_group", "group/escape"),
        ("agent_group", ""),
        ("trace_collection", ""),
        ("socket_timeout_seconds", 0),
        ("socket_timeout_seconds", math.inf),
        ("max_response_chars", 511),
    ],
)
def test_target_rejects_unsafe_or_unbounded_fields(
    allow_trustgraph: None,
    field_name: str,
    value: Any,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_target(**{field_name: value})


def test_query_stream_compresses_two_agent_rounds_and_discards_hidden_content(
    allow_trustgraph: None,
) -> None:
    hidden_values = [
        "secret thought",
        "secret reflection",
        "secret arguments",
        "secret synthesis",
        "secret observation",
    ]
    factory = RecordingExplainFactory([
        AgentThought(content=hidden_values[0], end_of_message=True),
        provenance(Question(uri="urn:question", query="hidden question")),
        provenance(Reflection(uri="urn:reflection", document=hidden_values[1])),
        provenance(Analysis(
            uri="urn:analysis:1",
            action="governed_terms_lookup",
            arguments=hidden_values[2],
            thought="hidden analysis thought",
        )),
        provenance(Grounding(uri="urn:grounding:1", concepts=["hidden concept"])),
        provenance(Exploration(
            uri="urn:exploration:1",
            edge_count=4,
            chunk_count=2,
            entities=["hidden entity"],
        )),
        provenance(Focus(uri="urn:focus:1", selected_edge_uris=["hidden edge"])),
        provenance(Synthesis(uri="urn:synthesis:1", document=hidden_values[3])),
        AgentObservation(content="hidden raw tool output", end_of_message=True),
        provenance(Observation(uri="urn:observation:1", document=hidden_values[4])),
        provenance(Analysis(
            uri="urn:analysis:2",
            action="governed_records_lookup",
            arguments="hidden structured arguments",
        )),
        provenance(Observation(
            uri="urn:observation:2",
            document="hidden structured result",
        )),
        provenance(Conclusion(uri="urn:conclusion", document="hidden conclusion")),
        AgentAnswer(content="Delayed records follow ", message_id="answer-1"),
        terminal_answer("the governed waiting-state rule."),
    ])
    client = TrustGraphClient(
        make_target(),
        explain_iterator_factory=factory,
        session_id_factory=lambda: "session-123",
    )

    progress, result = drain_stream(client.query_stream(
        make_query(),
        bearer_token=_TOKEN,
    ))

    assert [(item.query_index, item.phase) for item in progress] == [
        (1, "searching"),
        (1, "filtering"),
        (1, "summarizing"),
        (1, "completed"),
        (2, "searching"),
        (2, "completed"),
        (None, "finalizing"),
    ]
    payload = json.loads(result.text)
    assert payload == {
        "operation": "business_context",
        "answer": "Delayed records follow the governed waiting-state rule.",
        "provenance": {
            "trace_id": "urn:trustgraph:agent:session-123",
            "query_count": 2,
        },
        "sources": [],
        "truncated": False,
    }
    assert len(result.context_items) == 1
    assert result.context_items[0].uri == "urn:trustgraph:agent:session-123"
    assert result.context_items[0].title == "TrustGraph retrieval trace · 2 queries"
    assert result.context_items[0].kind == "trace"
    serialized = json.dumps({
        "progress": [item.__dict__ for item in progress],
        "result": payload,
    })
    assert not any(value in serialized for value in hidden_values)
    assert "secret-subject" not in serialized
    assert factory.close_count == 1


def test_observation_only_round_gets_one_generic_query(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([
        provenance(Observation(uri="urn:observation", document="hidden")),
        terminal_answer("A governed record was found."),
    ])

    progress, result = drain_stream(TrustGraphClient(
        make_target(),
        explain_iterator_factory=factory,
    ).query_stream(make_query(), bearer_token=_TOKEN))

    assert [(item.query_index, item.phase) for item in progress] == [
        (1, "searching"),
        (1, "completed"),
    ]
    assert json.loads(result.text)["provenance"]["query_count"] == 1


def test_real_agent_tool_use_shape_starts_progress_before_observation(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([
        agent_tool_use_provenance("arbitrary_readonly_lookup"),
    ])
    stream = TrustGraphClient(
        make_target(),
        explain_iterator_factory=factory,
    ).query_stream(make_query(), bearer_token=_TOKEN)

    assert next(stream) == BusinessContextProgress(1, "searching")
    stream.close()
    assert factory.close_count == 1


def test_default_factory_calls_official_socket_agent_explain(
    allow_trustgraph: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {}

    class FakeFlow:
        def agent_explain(self, **kwargs: Any) -> Iterator[object]:
            recorded["agent_explain"] = kwargs
            return iter([terminal_answer("Definition.")])

    class FakeSocket:
        def flow(self, flow_id: str) -> FakeFlow:
            recorded["flow_id"] = flow_id
            return FakeFlow()

        def close(self) -> None:
            recorded["closed"] = True

    class FakeApi:
        def __init__(self, **kwargs: Any) -> None:
            recorded["api"] = kwargs

        def socket(self) -> FakeSocket:
            return FakeSocket()

    monkeypatch.setattr(
        "data_formulator.analyst.business_context.trustgraph.Api",
        FakeApi,
    )
    client = TrustGraphClient(
        make_target(),
        session_id_factory=lambda: "session-official",
    )

    result = client.query(make_query(), bearer_token=_TOKEN)

    assert json.loads(result.text)["answer"] == "Definition."
    assert recorded["api"] == {
        "url": "https://trustgraph.example.com/root",
        "timeout": 120.0,
        "token": _TOKEN,
        "workspace": "knowledge-workspace",
    }
    assert recorded["flow_id"] == "default"
    request = recorded["agent_explain"]
    assert request["history"] == []
    assert request["group"] == ["data-formulator-readonly"]
    assert request["collection"] == "business-context-traces"
    assert request["session_id"] == "session-official"
    framing, request_json = request["question"].split("\nREQUEST=", 1)
    assert json.loads(request_json) == {
        "question": make_query().text,
        "context": make_query().context,
    }
    assert "smallest sufficient set" in framing
    assert "tool's name and description" in framing
    assert "relevant read-only knowledge tool" in framing
    assert "request language and indexed terminology may differ" in framing
    assert "include concise common-language or English term equivalents" in framing
    assert "repeat that tool at most once" in framing
    assert "Answer in the request's language" in framing
    assert "knowledge_query" not in framing
    assert "structured_query" not in framing
    assert "do not perform row-level semantic matching" in framing.lower()
    assert "user:42" not in request["question"]
    assert "workspace-local" not in request["question"]
    assert _TOKEN not in request["question"]
    assert recorded["closed"] is True


def test_query_consumes_the_same_stream_once(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([
        provenance(Grounding(uri="urn:grounding")),
        provenance(Observation(uri="urn:observation")),
        terminal_answer("Definition."),
    ])
    client = TrustGraphClient(
        make_target(),
        explain_iterator_factory=factory,
        session_id_factory=lambda: "session-once",
    )

    result = client.query(make_query(context=""), bearer_token=_TOKEN)

    assert json.loads(result.text)["answer"] == "Definition."
    assert len(factory.calls) == 1
    target, token, question, session_id = factory.calls[0]
    assert target.trace_collection == "business-context-traces"
    assert token == _TOKEN
    assert session_id == "session-once"
    assert json.loads(question.split("\nREQUEST=", 1)[1]) == {
        "question": make_query().text,
    }
    assert factory.close_count == 1


@pytest.mark.parametrize(
    "events",
    [
        [],
        [AgentThought(content="hidden", end_of_message=True)],
        [AgentObservation(content="hidden", end_of_message=True)],
        [AgentAnswer(content="partial", end_of_message=False, end_of_dialog=False)],
        [AgentAnswer(content="not done", end_of_message=True, end_of_dialog=False)],
        [terminal_answer("")],
    ],
)
def test_query_rejects_missing_empty_or_non_terminal_answer(
    allow_trustgraph: None,
    events: list[object],
) -> None:
    factory = RecordingExplainFactory(events)

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(),
            explain_iterator_factory=factory,
        ).query(make_query(), bearer_token=_TOKEN)

    assert captured.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR
    assert factory.close_count == 1


def test_answer_text_does_not_create_fake_document_citations(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([
        terminal_answer("Narrative contains https://untrusted.example/document."),
    ])

    result = TrustGraphClient(
        make_target(),
        explain_iterator_factory=factory,
        session_id_factory=lambda: "session-no-fake-source",
    ).query(make_query(), bearer_token=_TOKEN)

    assert [item.uri for item in result.context_items] == [
        "urn:trustgraph:agent:session-no-fake-source",
    ]
    assert json.loads(result.text)["sources"] == []


def test_bounded_result_remains_valid_json_and_marks_truncation(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([terminal_answer("meaning " * 1_000)])

    result = TrustGraphClient(
        make_target(max_response_chars=600),
        explain_iterator_factory=factory,
        session_id_factory=lambda: "session-bounded",
    ).query(make_query(), bearer_token=_TOKEN)

    payload = json.loads(result.text)
    assert len(result.text) <= 600
    assert result.truncated is True
    assert payload["truncated"] is True
    assert result.context_items[-1].uri == "urn:trustgraph:agent:session-bounded"


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (TimeoutError("slow"), BusinessContextErrorCategory.TIMEOUT),
        (OSError("offline"), BusinessContextErrorCategory.UNAVAILABLE),
        (
            ProtocolException("auth failure: denied"),
            BusinessContextErrorCategory.UNAUTHORIZED,
        ),
        (
            ProtocolException("Timeout waiting for auth response"),
            BusinessContextErrorCategory.TIMEOUT,
        ),
        (ProtocolException("bad frame"), BusinessContextErrorCategory.PROTOCOL_ERROR),
        (TrustGraphException("agent failed"), BusinessContextErrorCategory.UNAVAILABLE),
    ],
)
def test_stream_errors_are_stable_and_socket_is_closed(
    allow_trustgraph: None,
    error: Exception,
    category: BusinessContextErrorCategory,
) -> None:
    factory = RecordingExplainFactory(error=error)

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(),
            explain_iterator_factory=factory,
        ).query(make_query(), bearer_token=_TOKEN)

    assert captured.value.category is category
    assert _TOKEN not in str(captured.value)
    assert _TOKEN not in repr(captured.value)
    assert factory.close_count == 1


def test_closing_outer_generator_closes_official_stream(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([
        provenance(Grounding(uri="urn:grounding")),
        terminal_answer("unused"),
    ])
    stream = TrustGraphClient(
        make_target(),
        explain_iterator_factory=factory,
    ).query_stream(make_query(), bearer_token=_TOKEN)

    assert next(stream) == BusinessContextProgress(1, "searching")
    stream.close()

    assert factory.close_count == 1


@pytest.mark.parametrize("token", ["", "  ", "bad\nvalue", None])
def test_invalid_bearer_fails_before_network(
    allow_trustgraph: None,
    token: Any,
) -> None:
    factory = RecordingExplainFactory([terminal_answer("unused")])

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(),
            explain_iterator_factory=factory,
        ).query(make_query(), bearer_token=token)

    assert captured.value.category is BusinessContextErrorCategory.NOT_CONFIGURED
    assert factory.calls == []


def test_invalid_generated_session_id_fails_before_network(
    allow_trustgraph: None,
) -> None:
    factory = RecordingExplainFactory([terminal_answer("unused")])

    with pytest.raises(BusinessContextError) as captured:
        TrustGraphClient(
            make_target(),
            explain_iterator_factory=factory,
            session_id_factory=lambda: "../escape",
        ).query(make_query(), bearer_token=_TOKEN)

    assert captured.value.category is BusinessContextErrorCategory.PROTOCOL_ERROR
    assert factory.calls == []
