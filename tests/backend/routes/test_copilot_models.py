from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_formulator.copilot.capabilities import CopilotCapabilityStore
from data_formulator.model_registry import ModelRegistry


pytestmark = [pytest.mark.backend]

COPILOT_ENV = {
    "GITHUB_COPILOT_ENABLED": "true",
    "GITHUB_COPILOT_MODELS": "gpt-4.1,gpt-5.3-codex",
}


class ProbeClient:
    def get_completion(self, _messages, *, stream=False, **_kwargs):
        if stream:
            return iter([
                SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="ok", tool_calls=None),
                )]),
            ])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok"),
        )])

    def get_completion_with_tools(self, _messages, _tools, *, stream=False, **_kwargs):
        assert stream is True
        return iter([
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(
                        function=SimpleNamespace(
                            name="report_capability",
                            arguments='{"ok":true}',
                        ),
                    )],
                ),
            )]),
        ])


@pytest.fixture()
def flask_client():
    from data_formulator.app import app

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@patch.dict(os.environ, COPILOT_ENV, clear=True)
def test_only_identity_qualified_chat_models_enter_public_results(flask_client):
    registry = ModelRegistry()
    store = CopilotCapabilityStore(
        model_catalog={
            "github_copilot/gpt-4.1": {"mode": "chat"},
            "github_copilot/gpt-5.3-codex": {"mode": "responses"},
        },
    )
    constructed: list[tuple[str, str, bool]] = []

    def get_client(config, *, trusted=False, identity_id=None, allow_unqualified_copilot=False):
        constructed.append((config["model"], identity_id, allow_unqualified_copilot))
        return ProbeClient()

    with (
        patch("data_formulator.routes.agents.model_registry", registry),
        patch("data_formulator.routes.agents.copilot_capability_store", store, create=True),
        patch("data_formulator.routes.agents.get_identity_id", return_value="browser:identity-a"),
        patch("data_formulator.routes.agents.get_client", side_effect=get_client),
    ):
        initial = flask_client.get("/api/agent/list-global-models").get_json()["data"]
        checked = flask_client.post("/api/agent/check-available-models", json={}).get_json()["data"]
        cached = flask_client.get("/api/agent/list-global-models").get_json()["data"]

    assert initial == []
    assert [item["model"] for item in checked] == ["gpt-4.1"]
    assert checked[0]["status"] == "connected"
    assert checked[0]["capabilities"] == {
        "chat": True,
        "streaming": True,
        "tools": True,
    }
    assert cached == [{key: value for key, value in checked[0].items() if key not in {"status", "error"}}]
    assert constructed == [("gpt-4.1", "browser:identity-a", True)]


@patch.dict(os.environ, COPILOT_ENV, clear=True)
def test_capability_cache_is_not_shared_between_request_identities(flask_client):
    registry = ModelRegistry()
    store = CopilotCapabilityStore(
        model_catalog={
            "github_copilot/gpt-4.1": {"mode": "chat"},
            "github_copilot/gpt-5.3-codex": {"mode": "responses"},
        },
    )

    with (
        patch("data_formulator.routes.agents.model_registry", registry),
        patch("data_formulator.routes.agents.copilot_capability_store", store, create=True),
        patch("data_formulator.routes.agents.get_identity_id", return_value="browser:identity-a"),
        patch("data_formulator.routes.agents.get_client", return_value=ProbeClient()),
    ):
        flask_client.post("/api/agent/check-available-models", json={})

    with (
        patch("data_formulator.routes.agents.model_registry", registry),
        patch("data_formulator.routes.agents.copilot_capability_store", store, create=True),
        patch("data_formulator.routes.agents.get_identity_id", return_value="browser:identity-b"),
    ):
        other_identity = flask_client.get("/api/agent/list-global-models").get_json()["data"]

    assert other_identity == []
