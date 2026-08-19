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

    assert "## Ground business meaning before acting" in prompt
    assert "Do not treat every word or column label as a lookup trigger" in prompt
    assert "load the relevant extension skill" in prompt
    assert "Do not infer governed business meaning solely from labels" in prompt
    assert "Use `ask_user` when choosing among meanings" in prompt


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
    assert result.context_items == (item,)
    assert result.public_summary == "Business context retrieved."


def test_tool_result_rejects_invalid_context_and_public_summary() -> None:
    with pytest.raises(ValueError, match="context_items"):
        ToolResult(context_items=("not-a-context-item",))
    with pytest.raises(ValueError, match="public_summary"):
        ToolResult(public_summary="x" * 513)
    with pytest.raises(ValueError, match="error_code"):
        ToolResult(error_code="invalid error code")


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
    }

    tool_event = next(event for event in events if event["type"] == "tool_result")
    assert tool_event["stdout"] == "Business context retrieved."
    assert messages[-2]["role"] == "tool"
    assert messages[-2]["content"] == "sensitive business answer"
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
