from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from data_formulator.copilot.device_flow import (
    COPILOT_CREDENTIAL_SOURCE,
    GITHUB_ACCESS_TOKEN_URL,
    GITHUB_DEVICE_CODE_URL,
    CopilotDeviceFlowService,
    is_github_copilot_enabled,
)
from data_formulator.errors import AppError, ErrorCode


pytestmark = [pytest.mark.backend]


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeVault:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], dict[str, Any]] = {}

    def store(self, user_id: str, source_key: str, credentials: dict) -> None:
        self.values[(user_id, source_key)] = dict(credentials)

    def retrieve(self, user_id: str, source_key: str) -> dict | None:
        value = self.values.get((user_id, source_key))
        return dict(value) if value is not None else None

    def delete(self, user_id: str, source_key: str) -> None:
        self.values.pop((user_id, source_key), None)

    def list_sources(self, user_id: str) -> list[str]:
        return [source for identity, source in self.values if identity == user_id]


@dataclass
class FakeResponse:
    payload: dict[str, Any]
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return dict(self.payload)


class ScriptedHttp:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        assert self.responses, f"unexpected HTTP request to {url}"
        return self.responses.pop(0)


def _device_response(
    *,
    device_code: str = "device-secret-alice",
    user_code: str = "ABCD-EFGH",
    expires_in: int = 900,
    interval: int = 5,
    verification_uri: str = "https://github.com/login/device",
) -> FakeResponse:
    return FakeResponse({
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": verification_uri,
        "expires_in": expires_in,
        "interval": interval,
    })


def _service(
    http: ScriptedHttp,
    *,
    clock: FakeClock | None = None,
    vault: FakeVault | None = None,
) -> tuple[CopilotDeviceFlowService, FakeClock, FakeVault]:
    actual_clock = clock or FakeClock()
    actual_vault = vault or FakeVault()
    return (
        CopilotDeviceFlowService(
            vault=actual_vault,
            http=http,
            clock=actual_clock,
            client_id="public-test-client",
        ),
        actual_clock,
        actual_vault,
    )


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off"])
def test_feature_flag_is_default_off(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("GITHUB_COPILOT_ENABLED", raising=False)
    else:
        monkeypatch.setenv("GITHUB_COPILOT_ENABLED", value)

    assert is_github_copilot_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_feature_flag_accepts_explicit_true(monkeypatch, value):
    monkeypatch.setenv("GITHUB_COPILOT_ENABLED", value)
    assert is_github_copilot_enabled() is True


def test_start_returns_only_public_device_fields_and_server_handle():
    http = ScriptedHttp(_device_response())
    service, _, _ = _service(http)

    result = service.start("user:alice")

    assert result["status"] == "pending"
    assert result["user_code"] == "ABCD-EFGH"
    assert result["verification_uri"] == "https://github.com/login/device"
    assert result["expires_in"] == 900
    assert result["interval"] == 5
    assert len(result["authorization_id"]) >= 32
    assert "device_code" not in result
    assert "access_token" not in result
    assert "device-secret-alice" not in repr(result)

    assert http.calls == [{
        "url": GITHUB_DEVICE_CODE_URL,
        "headers": {
            "Accept": "application/json",
            "User-Agent": "Data-Formulator",
        },
        "data": {"client_id": "public-test-client", "scope": "read:user"},
        "timeout": (3.05, 10.0),
        "allow_redirects": False,
    }]


def test_poll_is_non_blocking_and_enforces_github_interval():
    http = ScriptedHttp(
        _device_response(),
        FakeResponse({"error": "authorization_pending"}),
    )
    service, clock, _ = _service(http)
    started = service.start("user:alice")

    early = service.poll("user:alice", started["authorization_id"])
    assert early == {"status": "pending", "interval": 5, "retry_after": 5}
    assert len(http.calls) == 1

    clock.advance(5)
    pending = service.poll("user:alice", started["authorization_id"])
    assert pending == {"status": "pending", "interval": 5, "retry_after": 5}
    assert len(http.calls) == 2

    immediate_retry = service.poll("user:alice", started["authorization_id"])
    assert immediate_retry["status"] == "pending"
    assert len(http.calls) == 2
    assert http.calls[1]["url"] == GITHUB_ACCESS_TOKEN_URL
    assert http.calls[1]["data"]["device_code"] == "device-secret-alice"


def test_slow_down_increases_the_minimum_poll_interval():
    http = ScriptedHttp(
        _device_response(interval=5),
        FakeResponse({"error": "slow_down", "interval": 10}),
        FakeResponse({"error": "authorization_pending"}),
    )
    service, clock, _ = _service(http)
    started = service.start("user:alice")

    clock.advance(5)
    slowed = service.poll("user:alice", started["authorization_id"])
    assert slowed == {"status": "pending", "interval": 10, "retry_after": 10}

    clock.advance(9)
    service.poll("user:alice", started["authorization_id"])
    assert len(http.calls) == 2

    clock.advance(1)
    service.poll("user:alice", started["authorization_id"])
    assert len(http.calls) == 3


def test_success_persists_long_lived_token_without_returning_it():
    secret = "gho_super_secret_access_token"
    http = ScriptedHttp(
        _device_response(),
        FakeResponse({"access_token": secret, "token_type": "bearer", "scope": "read:user"}),
    )
    service, clock, vault = _service(http)
    started = service.start("user:alice")

    clock.advance(5)
    result = service.poll("user:alice", started["authorization_id"])

    assert result == {"status": "connected"}
    assert secret not in repr(result)
    stored = vault.retrieve("user:alice", COPILOT_CREDENTIAL_SOURCE)
    assert stored == {
        "access_token": secret,
        "token_type": "bearer",
        "scope": "read:user",
    }
    assert service.status("user:alice") == {"connected": True}

    restarted, _, _ = _service(ScriptedHttp(), clock=clock, vault=vault)
    assert restarted.status("user:alice") == {"connected": True}
    assert restarted.retrieve_access_token("user:alice") == secret


def test_transactions_and_credentials_are_identity_scoped():
    http = ScriptedHttp(
        _device_response(device_code="alice-device", user_code="AAAA-AAAA"),
        _device_response(device_code="bob-device", user_code="BBBB-BBBB"),
        FakeResponse({"access_token": "alice-token", "token_type": "bearer"}),
    )
    service, clock, _ = _service(http)
    alice = service.start("user:alice")
    bob = service.start("user:bob")

    assert alice["authorization_id"] != bob["authorization_id"]
    with pytest.raises(AppError) as exc:
        service.poll("user:bob", alice["authorization_id"])
    assert exc.value.code == ErrorCode.INVALID_REQUEST
    assert len(http.calls) == 2

    clock.advance(5)
    assert service.poll("user:alice", alice["authorization_id"]) == {"status": "connected"}
    assert service.status("user:alice") == {"connected": True}
    assert service.status("user:bob") == {"connected": False}


@pytest.mark.parametrize(
    ("oauth_error", "expected_status"),
    [("access_denied", "denied"), ("expired_token", "expired"), ("token_expired", "expired")],
)
def test_terminal_oauth_errors_are_stable_and_remove_transaction(oauth_error, expected_status):
    http = ScriptedHttp(_device_response(), FakeResponse({"error": oauth_error}))
    service, clock, _ = _service(http)
    started = service.start("user:alice")
    clock.advance(5)

    assert service.poll("user:alice", started["authorization_id"]) == {"status": expected_status}
    with pytest.raises(AppError) as exc:
        service.poll("user:alice", started["authorization_id"])
    assert exc.value.code == ErrorCode.INVALID_REQUEST


def test_local_expiration_does_not_contact_token_endpoint():
    http = ScriptedHttp(_device_response(expires_in=6, interval=5))
    service, clock, _ = _service(http)
    started = service.start("user:alice")
    clock.advance(6)

    assert service.poll("user:alice", started["authorization_id"]) == {"status": "expired"}
    assert len(http.calls) == 1


def test_unknown_oauth_failure_and_response_body_are_not_exposed():
    secret_body = "upstream says device=secret-device and token=secret-token"
    http = ScriptedHttp(
        _device_response(),
        FakeResponse({"error": "device_flow_disabled", "error_description": secret_body}),
    )
    service, clock, _ = _service(http)
    started = service.start("user:alice")
    clock.advance(5)

    with pytest.raises(AppError) as exc:
        service.poll("user:alice", started["authorization_id"])

    assert exc.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert secret_body not in str(exc.value)
    assert "secret-device" not in str(exc.value)
    assert "secret-token" not in str(exc.value)


@pytest.mark.parametrize("verification_uri", [
    "https://evil.example/login/device",
    "https://user@github.com/login/device",
    "https://github.com:invalid/login/device",
    "https://github.com/login/device?continue=evil",
])
def test_invalid_verification_uri_fails_closed_without_leaking_device_code(verification_uri):
    http = ScriptedHttp(_device_response(
        device_code="must-not-leak",
        verification_uri=verification_uri,
    ))
    service, _, _ = _service(http)

    with pytest.raises(AppError) as exc:
        service.start("user:alice")

    assert exc.value.code == ErrorCode.SERVICE_UNAVAILABLE
    assert "must-not-leak" not in str(exc.value)


def test_cancel_and_disconnect_only_affect_the_current_identity():
    vault = FakeVault()
    vault.store("user:alice", COPILOT_CREDENTIAL_SOURCE, {"access_token": "alice-token"})
    vault.store("user:bob", COPILOT_CREDENTIAL_SOURCE, {"access_token": "bob-token"})
    http = ScriptedHttp(_device_response())
    service, _, _ = _service(http, vault=vault)
    started = service.start("user:alice")

    assert service.cancel("user:alice", started["authorization_id"]) == {"status": "cancelled"}
    service.disconnect("user:alice")

    assert service.status("user:alice") == {"connected": False}
    assert service.retrieve_access_token("user:bob") == "bob-token"
