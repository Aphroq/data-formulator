from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_formulator.copilot.capabilities import CopilotCapabilityStore


pytestmark = [pytest.mark.backend]


def _buffered_response(content: str = "ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def _content_stream():
    return iter([
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="ok", tool_calls=None))],
        ),
    ])


def _tool_stream(name: str = "report_capability"):
    return iter([
        SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(
                        function=SimpleNamespace(name=name, arguments='{"ok":true}'),
                    )],
                ),
            )],
        ),
    ])


class FullyCapableClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def get_completion(self, _messages, *, stream=False, **_kwargs):
        self.calls.append(("chat", stream))
        return _content_stream() if stream else _buffered_response()

    def get_completion_with_tools(self, _messages, _tools, *, stream=False, **_kwargs):
        self.calls.append(("tools", stream))
        return _tool_stream()


def test_chat_streaming_and_streamed_tools_are_recorded_separately():
    client = FullyCapableClient()
    store = CopilotCapabilityStore(
        model_catalog={"github_copilot/gpt-4.1": {"mode": "chat"}},
        clock=lambda: 1_000.0,
    )

    result = store.probe(
        "identity-a",
        "global-github_copilot-gpt-4.1",
        "gpt-4.1",
        lambda: client,
    )

    assert result.chat is True
    assert result.streaming is True
    assert result.tools is True
    assert result.qualified is True
    assert result.error_codes == {}
    assert client.calls == [("chat", False), ("chat", True), ("tools", True)]
    assert store.get_qualified(
        "identity-a",
        "global-github_copilot-gpt-4.1",
    ) == result


def test_responses_only_model_fails_closed_without_constructing_a_client():
    constructed = False

    def client_factory():
        nonlocal constructed
        constructed = True
        return FullyCapableClient()

    store = CopilotCapabilityStore(
        model_catalog={"github_copilot/gpt-5.3-codex": {"mode": "responses"}},
    )

    result = store.probe(
        "identity-a",
        "global-github_copilot-gpt-5.3-codex",
        "gpt-5.3-codex",
        client_factory,
    )

    assert constructed is False
    assert result.qualified is False
    assert result.error_codes == {
        "chat": "unsupported_mode",
        "streaming": "unsupported_mode",
        "tools": "unsupported_mode",
    }


def test_each_probe_runs_and_raw_failures_are_replaced_by_stable_codes():
    secret = "long-token-that-must-not-escape"

    class PartiallyCapableClient(FullyCapableClient):
        def get_completion(self, _messages, *, stream=False, **_kwargs):
            self.calls.append(("chat", stream))
            if not stream:
                raise RuntimeError(f"chat failed with {secret}")
            return _content_stream()

        def get_completion_with_tools(self, _messages, _tools, *, stream=False, **_kwargs):
            self.calls.append(("tools", stream))
            return _tool_stream("wrong_tool")

    client = PartiallyCapableClient()
    store = CopilotCapabilityStore(
        model_catalog={"github_copilot/gpt-4.1": {"mode": "chat"}},
    )

    result = store.probe(
        "identity-a",
        "global-github_copilot-gpt-4.1",
        "gpt-4.1",
        lambda: client,
    )

    assert client.calls == [("chat", False), ("chat", True), ("tools", True)]
    assert result.chat is False
    assert result.streaming is True
    assert result.tools is False
    assert result.error_codes == {
        "chat": "chat_failed",
        "tools": "tools_failed",
    }
    assert secret not in repr(result)
    assert store.get_qualified("identity-a", result.model_id) is None


def test_cache_is_identity_scoped_expires_and_can_be_invalidated():
    now = [1_000.0]
    store = CopilotCapabilityStore(
        model_catalog={"github_copilot/gpt-4.1": {"mode": "chat"}},
        clock=lambda: now[0],
        ttl_seconds=30,
    )
    model_id = "global-github_copilot-gpt-4.1"

    result = store.probe("identity-a", model_id, "gpt-4.1", FullyCapableClient)

    assert store.get_qualified("identity-a", model_id) == result
    assert store.get_qualified("identity-b", model_id) is None
    store.invalidate_identity("identity-b")
    assert store.get_qualified("identity-a", model_id) == result

    now[0] += 31
    assert store.get_qualified("identity-a", model_id) is None

    store.probe("identity-a", model_id, "gpt-4.1", FullyCapableClient)
    store.invalidate_identity("identity-a")
    assert store.get_qualified("identity-a", model_id) is None


def test_default_cache_survives_idle_time_until_explicit_invalidation():
    now = [1_000.0]
    store = CopilotCapabilityStore(
        model_catalog={"github_copilot/gpt-4.1": {"mode": "chat"}},
        clock=lambda: now[0],
    )
    model_id = "global-github_copilot-gpt-4.1"

    result = store.probe("identity-a", model_id, "gpt-4.1", FullyCapableClient)
    now[0] += 365 * 24 * 60 * 60

    assert store.get_qualified("identity-a", model_id) == result


def test_client_construction_failure_records_all_three_results_without_details():
    store = CopilotCapabilityStore(
        model_catalog={"github_copilot/gpt-4.1": {"mode": "chat"}},
    )

    def unavailable():
        raise RuntimeError("vault body with secret-token")

    result = store.probe(
        "identity-a",
        "global-github_copilot-gpt-4.1",
        "gpt-4.1",
        unavailable,
    )

    assert result.error_codes == {
        "chat": "client_unavailable",
        "streaming": "client_unavailable",
        "tools": "client_unavailable",
    }
    assert "secret-token" not in repr(result)
