from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest

from data_formulator.errors import AppError, ErrorCode
from data_formulator.copilot.litellm_adapter import (
    COPILOT_API_BASE,
    COPILOT_TOKEN_URL,
    CopilotTokenManager,
    install_litellm_copilot_adapter,
    verify_litellm_copilot_contract,
)


pytestmark = [pytest.mark.backend]


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass
class FakeResponse:
    payload: dict[str, Any]
    status_code: int = 200

    def json(self) -> dict[str, Any]:
        return dict(self.payload)


class ScriptedHttp:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        with self._lock:
            self.calls.append({"url": url, **kwargs})
            assert self.responses, f"unexpected HTTP request to {url}"
            return self.responses.pop(0)


def _token_response(
    token: str = "short-copilot-token",
    *,
    expires_at: float = 2_000.0,
    api_base: str = COPILOT_API_BASE,
) -> FakeResponse:
    return FakeResponse({
        "token": token,
        "expires_at": expires_at,
        "endpoints": {"api": api_base},
    })


def test_litellm_contract_is_locked_to_the_audited_version():
    result = verify_litellm_copilot_contract()

    assert result["version"] == "1.91.3"
    assert len(result["authenticator_sha256"]) == 64
    assert len(result["chat_config_sha256"]) == 64


def test_contract_fails_closed_on_a_litellm_version_change(monkeypatch):
    monkeypatch.setattr(
        "data_formulator.copilot.litellm_adapter.importlib_metadata.version",
        lambda _name: "1.92.0",
    )

    with pytest.raises(AppError) as exc:
        verify_litellm_copilot_contract()

    assert exc.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert "1.92.0" not in str(exc.value)


def test_adapter_uses_request_local_tokens_without_creating_litellm_files(
    tmp_path,
    monkeypatch,
):
    token_dir = tmp_path / "shared-litellm-token-dir"
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(token_dir))
    install_litellm_copilot_adapter()

    from litellm.llms.github_copilot.authenticator import Authenticator

    http = ScriptedHttp(_token_response())
    manager = CopilotTokenManager(
        "long-lived-github-token",
        http=http,
        clock=FakeClock(),
    )

    with manager.activate():
        authenticator = Authenticator()
        assert authenticator.get_access_token() == "long-lived-github-token"
        assert authenticator.get_api_key() == "short-copilot-token"
        assert authenticator.get_api_base() == COPILOT_API_BASE

    assert not token_dir.exists()
    assert len(http.calls) == 1
    assert http.calls[0] == {
        "url": COPILOT_TOKEN_URL,
        "headers": {
            "accept": "application/json",
            "editor-version": "vscode/1.85.1",
            "editor-plugin-version": "copilot/1.155.0",
            "user-agent": "GithubCopilot/1.155.0",
            "accept-encoding": "gzip,deflate,br",
            "content-type": "application/json",
            "authorization": "token long-lived-github-token",
        },
        "timeout": (3.05, 10.0),
        "allow_redirects": False,
    }


def test_adapter_blocks_authenticator_outside_an_application_request_context(tmp_path, monkeypatch):
    token_dir = tmp_path / "must-not-exist"
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(token_dir))
    install_litellm_copilot_adapter()
    from litellm.llms.github_copilot.authenticator import Authenticator, GetAPIKeyError

    with pytest.raises(GetAPIKeyError, match="application-managed"):
        Authenticator().get_api_key()

    assert not token_dir.exists()


def test_chat_config_reuses_one_short_token_exchange_for_all_authenticator_calls():
    install_litellm_copilot_adapter()
    from litellm.llms.github_copilot.chat.transformation import GithubCopilotConfig

    http = ScriptedHttp(_token_response())
    manager = CopilotTokenManager("github-token", http=http, clock=FakeClock())

    with manager.activate():
        config = GithubCopilotConfig()
        api_base, api_key, provider = config._get_openai_compatible_provider_info(
            "gpt-4.1",
            None,
            None,
            "github_copilot",
        )
        headers = config.validate_environment(
            {},
            "gpt-4.1",
            [{"role": "user", "content": "hello"}],
            {},
            {},
            api_key=api_key,
            api_base=api_base,
        )

    assert (api_base, api_key, provider) == (
        COPILOT_API_BASE,
        "short-copilot-token",
        "github_copilot",
    )
    assert headers["Authorization"] == "Bearer short-copilot-token"
    assert len(http.calls) == 1


def test_short_token_refreshes_inside_the_same_request_manager_before_expiry():
    install_litellm_copilot_adapter()
    from litellm.llms.github_copilot.authenticator import Authenticator

    clock = FakeClock()
    http = ScriptedHttp(
        _token_response("short-one", expires_at=1_100),
        _token_response("short-two", expires_at=2_000),
    )
    manager = CopilotTokenManager("github-token", http=http, clock=clock)

    with manager.activate():
        assert Authenticator().get_api_key() == "short-one"
        clock.now = 1_039
        assert Authenticator().get_api_key() == "short-one"
        clock.now = 1_040
        assert Authenticator().get_api_key() == "short-two"

    assert len(http.calls) == 2


def test_two_identities_remain_isolated_when_authenticator_calls_overlap():
    install_litellm_copilot_adapter()
    from litellm.llms.github_copilot.authenticator import Authenticator

    barrier = threading.Barrier(2)

    class IdentityHttp:
        def get(self, _url: str, **kwargs: Any) -> FakeResponse:
            long_token = kwargs["headers"]["authorization"].removeprefix("token ")
            barrier.wait(timeout=5)
            return _token_response(f"short-for-{long_token}")

    def resolve(long_token: str) -> tuple[str, str]:
        manager = CopilotTokenManager(long_token, http=IdentityHttp(), clock=FakeClock())
        with manager.activate():
            auth = Authenticator()
            return auth.get_access_token(), auth.get_api_key()

    with ThreadPoolExecutor(max_workers=2) as executor:
        alice = executor.submit(resolve, "alice")
        bob = executor.submit(resolve, "bob")

    assert alice.result() == ("alice", "short-for-alice")
    assert bob.result() == ("bob", "short-for-bob")


def test_token_exchange_errors_are_stable_and_do_not_expose_tokens_or_body():
    secret_body = "upstream leaked github-token and short-token"
    http = ScriptedHttp(FakeResponse({"message": secret_body}, status_code=401))
    manager = CopilotTokenManager("long-secret-token", http=http, clock=FakeClock())

    with pytest.raises(AppError) as exc:
        manager.get_api_key()

    assert exc.value.code == ErrorCode.LLM_AUTH_FAILED
    assert "long-secret-token" not in str(exc.value)
    assert secret_body not in str(exc.value)


def test_non_json_auth_failure_still_requires_reconnection():
    class NonJsonAuthResponse:
        status_code = 401

        def json(self):
            raise ValueError("secret upstream HTML body")

    http = ScriptedHttp(NonJsonAuthResponse())
    manager = CopilotTokenManager("long-secret-token", http=http, clock=FakeClock())

    with pytest.raises(AppError) as exc:
        manager.get_api_key()

    assert exc.value.code == ErrorCode.LLM_AUTH_FAILED
    assert "reconnect" in str(exc.value).lower()
    assert "secret" not in str(exc.value).lower()


def test_adapter_does_not_mutate_process_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", "sentinel-token-dir")
    monkeypatch.setenv("GITHUB_COPILOT_API_KEY_FILE", "sentinel-key-file")
    before = {
        key: os.environ.get(key)
        for key in ("GITHUB_COPILOT_TOKEN_DIR", "GITHUB_COPILOT_API_KEY_FILE")
    }

    install_litellm_copilot_adapter()

    assert {
        key: os.environ.get(key)
        for key in before
    } == before
