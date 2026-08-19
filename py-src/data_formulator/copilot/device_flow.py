"""Bounded, identity-scoped GitHub OAuth device authorization.

LiteLLM 1.91.3 ships a GitHub Copilot ``Authenticator``, but that class stores
tokens in process-user files and may synchronously start an interactive login
from an ordinary model request.  Data Formulator owns the interactive flow
instead:

* pending device codes stay in a bounded in-memory store behind opaque handles;
* handles are bound to the authenticated Data Formulator identity;
* each poll request performs at most one upstream HTTP request and never sleeps;
* GitHub's ``interval``, ``slow_down`` and expiry semantics are enforced; and
* only the long-lived GitHub access token enters the existing encrypted vault.

The pending handle is intentionally process-local.  A server restart cancels an
unfinished login, while a completed login survives through ``CredentialVault``.
"""

from __future__ import annotations

import math
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from data_formulator.auth.vault.base import CredentialVault
from data_formulator.errors import AppError, ErrorCode

from litellm.llms.github_copilot.authenticator import (
    DEFAULT_GITHUB_CLIENT_ID as LITELLM_GITHUB_CLIENT_ID,
)


GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_VERIFICATION_URL = "https://github.com/login/device"
COPILOT_CREDENTIAL_SOURCE = "github-copilot:oauth"

_REQUEST_TIMEOUT = (3.05, 10.0)
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Data-Formulator",
}
_DEVICE_SCOPE = "read:user"
_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_USER_CODE_RE = re.compile(r"^[A-Za-z0-9-]{4,64}$")


def is_github_copilot_enabled() -> bool:
    """Return whether the independently default-off Copilot flag is enabled."""

    return os.getenv("GITHUB_COPILOT_ENABLED", "").strip().lower() in _TRUE_VALUES


@dataclass
class _PendingAuthorization:
    identity_id: str
    device_code: str
    expires_at: float
    interval: int
    next_poll_at: float
    poll_in_progress: bool = False


class CopilotDeviceFlowService:
    """Drive GitHub device authorization without exposing its bearer secrets."""

    def __init__(
        self,
        *,
        vault: CredentialVault,
        http: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        client_id: str | None = None,
        max_pending: int = 256,
    ) -> None:
        if vault is None:
            raise ValueError("vault is required")
        if max_pending < 1:
            raise ValueError("max_pending must be positive")

        resolved_client_id = (
            client_id
            if client_id is not None
            else os.getenv("GITHUB_COPILOT_CLIENT_ID", "").strip()
            or LITELLM_GITHUB_CLIENT_ID
        )
        if not isinstance(resolved_client_id, str) or not resolved_client_id.strip():
            raise ValueError("GitHub Copilot client id is required")
        if len(resolved_client_id.strip()) > 256:
            raise ValueError("GitHub Copilot client id is too long")

        self._vault = vault
        self._http = http or requests.Session()
        self._clock = clock
        self._client_id = resolved_client_id.strip()
        self._max_pending = max_pending
        self._pending: dict[str, _PendingAuthorization] = {}
        self._lock = threading.Lock()

    def start(self, identity_id: str) -> dict[str, Any]:
        """Start a device flow and return only fields safe for browser display."""

        identity_id = self._validate_identity(identity_id)
        now = self._clock()
        with self._lock:
            self._discard_expired_locked(now)
            if len(self._pending) >= self._max_pending:
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "Too many GitHub Copilot authorization requests are pending",
                    retry=True,
                )

        payload = self._post_json(
            GITHUB_DEVICE_CODE_URL,
            data={"client_id": self._client_id, "scope": _DEVICE_SCOPE},
            failure_message="GitHub Copilot authorization is temporarily unavailable",
        )
        device_code = self._required_secret(payload, "device_code", max_length=1024)
        user_code = self._required_text(payload, "user_code", max_length=64)
        if not _USER_CODE_RE.fullmatch(user_code):
            raise self._protocol_error()
        verification_uri = self._verification_uri(payload.get("verification_uri"))
        expires_in = self._bounded_int(payload.get("expires_in"), minimum=1, maximum=3600)
        interval = self._bounded_int(payload.get("interval"), minimum=1, maximum=300)

        created_at = self._clock()
        transaction = _PendingAuthorization(
            identity_id=identity_id,
            device_code=device_code,
            expires_at=created_at + expires_in,
            interval=interval,
            next_poll_at=created_at + interval,
        )
        with self._lock:
            self._discard_expired_locked(created_at)
            if len(self._pending) >= self._max_pending:
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "Too many GitHub Copilot authorization requests are pending",
                    retry=True,
                )
            authorization_id = self._new_authorization_id_locked()
            self._pending[authorization_id] = transaction

        return {
            "status": "pending",
            "authorization_id": authorization_id,
            "user_code": user_code,
            "verification_uri": verification_uri,
            "expires_in": expires_in,
            "interval": interval,
        }

    def poll(self, identity_id: str, authorization_id: str) -> dict[str, Any]:
        """Perform at most one due upstream poll; never block or sleep locally."""

        identity_id = self._validate_identity(identity_id)
        authorization_id = self._validate_authorization_id(authorization_id)
        now = self._clock()
        with self._lock:
            transaction = self._owned_transaction_locked(identity_id, authorization_id)
            if now >= transaction.expires_at:
                self._pending.pop(authorization_id, None)
                return {"status": "expired"}
            if transaction.poll_in_progress or now < transaction.next_poll_at:
                return self._pending_result(transaction, now)
            transaction.poll_in_progress = True
            # Reserve the next interval before releasing the lock so concurrent
            # browser polls cannot make duplicate upstream token requests.
            transaction.next_poll_at = now + transaction.interval

        try:
            payload = self._post_json(
                GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "device_code": transaction.device_code,
                    "grant_type": _DEVICE_GRANT,
                },
                failure_message="GitHub Copilot authorization is temporarily unavailable",
                allow_oauth_error=True,
            )
        except Exception:
            with self._lock:
                current = self._pending.get(authorization_id)
                if current is transaction:
                    transaction.poll_in_progress = False
            raise

        now = self._clock()
        with self._lock:
            current = self._pending.get(authorization_id)
            if current is not transaction or current.identity_id != identity_id:
                return {"status": "cancelled"}
            transaction.poll_in_progress = False

            access_token = payload.get("access_token")
            if access_token is not None:
                token = self._required_secret(payload, "access_token", max_length=4096)
                token_type = self._optional_text(payload.get("token_type"), max_length=32)
                scope = self._optional_text(payload.get("scope"), max_length=2048)
                credentials = {
                    "access_token": token,
                    "token_type": (token_type or "bearer").lower(),
                    "scope": scope,
                }
                if credentials["token_type"] != "bearer":
                    self._pending.pop(authorization_id, None)
                    raise self._protocol_error()
                try:
                    self._vault.store(identity_id, COPILOT_CREDENTIAL_SOURCE, credentials)
                except Exception as exc:
                    self._pending.pop(authorization_id, None)
                    raise AppError(
                        ErrorCode.SERVICE_UNAVAILABLE,
                        "GitHub Copilot credentials could not be stored",
                        retry=False,
                    ) from exc
                self._pending.pop(authorization_id, None)
                return {"status": "connected"}

            oauth_error = payload.get("error")
            if oauth_error == "authorization_pending":
                transaction.next_poll_at = now + transaction.interval
                return self._pending_result(transaction, now)
            if oauth_error == "slow_down":
                announced = self._optional_interval(payload.get("interval"))
                transaction.interval = max(
                    transaction.interval + 5,
                    announced or 0,
                )
                transaction.next_poll_at = now + transaction.interval
                return self._pending_result(transaction, now)
            if oauth_error == "access_denied":
                self._pending.pop(authorization_id, None)
                return {"status": "denied"}
            if oauth_error in {"expired_token", "token_expired"}:
                self._pending.pop(authorization_id, None)
                return {"status": "expired"}

            self._pending.pop(authorization_id, None)
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "GitHub Copilot authorization could not be completed",
                retry=False,
            )

    def cancel(self, identity_id: str, authorization_id: str) -> dict[str, str]:
        """Cancel an unfinished authorization owned by ``identity_id``."""

        identity_id = self._validate_identity(identity_id)
        authorization_id = self._validate_authorization_id(authorization_id)
        with self._lock:
            self._owned_transaction_locked(identity_id, authorization_id)
            self._pending.pop(authorization_id, None)
        return {"status": "cancelled"}

    def status(self, identity_id: str) -> dict[str, bool]:
        """Return connection state without exposing vault contents."""

        identity_id = self._validate_identity(identity_id)
        try:
            credentials = self._vault.retrieve(identity_id, COPILOT_CREDENTIAL_SOURCE)
        except Exception as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "GitHub Copilot credentials are temporarily unavailable",
                retry=True,
            ) from exc
        token = credentials.get("access_token") if isinstance(credentials, dict) else None
        return {"connected": isinstance(token, str) and bool(token.strip())}

    def retrieve_access_token(self, identity_id: str) -> str:
        """Resolve the current identity's vault token for the A5 request adapter."""

        identity_id = self._validate_identity(identity_id)
        try:
            credentials = self._vault.retrieve(identity_id, COPILOT_CREDENTIAL_SOURCE)
        except Exception as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "GitHub Copilot credentials are temporarily unavailable",
                retry=True,
            ) from exc
        token = credentials.get("access_token") if isinstance(credentials, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise AppError(
                ErrorCode.LLM_AUTH_FAILED,
                "GitHub Copilot is not connected",
                retry=False,
            )
        return token.strip()

    def disconnect(self, identity_id: str) -> dict[str, str]:
        """Delete only this identity's completed and unfinished credentials."""

        identity_id = self._validate_identity(identity_id)
        try:
            self._vault.delete(identity_id, COPILOT_CREDENTIAL_SOURCE)
        except Exception as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "GitHub Copilot credentials could not be deleted",
                retry=True,
            ) from exc
        with self._lock:
            owned = [
                handle
                for handle, pending in self._pending.items()
                if pending.identity_id == identity_id
            ]
            for handle in owned:
                self._pending.pop(handle, None)
        return {"status": "disconnected"}

    def _post_json(
        self,
        url: str,
        *,
        data: dict[str, str],
        failure_message: str,
        allow_oauth_error: bool = False,
    ) -> dict[str, Any]:
        try:
            response = self._http.post(
                url,
                headers=dict(_REQUEST_HEADERS),
                data=data,
                timeout=_REQUEST_TIMEOUT,
                allow_redirects=False,
            )
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                failure_message,
                retry=True,
            ) from exc
        except Exception as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                failure_message,
                retry=True,
            ) from exc

        if not isinstance(payload, dict):
            raise self._protocol_error()
        status_code = getattr(response, "status_code", 500)
        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            if not (allow_oauth_error and isinstance(payload.get("error"), str)):
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    failure_message,
                    retry=True,
                )
        return payload

    @staticmethod
    def _verification_uri(value: Any) -> str:
        if not isinstance(value, str):
            raise CopilotDeviceFlowService._protocol_error()
        value = value.strip()
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise CopilotDeviceFlowService._protocol_error() from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path.rstrip("/") != "/login/device"
            or parsed.query
            or parsed.fragment
        ):
            raise CopilotDeviceFlowService._protocol_error()
        return GITHUB_VERIFICATION_URL

    @staticmethod
    def _required_secret(payload: dict[str, Any], field: str, *, max_length: int) -> str:
        value = payload.get(field)
        if not isinstance(value, str):
            raise CopilotDeviceFlowService._protocol_error()
        value = value.strip()
        if not value or len(value) > max_length or any(
            ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise CopilotDeviceFlowService._protocol_error()
        return value

    @staticmethod
    def _required_text(payload: dict[str, Any], field: str, *, max_length: int) -> str:
        value = CopilotDeviceFlowService._optional_text(payload.get(field), max_length=max_length)
        if not value:
            raise CopilotDeviceFlowService._protocol_error()
        return value

    @staticmethod
    def _optional_text(value: Any, *, max_length: int) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise CopilotDeviceFlowService._protocol_error()
        value = value.strip()
        if len(value) > max_length or any(
            ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise CopilotDeviceFlowService._protocol_error()
        return value

    @staticmethod
    def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise CopilotDeviceFlowService._protocol_error()
        if value < minimum or value > maximum:
            raise CopilotDeviceFlowService._protocol_error()
        return value

    @staticmethod
    def _optional_interval(value: Any) -> int | None:
        if value is None:
            return None
        return CopilotDeviceFlowService._bounded_int(value, minimum=1, maximum=300)

    @staticmethod
    def _validate_identity(identity_id: Any) -> str:
        if not isinstance(identity_id, str) or not identity_id.strip() or len(identity_id.strip()) > 512:
            raise AppError(ErrorCode.INVALID_REQUEST, "Invalid authorization identity")
        return identity_id.strip()

    @staticmethod
    def _validate_authorization_id(authorization_id: Any) -> str:
        if (
            not isinstance(authorization_id, str)
            or not authorization_id.strip()
            or len(authorization_id.strip()) > 256
        ):
            raise AppError(ErrorCode.INVALID_REQUEST, "Invalid Copilot authorization request")
        return authorization_id.strip()

    def _owned_transaction_locked(
        self,
        identity_id: str,
        authorization_id: str,
    ) -> _PendingAuthorization:
        transaction = self._pending.get(authorization_id)
        if transaction is None or not secrets.compare_digest(transaction.identity_id, identity_id):
            # Deliberately use the same response for a missing and foreign
            # handle so callers cannot enumerate another identity's login.
            raise AppError(ErrorCode.INVALID_REQUEST, "Unknown Copilot authorization request")
        return transaction

    def _new_authorization_id_locked(self) -> str:
        while True:
            candidate = secrets.token_urlsafe(32)
            if candidate not in self._pending:
                return candidate

    def _discard_expired_locked(self, now: float) -> None:
        expired = [
            handle
            for handle, transaction in self._pending.items()
            if now >= transaction.expires_at and not transaction.poll_in_progress
        ]
        for handle in expired:
            self._pending.pop(handle, None)

    @staticmethod
    def _pending_result(transaction: _PendingAuthorization, now: float) -> dict[str, Any]:
        return {
            "status": "pending",
            "interval": transaction.interval,
            "retry_after": max(1, math.ceil(transaction.next_poll_at - now)),
        }

    @staticmethod
    def _protocol_error() -> AppError:
        return AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub Copilot returned an invalid authorization response",
            retry=False,
        )
