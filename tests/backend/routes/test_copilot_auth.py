from __future__ import annotations

from unittest.mock import Mock

import pytest
from flask import Flask

from data_formulator.error_handler import register_error_handlers
from data_formulator.errors import AppError
from data_formulator.routes import copilot_auth


pytestmark = [pytest.mark.backend]


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def status(self, identity_id: str):
        self.calls.append(("status", identity_id))
        return {"connected": False}

    def start(self, identity_id: str):
        self.calls.append(("start", identity_id))
        return {
            "status": "pending",
            "authorization_id": "opaque-handle",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

    def poll(self, identity_id: str, authorization_id: str):
        self.calls.append(("poll", identity_id, authorization_id))
        return {"status": "pending", "interval": 5, "retry_after": 5}

    def cancel(self, identity_id: str, authorization_id: str):
        self.calls.append(("cancel", identity_id, authorization_id))
        return {"status": "cancelled"}

    def disconnect(self, identity_id: str):
        self.calls.append(("disconnect", identity_id))
        return {"status": "disconnected"}


@pytest.fixture
def route_client(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_error_handlers(app)
    app.register_blueprint(copilot_auth.copilot_auth_bp)

    service = FakeService()
    identity = ["user:alice"]
    monkeypatch.setattr(copilot_auth, "is_github_copilot_enabled", lambda: True)
    monkeypatch.setattr(copilot_auth, "get_identity_id", lambda: identity[0])
    monkeypatch.setattr(copilot_auth, "get_copilot_device_flow_service", lambda: service)
    return app.test_client(), service, identity


def test_status_and_start_use_the_authenticated_identity(route_client):
    client, service, _ = route_client

    status = client.get("/api/copilot/auth/status").get_json()
    started = client.post("/api/copilot/auth/device/start", json={}).get_json()

    assert status == {"status": "success", "data": {"connected": False}}
    assert started["status"] == "success"
    assert started["data"]["authorization_id"] == "opaque-handle"
    assert "device_code" not in started["data"]
    assert "access_token" not in started["data"]
    assert service.calls == [("status", "user:alice"), ("start", "user:alice")]


def test_poll_cancel_and_disconnect_are_forwarded_without_credentials(route_client):
    client, service, identity = route_client
    identity[0] = "user:bob"

    poll = client.post(
        "/api/copilot/auth/device/poll",
        json={"authorization_id": "opaque-bob"},
    ).get_json()
    cancel = client.post(
        "/api/copilot/auth/device/cancel",
        json={"authorization_id": "opaque-bob"},
    ).get_json()
    disconnected = client.post("/api/copilot/auth/disconnect", json={}).get_json()

    assert poll["data"] == {"status": "pending", "interval": 5, "retry_after": 5}
    assert cancel["data"] == {"status": "cancelled"}
    assert disconnected["data"] == {"status": "disconnected"}
    assert service.calls == [
        ("poll", "user:bob", "opaque-bob"),
        ("cancel", "user:bob", "opaque-bob"),
        ("disconnect", "user:bob"),
    ]


def test_completed_connection_and_disconnect_invalidate_only_that_identity(
    route_client,
    monkeypatch,
):
    client, service, identity = route_client
    identity[0] = "user:carol"
    capability_store = Mock()
    monkeypatch.setattr(
        copilot_auth,
        "copilot_capability_store",
        capability_store,
        raising=False,
    )
    service.poll = Mock(return_value={"status": "connected"})

    connected = client.post(
        "/api/copilot/auth/device/poll",
        json={"authorization_id": "opaque-carol"},
    ).get_json()
    disconnected = client.post("/api/copilot/auth/disconnect", json={}).get_json()

    assert connected["data"] == {"status": "connected"}
    assert disconnected["data"] == {"status": "disconnected"}
    assert capability_store.invalidate_identity.call_args_list == [
        (("user:carol",),),
        (("user:carol",),),
    ]


def test_disconnected_status_invalidates_stale_capabilities(route_client, monkeypatch):
    client, _, identity = route_client
    identity[0] = "user:dana"
    capability_store = Mock()
    monkeypatch.setattr(
        copilot_auth,
        "copilot_capability_store",
        capability_store,
    )

    response = client.get("/api/copilot/auth/status").get_json()

    assert response["data"] == {"connected": False}
    capability_store.invalidate_identity.assert_called_once_with("user:dana")


@pytest.mark.parametrize(
    ("path", "json_body"),
    [
        ("/api/copilot/auth/device/poll", None),
        ("/api/copilot/auth/device/poll", {}),
        ("/api/copilot/auth/device/poll", {"authorization_id": 123}),
        ("/api/copilot/auth/device/cancel", {}),
    ],
)
def test_handle_routes_reject_invalid_request_bodies(route_client, path, json_body):
    client, service, _ = route_client
    kwargs = {} if json_body is None else {"json": json_body}

    response = client.post(path, **kwargs).get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_REQUEST"
    assert service.calls == []


def test_directly_registered_routes_still_fail_closed_when_flag_is_disabled(
    route_client,
    monkeypatch,
):
    client, service, _ = route_client
    monkeypatch.setattr(copilot_auth, "is_github_copilot_enabled", lambda: False)

    response = client.get("/api/copilot/auth/status").get_json()

    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert service.calls == []


def test_service_factory_reuses_the_vault_and_fails_when_vault_is_missing(monkeypatch):
    vault = Mock()
    monkeypatch.setattr(copilot_auth, "_service", None)
    monkeypatch.setattr(copilot_auth, "_service_vault", None)
    monkeypatch.setattr(copilot_auth, "get_credential_vault", lambda: vault)

    first = copilot_auth.get_copilot_device_flow_service()
    second = copilot_auth.get_copilot_device_flow_service()

    assert first is second

    monkeypatch.setattr(copilot_auth, "_service", None)
    monkeypatch.setattr(copilot_auth, "_service_vault", None)
    monkeypatch.setattr(copilot_auth, "get_credential_vault", lambda: None)
    with pytest.raises(AppError) as exc:
        copilot_auth.get_copilot_device_flow_service()
    assert getattr(exc.value, "code", None) == "SERVICE_UNAVAILABLE"
