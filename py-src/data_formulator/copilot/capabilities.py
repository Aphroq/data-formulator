"""Identity-scoped GitHub Copilot capability probes.

Candidates come only from the server-side model registry.  This module reads
LiteLLM's already-loaded ``model_cost`` mapping directly to reject non-chat
models; it deliberately never calls ``get_model_info``, because the audited
Copilot provider can instantiate its interactive authenticator from metadata
paths too.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import litellm


_PROVIDER_PREFIX = "github_copilot/"
_PROBE_TIMEOUT_SECONDS = 8
# Output ceilings for tiny health-check responses only.  They do not configure
# or reduce the model's input context window, and normal Agent requests do not
# use them.
_CHAT_PROBE_MAX_OUTPUT_TOKENS = 8
_TOOL_PROBE_MAX_OUTPUT_TOKENS = 32
_MAX_STREAM_CHUNKS = 128
_DEFAULT_MAX_ENTRIES = 256
_TOOL_NAME = "report_capability"

_PROBE_MESSAGES = [
    {"role": "user", "content": "Reply with the single word ok."},
]
_TOOL_MESSAGES = [
    {
        "role": "user",
        "content": (
            "Call report_capability exactly once with ok=true. "
            "Do not answer in plain text."
        ),
    },
]
_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": "Report that the model can issue a tool call.",
        "parameters": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    },
}


def _member(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_choice(value: Any) -> Any:
    choices = _member(value, "choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        raise ValueError("missing choices")
    return choices[0]


def _validate_buffered_chat(value: Any) -> None:
    if _member(_first_choice(value), "message") is None:
        raise ValueError("missing message")


def _close_stream(value: Any) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        close()


def _validate_content_stream(value: Any) -> None:
    try:
        iterator = iter(value)
    except TypeError as exc:
        raise ValueError("not a stream") from exc

    try:
        for index, chunk in enumerate(iterator):
            if index >= _MAX_STREAM_CHUNKS:
                break
            try:
                delta = _member(_first_choice(chunk), "delta")
            except ValueError:
                continue
            content = _member(delta, "content")
            reasoning = _member(delta, "reasoning_content")
            if (
                isinstance(content, str) and bool(content)
                or isinstance(reasoning, str) and bool(reasoning)
            ):
                return
        raise ValueError("stream contained no content delta")
    finally:
        _close_stream(value)


def _validate_tool_stream(value: Any) -> None:
    try:
        iterator = iter(value)
    except TypeError as exc:
        raise ValueError("not a stream") from exc

    try:
        for index, chunk in enumerate(iterator):
            if index >= _MAX_STREAM_CHUNKS:
                break
            try:
                delta = _member(_first_choice(chunk), "delta")
            except ValueError:
                continue
            tool_calls = _member(delta, "tool_calls") or []
            if not isinstance(tool_calls, (list, tuple)):
                continue
            for tool_call in tool_calls:
                function = _member(tool_call, "function")
                if _member(function, "name") == _TOOL_NAME:
                    return
        raise ValueError("stream contained no expected tool call")
    finally:
        _close_stream(value)


@dataclass(frozen=True)
class CopilotCapabilityResult:
    model_id: str
    model: str
    checked_at: float
    chat: bool
    streaming: bool
    tools: bool
    chat_error: str | None = None
    streaming_error: str | None = None
    tools_error: str | None = None

    @property
    def qualified(self) -> bool:
        return self.chat and self.streaming and self.tools

    @property
    def error_codes(self) -> dict[str, str]:
        return {
            name: code
            for name, code in (
                ("chat", self.chat_error),
                ("streaming", self.streaming_error),
                ("tools", self.tools_error),
            )
            if code is not None
        }

    def public_capabilities(self) -> dict[str, bool]:
        return {
            "chat": self.chat,
            "streaming": self.streaming,
            "tools": self.tools,
        }


class CopilotCapabilityStore:
    """Probe and cache results without caching any credential material."""

    def __init__(
        self,
        *,
        model_catalog: Mapping[str, Any] | None = None,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float | None = None,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        if (
            ttl_seconds is not None and ttl_seconds <= 0
        ) or max_entries <= 0:
            raise ValueError("Capability cache bounds must be positive")
        self._model_catalog = model_catalog if model_catalog is not None else litellm.model_cost
        self._clock = clock
        # Successful capabilities are not authorization state: the vault is
        # still checked on every real model request.  Keep them for this
        # bounded process lifetime by default so an idle UI does not suddenly
        # lose a previously qualified model.  Tests/callers may opt into TTL.
        self._ttl_seconds = float(ttl_seconds) if ttl_seconds is not None else None
        self._max_entries = int(max_entries)
        self._entries: OrderedDict[
            tuple[str, str], tuple[CopilotCapabilityResult, float | None]
        ] = OrderedDict()
        self._lock = threading.Lock()

    def probe(
        self,
        identity_id: str,
        model_id: str,
        model: str,
        client_factory: Callable[[], Any],
    ) -> CopilotCapabilityResult:
        """Run the three independent probes and cache only stable booleans/codes."""

        checked_at = self._clock()
        catalog_key = (
            model
            if model.lower().startswith(_PROVIDER_PREFIX)
            else f"{_PROVIDER_PREFIX}{model}"
        )
        catalog_info = self._model_catalog.get(catalog_key)
        mode = catalog_info.get("mode") if isinstance(catalog_info, Mapping) else None
        if mode != "chat":
            result = CopilotCapabilityResult(
                model_id=model_id,
                model=model,
                checked_at=checked_at,
                chat=False,
                streaming=False,
                tools=False,
                chat_error="unsupported_mode",
                streaming_error="unsupported_mode",
                tools_error="unsupported_mode",
            )
            self._put(identity_id, result)
            return result

        try:
            client = client_factory()
        except Exception:
            result = CopilotCapabilityResult(
                model_id=model_id,
                model=model,
                checked_at=checked_at,
                chat=False,
                streaming=False,
                tools=False,
                chat_error="client_unavailable",
                streaming_error="client_unavailable",
                tools_error="client_unavailable",
            )
            self._put(identity_id, result)
            return result

        chat = streaming = tools = False
        chat_error = streaming_error = tools_error = None

        try:
            response = client.get_completion(
                _PROBE_MESSAGES,
                stream=False,
                max_tokens=_CHAT_PROBE_MAX_OUTPUT_TOKENS,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
            _validate_buffered_chat(response)
            chat = True
        except Exception:
            chat_error = "chat_failed"

        try:
            response = client.get_completion(
                _PROBE_MESSAGES,
                stream=True,
                max_tokens=_CHAT_PROBE_MAX_OUTPUT_TOKENS,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
            _validate_content_stream(response)
            streaming = True
        except Exception:
            streaming_error = "streaming_failed"

        try:
            response = client.get_completion_with_tools(
                _TOOL_MESSAGES,
                [_PROBE_TOOL],
                stream=True,
                max_tokens=_TOOL_PROBE_MAX_OUTPUT_TOKENS,
                timeout=_PROBE_TIMEOUT_SECONDS,
                parallel_tool_calls=False,
                tool_choice={
                    "type": "function",
                    "function": {"name": _TOOL_NAME},
                },
            )
            _validate_tool_stream(response)
            tools = True
        except Exception:
            tools_error = "tools_failed"

        result = CopilotCapabilityResult(
            model_id=model_id,
            model=model,
            checked_at=checked_at,
            chat=chat,
            streaming=streaming,
            tools=tools,
            chat_error=chat_error,
            streaming_error=streaming_error,
            tools_error=tools_error,
        )
        self._put(identity_id, result)
        return result

    def get_qualified(
        self,
        identity_id: str,
        model_id: str,
    ) -> CopilotCapabilityResult | None:
        key = (identity_id, model_id)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            result, expires_at = entry
            if expires_at is not None and expires_at <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return result if result.qualified else None

    def invalidate_identity(self, identity_id: str) -> None:
        with self._lock:
            for key in [key for key in self._entries if key[0] == identity_id]:
                self._entries.pop(key, None)

    def _put(self, identity_id: str, result: CopilotCapabilityResult) -> None:
        key = (identity_id, result.model_id)
        with self._lock:
            expires_at = (
                result.checked_at + self._ttl_seconds
                if self._ttl_seconds is not None
                else None
            )
            self._entries[key] = (result, expires_at)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


copilot_capability_store = CopilotCapabilityStore()
