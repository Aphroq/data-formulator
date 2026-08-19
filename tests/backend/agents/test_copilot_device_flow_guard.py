from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

from data_formulator.agents.client_utils import Client
from data_formulator.copilot.litellm_adapter import CopilotTokenManager


pytestmark = [pytest.mark.backend]


@pytest.mark.parametrize(
    ("endpoint", "model"),
    [
        ("github_copilot", "gpt-4.1"),
        ("github_copilot", "github_copilot/gpt-4.1"),
        ("custom", "github_copilot/gpt-4.1"),
        (" GitHub_Copilot ", "gpt-4.1"),
        ("custom", " GITHUB_COPILOT/gpt-4.1 "),
    ],
)
def test_copilot_model_cannot_reach_litellm_interactive_authenticator(
    endpoint,
    model,
    monkeypatch,
):
    completion = Mock()
    monkeypatch.setattr("data_formulator.agents.client_utils.litellm.completion", completion)

    with pytest.raises(ValueError, match="application-managed authentication"):
        Client(endpoint, model)

    completion.assert_not_called()


def test_existing_provider_construction_is_unchanged():
    client = Client("openai", "gpt-4.1", api_key="test-key")

    assert client.model == "openai/gpt-4.1"
    assert client.params["api_key"] == "test-key"


@dataclass
class _TokenResponse:
    status_code: int = 200

    def json(self) -> dict[str, Any]:
        return {
            "token": "request-local-short-token",
            "expires_at": 2_000.0,
            "endpoints": {"api": "https://api.githubcopilot.com"},
        }


class _TokenHttp:
    def get(self, _url: str, **_kwargs: Any) -> _TokenResponse:
        return _TokenResponse()


def test_copilot_client_activates_request_local_auth_for_completion_and_ping(monkeypatch):
    from litellm.llms.github_copilot.authenticator import Authenticator, GetAPIKeyError

    observed: list[str] = []

    def fake_completion(**kwargs):
        observed.append(Authenticator().get_api_key())
        return {"model": kwargs["model"]}

    monkeypatch.setattr("data_formulator.agents.client_utils.litellm.completion", fake_completion)
    manager = CopilotTokenManager(
        "identity-long-token",
        http=_TokenHttp(),
        clock=lambda: 1_000.0,
    )
    client = Client(
        "github_copilot",
        "gpt-4.1",
        copilot_token_manager=manager,
    )

    response = client.get_completion([{"role": "user", "content": "hello"}])
    client.ping()

    assert response == {"model": "github_copilot/gpt-4.1"}
    assert observed == ["request-local-short-token", "request-local-short-token"]
    with pytest.raises(GetAPIKeyError, match="application-managed"):
        Authenticator().get_api_key()


def test_copilot_client_keeps_lazy_stream_iteration_request_local(monkeypatch):
    from litellm.llms.github_copilot.authenticator import Authenticator, GetAPIKeyError

    def fake_completion(**kwargs):
        assert kwargs["stream"] is True

        def lazy_chunks():
            yield Authenticator().get_api_key()
            yield Authenticator().get_api_key()

        return lazy_chunks()

    monkeypatch.setattr("data_formulator.agents.client_utils.litellm.completion", fake_completion)
    manager = CopilotTokenManager(
        "identity-long-token",
        http=_TokenHttp(),
        clock=lambda: 1_000.0,
    )
    client = Client(
        "github_copilot",
        "gpt-4.1",
        copilot_token_manager=manager,
    )

    stream = client.get_completion(
        [{"role": "user", "content": "hello"}],
        stream=True,
    )

    assert list(stream) == [
        "request-local-short-token",
        "request-local-short-token",
    ]
    with pytest.raises(GetAPIKeyError, match="application-managed"):
        Authenticator().get_api_key()
