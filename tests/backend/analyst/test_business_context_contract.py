# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Provider-neutral contracts for optional analyst business context."""

from __future__ import annotations

import pytest

from data_formulator.analyst.business_context.base import (
    MAX_BUSINESS_CONTEXT_LOCAL_CONTEXT_CHARS,
    MAX_BUSINESS_CONTEXT_QUERY_CHARS,
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextQuery,
    BusinessContextResult,
    ContextItem,
)
from data_formulator.analyst.business_context.trustgraph import (
    is_trustgraph_enabled,
)


pytestmark = [pytest.mark.backend]


def test_query_normalizes_authorized_context() -> None:
    query = BusinessContextQuery(
        text="  今年的收入政策是什么？  ",
        identity_id="  user:42  ",
        workspace_id="  workspace-a  ",
        context="  Filter field state; examples: active, paused.  ",
    )

    assert query.text == "今年的收入政策是什么？"
    assert query.identity_id == "user:42"
    assert query.workspace_id == "workspace-a"
    assert query.context == "Filter field state; examples: active, paused."


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", " "),
        ("identity_id", ""),
        ("workspace_id", "\t"),
    ],
)
def test_query_rejects_missing_required_values(field: str, value: str) -> None:
    values = {
        "text": "What is the policy?",
        "identity_id": "user:42",
        "workspace_id": "workspace-a",
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        BusinessContextQuery(**values)


def test_query_rejects_oversized_text() -> None:
    with pytest.raises(ValueError, match="text"):
        BusinessContextQuery(
            text="x" * (MAX_BUSINESS_CONTEXT_QUERY_CHARS + 1),
            identity_id="user:42",
            workspace_id="workspace-a",
        )


def test_query_preserves_internal_line_breaks() -> None:
    query = BusinessContextQuery(
        text="  First question\nSecond line  ",
        identity_id="user:42",
        workspace_id="workspace-a",
    )

    assert query.text == "First question\nSecond line"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", "What does active\x7f mean?"),
        ("context", "Relevant value pattern: active\x7f"),
    ],
)
def test_query_rejects_delete_control_character(
    field: str,
    value: str,
) -> None:
    values = {
        "text": "What does active mean?",
        "identity_id": "user:42",
        "workspace_id": "workspace-a",
        "context": "Relevant value pattern: active",
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        BusinessContextQuery(**values)


def test_query_allows_empty_context_but_rejects_invalid_context() -> None:
    query = BusinessContextQuery(
        text="What does active mean?",
        identity_id="user:42",
        workspace_id="workspace-a",
    )
    assert query.context == ""

    with pytest.raises(ValueError, match="context"):
        BusinessContextQuery(
            text="What does active mean?",
            identity_id="user:42",
            workspace_id="workspace-a",
            context="x" * (MAX_BUSINESS_CONTEXT_LOCAL_CONTEXT_CHARS + 1),
        )


def test_context_item_normalizes_optional_title() -> None:
    item = ContextItem(
        uri="  urn:document:alpha  ",
        title="   ",
        provider="  trustgraph  ",
    )

    assert item == ContextItem(
        uri="urn:document:alpha",
        title=None,
        provider="trustgraph",
    )


def test_context_item_rejects_empty_uri() -> None:
    with pytest.raises(ValueError, match="uri"):
        ContextItem(uri="  ")


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "data:text/plain,secret",
        "file:///etc/passwd",
        "https://user:password@example.com/source",
        "https://example.com:bad-port/source",
        "https:///missing-host",
        "urn:",
    ],
)
def test_context_item_rejects_unsafe_uri(uri: str) -> None:
    with pytest.raises(ValueError, match="uri"):
        ContextItem(uri=uri)


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/source?id=42#section",
        "http://localhost:8080/source",
        "urn:document:alpha",
    ],
)
def test_context_item_accepts_supported_uri(uri: str) -> None:
    assert ContextItem(uri=f"  {uri}  ").uri == uri


def test_result_uses_immutable_context_items() -> None:
    item = ContextItem(uri="urn:document:alpha", provider="trustgraph")
    result = BusinessContextResult(text="answer", context_items=(item,))

    assert result.context_items == (item,)
    assert result.truncated is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "  true  ", "1", "yes", "on"])
def test_trustgraph_flag_accepts_explicit_true_values(raw: str) -> None:
    assert is_trustgraph_enabled({"TRUSTGRAPH_ENABLED": raw}) is True


@pytest.mark.parametrize("raw", [None, "", "false", "0", "no", "off", "unexpected"])
def test_trustgraph_flag_fails_closed(raw: str | None) -> None:
    environment = {} if raw is None else {"TRUSTGRAPH_ENABLED": raw}
    assert is_trustgraph_enabled(environment) is False


def test_business_context_error_has_stable_secret_free_representation() -> None:
    error = BusinessContextError(
        BusinessContextErrorCategory.UNAVAILABLE,
        status_code=503,
    )

    assert error.category is BusinessContextErrorCategory.UNAVAILABLE
    assert error.retryable is True
    assert error.status_code == 503
    assert "503" in repr(error)
    assert "temporarily unavailable" in str(error).lower()
