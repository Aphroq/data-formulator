"""Request-local adapter for LiteLLM 1.91.3's GitHub Copilot provider.

LiteLLM's bundled Copilot ``Authenticator`` is designed for a single CLI
identity: constructing it creates a shared token directory, and a missing token
can start a blocking OAuth device flow.  Data Formulator already owns device
authorization and encrypted identity-scoped storage, so this module installs a
strictly version-guarded method adapter on that existing class.

The adapter itself carries no global credential.  A :class:`ContextVar` points
to a ``CopilotTokenManager`` only while one Data Formulator model request is
being dispatched.  The manager exchanges that identity's vault-backed GitHub
token for a short-lived Copilot token and caches it only for the lifetime of the
request/client.  Two threads or async contexts therefore cannot share tokens,
and calls outside an application-owned context fail instead of touching files
or launching interactive login.
"""

from __future__ import annotations

import hashlib
import inspect
import threading
import textwrap
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

import requests

from litellm.llms.github_copilot.authenticator import Authenticator
from litellm.llms.github_copilot.chat.transformation import GithubCopilotConfig
from litellm.llms.github_copilot.common_utils import (
    GetAccessTokenError,
    GetAPIKeyError,
    GetDeviceCodeError,
)

from data_formulator.errors import AppError, ErrorCode


SUPPORTED_LITELLM_VERSION = "1.91.3"
_AUTHENTICATOR_SHA256 = "a18fc8b27d3566802e16395c8a4ae375d038129377b410a9caa70f999af60b05"
_CHAT_CONFIG_SHA256 = "6775d4e0105f4df49b8b0c471c30097fd33cd7fe76209fc4427167ea712c8979"

COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_API_BASE = "https://api.githubcopilot.com"

_REQUEST_TIMEOUT = (3.05, 10.0)
_REFRESH_MARGIN_SECONDS = 60.0
_MAX_TOKEN_CHARS = 16_384
_MAX_TOKEN_LIFETIME_SECONDS = 86_400.0
_install_lock = threading.Lock()
_installed = False


def _source_sha256(value: Any) -> str:
    try:
        source = textwrap.dedent(inspect.getsource(value))
    except (OSError, TypeError) as exc:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub Copilot integration does not match the audited LiteLLM contract",
            retry=False,
        ) from exc
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def verify_litellm_copilot_contract() -> dict[str, str]:
    """Fail closed unless the installed provider matches the audited source."""

    try:
        version = importlib_metadata.version("litellm")
    except importlib_metadata.PackageNotFoundError as exc:
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub Copilot requires the audited LiteLLM version",
            retry=False,
        ) from exc

    authenticator_hash = _source_sha256(Authenticator)
    chat_config_hash = _source_sha256(GithubCopilotConfig)
    if (
        version != SUPPORTED_LITELLM_VERSION
        or authenticator_hash != _AUTHENTICATOR_SHA256
        or chat_config_hash != _CHAT_CONFIG_SHA256
    ):
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub Copilot integration does not match the audited LiteLLM contract",
            retry=False,
        )

    # These transformation modules import the class object directly.  The
    # request-local method patch is safe only while every audited path refers to
    # the same class.
    from litellm.llms.github_copilot import authenticator as authenticator_module
    from litellm.llms.github_copilot.chat import transformation as chat_module
    from litellm.llms.github_copilot.embedding import transformation as embedding_module
    from litellm.llms.github_copilot.responses import transformation as responses_module

    if not all(
        reference is Authenticator
        for reference in (
            authenticator_module.Authenticator,
            chat_module.Authenticator,
            embedding_module.Authenticator,
            responses_module.Authenticator,
        )
    ):
        raise AppError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "GitHub Copilot integration does not match the audited LiteLLM contract",
            retry=False,
        )

    return {
        "version": version,
        "authenticator_sha256": authenticator_hash,
        "chat_config_sha256": chat_config_hash,
    }


@dataclass(frozen=True)
class _CopilotCredential:
    token: str
    expires_at: float
    api_base: str


_active_manager: ContextVar["CopilotTokenManager | None"] = ContextVar(
    "data_formulator_copilot_token_manager",
    default=None,
)


class CopilotTokenManager:
    """Exchange one identity's GitHub token for request-local Copilot tokens."""

    def __init__(
        self,
        github_access_token: str,
        *,
        http: Any | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(github_access_token, str):
            raise ValueError("GitHub access token is required")
        github_access_token = github_access_token.strip()
        if (
            not github_access_token
            or len(github_access_token) > _MAX_TOKEN_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in github_access_token)
        ):
            raise ValueError("Invalid GitHub access token")
        self._github_access_token = github_access_token
        # The manager lives for one Data Formulator client/request.  Direct
        # requests avoids leaving a per-request Session pool to be finalized.
        self._http = http or requests
        self._clock = clock
        self._credential: _CopilotCredential | None = None
        self._lock = threading.Lock()

    @contextmanager
    def activate(self) -> Iterator["CopilotTokenManager"]:
        """Expose this manager only to the current thread/async context."""

        install_litellm_copilot_adapter()
        token = _active_manager.set(self)
        try:
            yield self
        finally:
            _active_manager.reset(token)

    def get_access_token(self) -> str:
        """Return the vault-backed GitHub token only inside the active context."""

        return self._github_access_token

    def get_api_key(self) -> str:
        return self._get_credential().token

    def get_api_base(self) -> str:
        return self._get_credential().api_base

    def _get_credential(self) -> _CopilotCredential:
        with self._lock:
            now = self._clock()
            if (
                self._credential is not None
                and self._credential.expires_at - now > _REFRESH_MARGIN_SECONDS
            ):
                return self._credential
            self._credential = self._exchange(now)
            return self._credential

    def _exchange(self, now: float) -> _CopilotCredential:
        headers = {
            "accept": "application/json",
            "editor-version": "vscode/1.85.1",
            "editor-plugin-version": "copilot/1.155.0",
            "user-agent": "GithubCopilot/1.155.0",
            "accept-encoding": "gzip,deflate,br",
            "content-type": "application/json",
            "authorization": f"token {self._github_access_token}",
        }
        try:
            response = self._http.get(
                COPILOT_TOKEN_URL,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise AppError(
                ErrorCode.LLM_SERVICE_ERROR,
                "GitHub Copilot token service is temporarily unavailable",
                retry=True,
            ) from exc
        except Exception as exc:
            raise AppError(
                ErrorCode.LLM_SERVICE_ERROR,
                "GitHub Copilot token service is temporarily unavailable",
                retry=True,
            ) from exc

        status_code = getattr(response, "status_code", 500)
        if status_code in (401, 403):
            raise AppError(
                ErrorCode.LLM_AUTH_FAILED,
                "GitHub Copilot authentication failed; reconnect your account",
                retry=False,
            )
        if status_code == 429 or isinstance(status_code, int) and status_code >= 500:
            raise AppError(
                ErrorCode.LLM_SERVICE_ERROR,
                "GitHub Copilot token service is temporarily unavailable",
                retry=True,
            )
        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            raise AppError(
                ErrorCode.LLM_SERVICE_ERROR,
                "GitHub Copilot token request failed",
                retry=False,
            )

        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise self._protocol_error() from exc
        except Exception as exc:
            raise self._protocol_error() from exc
        if not isinstance(payload, dict):
            raise self._protocol_error()

        token = payload.get("token")
        if (
            not isinstance(token, str)
            or not token.strip()
            or len(token.strip()) > _MAX_TOKEN_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in token.strip())
        ):
            raise self._protocol_error()

        expires_at = payload.get("expires_at")
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
            or expires_at <= now
            or expires_at - now > _MAX_TOKEN_LIFETIME_SECONDS
        ):
            raise self._protocol_error()

        api_base = COPILOT_API_BASE
        endpoints = payload.get("endpoints")
        if endpoints is not None:
            if not isinstance(endpoints, dict):
                raise self._protocol_error()
            candidate = endpoints.get("api")
            if candidate is not None:
                api_base = self._validate_api_base(candidate)

        return _CopilotCredential(
            token=token.strip(),
            expires_at=float(expires_at),
            api_base=api_base,
        )

    @staticmethod
    def _validate_api_base(value: Any) -> str:
        if not isinstance(value, str) or len(value) > 2048:
            raise CopilotTokenManager._protocol_error()
        value = value.strip().rstrip("/")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise CopilotTokenManager._protocol_error() from exc
        hostname = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not (
                hostname == "api.githubcopilot.com"
                or hostname.endswith(".githubcopilot.com")
            )
            or port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise CopilotTokenManager._protocol_error()
        return value

    @staticmethod
    def _protocol_error() -> AppError:
        return AppError(
            ErrorCode.LLM_SERVICE_ERROR,
            "GitHub Copilot returned an invalid token response",
            retry=False,
        )


def _require_manager(error_type: type[Exception]) -> CopilotTokenManager:
    manager = _active_manager.get()
    if manager is None:
        raise error_type(
            message="GitHub Copilot requires application-managed authentication",
            status_code=401,
        )
    return manager


def _patched_ensure_token_dir(_self: Authenticator) -> None:
    # Authenticator.__init__ still computes its normal path attributes for
    # compatibility, but it must never create or read those paths.
    return None


def _patched_get_access_token(_self: Authenticator) -> str:
    return _require_manager(GetAccessTokenError).get_access_token()


def _patched_get_api_key(_self: Authenticator) -> str:
    return _require_manager(GetAPIKeyError).get_api_key()


def _patched_get_api_base(_self: Authenticator) -> str:
    return _require_manager(GetAPIKeyError).get_api_base()


def _blocked_get_device_code(_self: Authenticator) -> dict[str, str]:
    raise GetDeviceCodeError(
        message="Interactive GitHub Copilot authentication is disabled",
        status_code=401,
    )


def _blocked_poll_for_access_token(_self: Authenticator, _device_code: str) -> str:
    raise GetAccessTokenError(
        message="Interactive GitHub Copilot authentication is disabled",
        status_code=401,
    )


def _blocked_login(_self: Authenticator) -> str:
    raise GetAccessTokenError(
        message="Interactive GitHub Copilot authentication is disabled",
        status_code=401,
    )


def install_litellm_copilot_adapter() -> None:
    """Install the audited class-method adapter once for this process."""

    global _installed
    if _installed:
        return
    with _install_lock:
        if _installed:
            return
        verify_litellm_copilot_contract()
        Authenticator._ensure_token_dir = _patched_ensure_token_dir  # type: ignore[method-assign]
        Authenticator.get_access_token = _patched_get_access_token  # type: ignore[method-assign]
        Authenticator.get_api_key = _patched_get_api_key  # type: ignore[method-assign]
        Authenticator.get_api_base = _patched_get_api_base  # type: ignore[method-assign]
        Authenticator._get_device_code = _blocked_get_device_code  # type: ignore[method-assign]
        Authenticator._poll_for_access_token = _blocked_poll_for_access_token  # type: ignore[method-assign]
        Authenticator._login = _blocked_login  # type: ignore[method-assign]
        _installed = True
