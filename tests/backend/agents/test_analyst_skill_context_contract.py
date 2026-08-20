# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from data_formulator.analyst.agent import AnalystAgent
from data_formulator.analyst.business_context.base import ContextItem
from data_formulator.analyst.skills import (
    SkillAuthorization,
    SkillMeta,
    SkillRegistry,
    ToolResult,
)


pytestmark = [pytest.mark.backend]


class _RecordingLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def log(self, step_type: str, **kwargs) -> None:
        self.entries.append({"step_type": step_type, **kwargs})


class _ContextSkill:
    def __init__(self, context_items: tuple[ContextItem, ...]) -> None:
        self.context_items = context_items
        self.contexts = []

    def handle_tool(self, name, args, ctx) -> ToolResult:
        self.contexts.append(ctx)
        return ToolResult(
            text="sensitive business answer",
            context_items=self.context_items,
            public_summary="Business context retrieved.",
            resume_text="bounded business evidence",
        )


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


def _context_registry(skill: _ContextSkill) -> SkillRegistry:
    return SkillRegistry(
        metas={
            "context-skill": SkillMeta(
                name="context-skill",
                description="Read-only context lookup.",
                tool_names=("lookup_context",),
            ),
        },
        skills={"context-skill": skill},
        tool_specs={
            "context-skill": [{
                "type": "function",
                "function": {
                    "name": "lookup_context",
                    "description": "Look up context.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                },
            }],
        },
    )


def test_skill_authorization_normalizes_and_requires_both_ids() -> None:
    authorization = SkillAuthorization(
        identity_id="  user:42  ",
        workspace_id="  workspace-good  ",
    )

    assert authorization.identity_id == "user:42"
    assert authorization.workspace_id == "workspace-good"

    with pytest.raises(ValueError, match="identity_id"):
        SkillAuthorization(identity_id=" ", workspace_id="workspace-good")
    with pytest.raises(ValueError, match="workspace_id"):
        SkillAuthorization(identity_id="user:42", workspace_id="\t")


def test_system_prompt_requires_material_business_semantics_before_action() -> None:
    agent = AnalystAgent(
        client=None,
        workspace=MagicMock(user_home=None),
    )

    prompt = agent._build_system_prompt()
    normalized_prompt = " ".join(prompt.split())

    assert "## Ground business meaning before acting" in prompt
    assert "Do not look up every term or column" in normalized_prompt
    assert "offers a relevant extension skill, load it" in normalized_prompt
    assert "If none is available" in normalized_prompt
    assert "Do not infer a governed meaning solely from a label" in normalized_prompt
    assert "relevant source or table's role" in normalized_prompt
    assert "field names and types" in normalized_prompt
    assert "non-sensitive representative values" in normalized_prompt
    assert "masked value patterns" in normalized_prompt
    assert "raw sensitive values" in normalized_prompt
    assert "Never send a whole table" in normalized_prompt
    assert (
        "provider owns its internal search and any multi-round retrieval"
        in normalized_prompt
    )
    assert "Use `ask_user` when choosing among meanings" in normalized_prompt


def test_tool_result_keeps_legacy_positionals_and_freezes_context_items() -> None:
    item = ContextItem(
        uri="https://example.com/source",
        title="Source title",
        provider="example",
    )
    mutable_items = [item]

    legacy = ToolResult("legacy text", ("data:image/png;base64,abc",))
    result = ToolResult(
        "business answer",
        (),
        mutable_items,
        public_summary="  Business context retrieved.  ",
    )
    mutable_items.clear()

    assert legacy.text == "legacy text"
    assert legacy.images == ("data:image/png;base64,abc",)
    assert legacy.context_items == ()
    assert legacy.error_code is None
    assert legacy.resume_text is None
    assert result.context_items == (item,)
    assert result.public_summary == "Business context retrieved."


def test_tool_result_rejects_invalid_context_and_public_summary() -> None:
    with pytest.raises(ValueError, match="context_items"):
        ToolResult(context_items=("not-a-context-item",))
    with pytest.raises(ValueError, match="public_summary"):
        ToolResult(public_summary="x" * 513)
    with pytest.raises(ValueError, match="error_code"):
        ToolResult(error_code="invalid error code")
    with pytest.raises(ValueError, match="resume_text"):
        ToolResult(resume_text="x" * 1_048_577)
    with pytest.raises(ValueError, match="resume_text"):
        ToolResult(resume_text="unsafe\x00text")


def test_context_item_kind_defaults_to_source_and_rejects_unknown_values() -> None:
    assert ContextItem(uri="urn:document:one").kind == "source"
    assert ContextItem(uri="urn:trace:one", kind="trace").kind == "trace"
    with pytest.raises(ValueError, match="kind"):
        ContextItem(uri="urn:document:one", kind="citation")  # type: ignore[arg-type]


def test_skill_context_authorization_cannot_be_overridden_by_payload() -> None:
    workspace = MagicMock()
    workspace.user_home = None
    agent = AnalystAgent(
        client=None,
        workspace=workspace,
        identity_id="user:42",
        workspace_id="workspace-good",
    )
    agent._run_payload = {
        "identity_id": "attacker",
        "workspace_id": "workspace-attacker",
    }

    ctx = agent._make_skill_context(
        trajectory=[],
        payload={"workspace_id": "another-attacker"},
        runtime=agent,
    )

    assert ctx.authorization == SkillAuthorization(
        identity_id="user:42",
        workspace_id="workspace-good",
    )
    assert ctx.payload["workspace_id"] == "another-attacker"


def test_resume_trajectory_uses_public_tool_summary_without_mutating_model_copy() -> None:
    workspace = MagicMock()
    workspace.user_home = None
    agent = AnalystAgent(client=None, workspace=workspace)
    agent._public_tool_result_summaries = {
        "context-call": "Business context retrieved.",
    }
    trajectory = [
        {
            "role": "tool",
            "tool_call_id": "context-call",
            "content": "sensitive business answer",
        },
        {
            "role": "tool",
            "tool_call_id": "local-call",
            "content": "ordinary local result",
        },
    ]

    public_trajectory = agent._strip_images(trajectory)

    assert public_trajectory[0]["content"] == "Business context retrieved."
    assert public_trajectory[1]["content"] == "ordinary local result"
    assert trajectory[0]["content"] == "sensitive business answer"


def test_resume_trajectory_prefers_model_evidence_over_public_summary() -> None:
    workspace = MagicMock(user_home=None)
    agent = AnalystAgent(client=None, workspace=workspace)
    agent._public_tool_result_summaries = {
        "context-call": "Business context retrieved.",
    }
    agent._resume_tool_result_texts = {
        "context-call": "[FINAL_EVIDENCE]\nGoverned meaning and sources.",
    }
    trajectory = [{
        "role": "tool",
        "tool_call_id": "context-call",
        "content": "full private provider response",
    }]

    resumed = agent._strip_images(trajectory)

    assert resumed[0]["content"] == (
        "[FINAL_EVIDENCE]\nGoverned meaning and sources."
    )
    assert trajectory[0]["content"] == "full private provider response"


def test_context_tool_routes_bounded_citations_without_logging_answer() -> None:
    first = ContextItem(
        uri="https://example.com/private-source",
        title="Sensitive source title",
        provider="example",
    )
    context_items = (
        first,
        ContextItem(
            uri=first.uri,
            title="Duplicate title",
            provider="example",
        ),
        *(
            ContextItem(
                uri=f"urn:document:{index}",
                title=f"Source {index}",
                provider="example",
            )
            for index in range(60)
        ),
    )
    skill = _ContextSkill(context_items)
    agent = AnalystAgent(
        client=None,
        workspace=MagicMock(user_home=None),
        skill_registry=_context_registry(skill),
        identity_id="user:42",
        workspace_id="workspace-good",
    )
    agent._loaded_skills = {"context-skill"}
    agent._run_payload = {
        "identity_id": "attacker",
        "workspace_id": "workspace-attacker",
    }

    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="lookup_context",
            arguments=json.dumps({
                "query": "sensitive user query",
                "identity_id": "attacker",
                "workspace_id": "workspace-attacker",
            }),
        ),
    )
    responses = [
        _response(tool_calls=[tool_call], finish_reason="tool_calls"),
        _response(content="done"),
    ]

    def fake_stream_llm(messages, tools):
        if False:  # Make this a generator so ``yield from`` captures return.
            yield None
        return responses.pop(0)

    agent._stream_llm = fake_stream_llm
    messages: list[dict] = []
    recording_log = _RecordingLog()

    events = list(agent._tool_loop(
        messages=messages,
        max_tool_rounds=2,
        max_json_retries=1,
        json_retries=0,
        llm_calls_in_cycle=0,
        rlog=recording_log,
        input_tables=[],
        outer_iteration=1,
    ))

    context_events = [event for event in events if event["type"] == "context_info"]
    assert len(context_events) == 1
    assert context_events[0]["tool"] == "lookup_context"
    assert len(context_events[0]["context_items"]) == 50
    assert context_events[0]["context_items"][0] == {
        "uri": first.uri,
        "title": first.title,
        "provider": first.provider,
        "kind": "source",
    }

    tool_event = next(event for event in events if event["type"] == "tool_result")
    assert tool_event["stdout"] == "Business context retrieved."
    assert messages[-2]["role"] == "tool"
    assert messages[-2]["content"] == "sensitive business answer"
    assert agent._strip_images(messages)[-2]["content"] == (
        "bounded business evidence"
    )
    assert skill.contexts[0].authorization == SkillAuthorization(
        identity_id="user:42",
        workspace_id="workspace-good",
    )

    serialized_log = json.dumps(recording_log.entries)
    assert "sensitive business answer" not in serialized_log
    assert "sensitive user query" not in serialized_log
    assert "Sensitive source title" not in serialized_log
    assert "private-source" not in serialized_log
    tool_log = next(
        entry for entry in recording_log.entries
        if entry["step_type"] == "tool_execution"
    )
    assert tool_log["output_summary"] == "Business context retrieved."
    assert tool_log["context_item_count"] == 50
    assert tool_log["context_providers"] == ["example"]


def test_skill_tool_exception_is_stable_and_does_not_leak_message() -> None:
    class FailingSkill(_ContextSkill):
        def handle_tool(self, name, args, ctx) -> ToolResult:
            raise RuntimeError("secret-token external response body")

    skill = FailingSkill(())
    agent = AnalystAgent(
        client=None,
        workspace=MagicMock(user_home=None),
        skill_registry=_context_registry(skill),
    )
    agent._loaded_skills = {"context-skill"}
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="lookup_context", arguments="{}"),
    )
    responses = [
        _response(tool_calls=[tool_call], finish_reason="tool_calls"),
        _response(content="done"),
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

    serialized = json.dumps({"events": events, "logs": recording_log.entries})
    assert "secret-token" not in serialized
    assert "external response body" not in serialized
    tool_event = next(event for event in events if event["type"] == "tool_result")
    assert tool_event == {
        "type": "tool_result",
        "tool": "lookup_context",
        "status": "error",
        "stdout": "Tool 'lookup_context' failed.",
    }
    assert messages[-2]["content"] == "Tool 'lookup_context' failed."


def test_streaming_skill_tool_routes_only_bounded_progress_fields() -> None:
    closed = False

    def streaming_tool():
        nonlocal closed
        try:
            yield {
                "type": "tool_progress",
                "tool": "attacker-controlled-name",
                "query_index": 1,
                "phase": "searching",
                "thought": "secret hidden reasoning",
            }
            yield {
                "type": "tool_progress",
                "query_index": 1,
                "phase": "unknown-phase",
                "observation": "secret raw result",
            }
            yield {"type": "not-public", "content": "secret event"}
            yield {
                "type": "tool_progress",
                "query_index": None,
                "phase": "finalizing",
                "triples": ["secret triple"],
            }
            return ToolResult(text="bounded final result")
        finally:
            closed = True

    agent = AnalystAgent(client=None, workspace=MagicMock(user_home=None))
    routed = agent._route_skill_tool_events(
        streaming_tool(),
        "lookup_context",
    )
    events = []
    while True:
        try:
            events.append(next(routed))
        except StopIteration as completed:
            result = completed.value
            break

    assert events == [
        {
            "type": "tool_progress",
            "tool": "lookup_context",
            "query_index": 1,
            "phase": "searching",
        },
        {
            "type": "tool_progress",
            "tool": "lookup_context",
            "query_index": None,
            "phase": "finalizing",
        },
    ]
    assert result == ToolResult(text="bounded final result")
    assert closed is True
    assert "secret" not in json.dumps(events)


def test_malformed_action_arguments_are_repaired_before_retry() -> None:
    agent = AnalystAgent(
        client=None,
        workspace=MagicMock(user_home=None),
    )
    malformed_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="ask_user",
            arguments='{"questions":["unfinished"',
        ),
    )
    responses = [
        _response(tool_calls=[malformed_call], finish_reason="tool_calls"),
        _response(content="done"),
    ]

    def fake_stream_llm(messages, tools):
        if False:
            yield None
        return responses.pop(0)

    agent._stream_llm = fake_stream_llm
    messages: list[dict] = []
    events = list(agent._tool_loop(
        messages, 2, 1, 0, 0, _RecordingLog(), [], 1,
    ))

    assert messages[0]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert messages[1]["role"] == "tool"
    assert "valid JSON object" in messages[1]["content"]
    assert next(
        event for event in events if event["type"] == "tool_result"
    )["status"] == "error"
    assert events[-1]["final_text"] == "done"
