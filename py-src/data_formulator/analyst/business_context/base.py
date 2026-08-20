# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Small, provider-neutral contracts for analyst business context.

The identity and workspace fields are authorization context supplied by the
backend. Providers may use them to resolve a server-owned target and
credential, but must not treat them as values to forward to an external API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit


MAX_BUSINESS_CONTEXT_QUERY_CHARS = 8_000
MAX_BUSINESS_CONTEXT_LOCAL_CONTEXT_CHARS = 16_000
MAX_CONTEXT_ITEM_URI_CHARS = 2_048
MAX_CONTEXT_ITEM_TITLE_CHARS = 512
MAX_CONTEXT_ITEM_PROVIDER_CHARS = 64
_CONTEXT_ITEM_URI_SCHEMES = frozenset({"http", "https", "urn"})


def _normalized_required_text(
    value: str,
    field_name: str,
    max_chars: int,
    *,
    allow_multiline: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if len(normalized) > max_chars:
        raise ValueError(f"{field_name} exceeds the maximum length")
    allowed_controls = {"\t", "\n", "\r"} if allow_multiline else set()
    if any(
        (ord(char) < 32 or ord(char) == 127) and char not in allowed_controls
        for char in normalized
    ):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


@dataclass(frozen=True)
class BusinessContextQuery:
    """A focused question, minimal local context, and authorized scope."""

    text: str
    identity_id: str
    workspace_id: str
    context: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _normalized_required_text(
                self.text,
                "text",
                MAX_BUSINESS_CONTEXT_QUERY_CHARS,
                allow_multiline=True,
            ),
        )
        object.__setattr__(
            self,
            "identity_id",
            _normalized_required_text(self.identity_id, "identity_id", 512),
        )
        object.__setattr__(
            self,
            "workspace_id",
            _normalized_required_text(self.workspace_id, "workspace_id", 512),
        )
        if not isinstance(self.context, str):
            raise ValueError("context must be a string")
        context = self.context.strip()
        if len(context) > MAX_BUSINESS_CONTEXT_LOCAL_CONTEXT_CHARS:
            raise ValueError("context exceeds the maximum length")
        if any(
            (ord(char) < 32 or ord(char) == 127)
            and char not in {"\t", "\n", "\r"}
            for char in context
        ):
            raise ValueError("context contains control characters")
        object.__setattr__(self, "context", context)


@dataclass(frozen=True)
class ContextItem:
    """A source reference returned alongside provider context."""

    uri: str
    title: str | None = None
    provider: str = ""

    def __post_init__(self) -> None:
        uri = _normalized_required_text(
            self.uri,
            "uri",
            MAX_CONTEXT_ITEM_URI_CHARS,
        )
        if "\\" in uri:
            raise ValueError("uri is not a supported source URI")
        try:
            parsed = urlsplit(uri)
            parsed.port
        except ValueError as exc:
            raise ValueError("uri is not a valid source URI") from exc

        scheme = parsed.scheme.lower()
        if scheme not in _CONTEXT_ITEM_URI_SCHEMES:
            raise ValueError("uri uses an unsupported scheme")
        if scheme in {"http", "https"}:
            if not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("uri must contain a host and no user information")
        elif not parsed.path:
            raise ValueError("uri must contain a URN value")

        object.__setattr__(
            self,
            "uri",
            uri,
        )

        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be a string or None")
        title = self.title.strip() if self.title is not None else None
        if title == "":
            title = None
        if title is not None:
            if len(title) > MAX_CONTEXT_ITEM_TITLE_CHARS:
                raise ValueError("title exceeds the maximum length")
            if any(ord(char) < 32 for char in title):
                raise ValueError("title contains control characters")
        object.__setattr__(self, "title", title)

        if not isinstance(self.provider, str):
            raise ValueError("provider must be a string")
        provider = self.provider.strip()
        if len(provider) > MAX_CONTEXT_ITEM_PROVIDER_CHARS:
            raise ValueError("provider exceeds the maximum length")
        if any(ord(char) < 32 for char in provider):
            raise ValueError("provider contains control characters")
        object.__setattr__(self, "provider", provider)


@dataclass(frozen=True)
class BusinessContextResult:
    """Normalized context text and immutable source references."""

    text: str
    context_items: tuple[ContextItem, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        items = tuple(self.context_items)
        if not all(isinstance(item, ContextItem) for item in items):
            raise ValueError("context_items must contain ContextItem values")
        object.__setattr__(self, "context_items", items)
        object.__setattr__(self, "truncated", bool(self.truncated))


class BusinessContextErrorCategory(str, Enum):
    """Stable categories safe to expose to the agent and frontend."""

    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    PROTOCOL_ERROR = "protocol_error"


_SAFE_ERROR_MESSAGES = {
    BusinessContextErrorCategory.DISABLED: "Business context is not enabled.",
    BusinessContextErrorCategory.NOT_CONFIGURED: (
        "Business context is not configured for this workspace."
    ),
    BusinessContextErrorCategory.INVALID_REQUEST: (
        "The business context query is invalid."
    ),
    BusinessContextErrorCategory.UNAUTHORIZED: (
        "Business context authentication failed."
    ),
    BusinessContextErrorCategory.TIMEOUT: "Business context request timed out.",
    BusinessContextErrorCategory.UNAVAILABLE: (
        "Business context is temporarily unavailable."
    ),
    BusinessContextErrorCategory.PROTOCOL_ERROR: (
        "Business context returned an unexpected response."
    ),
}

_RETRYABLE_CATEGORIES = {
    BusinessContextErrorCategory.TIMEOUT,
    BusinessContextErrorCategory.UNAVAILABLE,
}


class BusinessContextError(RuntimeError):
    """Secret-free error boundary for optional external context providers."""

    def __init__(
        self,
        category: BusinessContextErrorCategory,
        *,
        status_code: int | None = None,
    ) -> None:
        self.category = category
        self.status_code = status_code
        self.retryable = category in _RETRYABLE_CATEGORIES
        super().__init__(_SAFE_ERROR_MESSAGES[category])

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(category={self.category.value!r}, "
            f"retryable={self.retryable!r}, status_code={self.status_code!r})"
        )


@runtime_checkable
class BusinessContextProvider(Protocol):
    """Provider interface consumed by a read-only analyst Skill."""

    def query(self, request: BusinessContextQuery) -> BusinessContextResult:
        ...


__all__ = [
    "MAX_BUSINESS_CONTEXT_QUERY_CHARS",
    "MAX_BUSINESS_CONTEXT_LOCAL_CONTEXT_CHARS",
    "BusinessContextError",
    "BusinessContextErrorCategory",
    "BusinessContextProvider",
    "BusinessContextQuery",
    "BusinessContextResult",
    "ContextItem",
]
