# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only TrustGraph ontology and RDF graph integration.

The implementation deliberately uses the pinned TrustGraph Python API and its
RDF schema/translators.  A small ``Api`` subclass only supplies the security
controls that the 2.8.14 client does not expose (redirect blocking, injectable
Session, and separate connect/read timeouts).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
import os
import re
from typing import Any
from urllib.parse import urlsplit

import requests
from pyparsing import ParseResults
from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.parserutils import CompValue
from trustgraph.api import Api, ConfigKey
from trustgraph.api.api import check_error
from trustgraph.api.exceptions import ProtocolException, TrustGraphException
from trustgraph.messaging.translators.primitives import (
    TermTranslator,
    TripleTranslator,
)
from trustgraph.schema import BLANK, IRI, LITERAL, TRIPLE, Term, Triple

from data_formulator.analyst.business_context.base import (
    BusinessContextError,
    BusinessContextErrorCategory,
    BusinessContextResult,
    ContextItem,
)
from data_formulator.security.url_allowlist import validate_api_base


PROVENANCE_GRAPH_IRI = "urn:graph:source"
_FLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IRI_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+$",
)
_LANGUAGE_PATTERN = re.compile(
    r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$",
)
_SPARQL_QUERY_TYPES = {
    "SelectQuery": "select",
    "AskQuery": "ask",
    "ConstructQuery": "construct",
    "DescribeQuery": "describe",
}
_TERM_TRANSLATOR = TermTranslator()
_TRIPLE_TRANSLATOR = TripleTranslator()
_MAX_IRI_CHARS = 2_048
_MAX_LITERAL_CHARS = 32_768
_MAX_SEARCH_QUERY_CHARS = 8_000
_MAX_RDF_STAR_DEPTH = 8


def is_trustgraph_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return the default-off feature flag value without importing a Skill."""

    source = os.environ if environment is None else environment
    raw = source.get("TRUSTGRAPH_ENABLED", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _required_text(
    value: str,
    name: str,
    max_chars: int = 512,
    *,
    allow_multiline: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    if len(normalized) > max_chars:
        raise ValueError(f"{name} exceeds the maximum length")
    allowed_controls = {"\t", "\n", "\r"} if allow_multiline else set()
    if any(
        (ord(char) < 32 or ord(char) == 127) and char not in allowed_controls
        for char in normalized
    ):
        raise ValueError(f"{name} contains control characters")
    return normalized


def _bounded_integer(
    value: int,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _positive_timeout(value: float, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0 or normalized > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return normalized


def _normalize_iri(value: str, name: str) -> str:
    iri = _required_text(value, name, _MAX_IRI_CHARS)
    if not _IRI_PATTERN.fullmatch(iri):
        raise ValueError(f"{name} must be an absolute RDF IRI")
    return iri


@dataclass(frozen=True)
class TrustGraphTarget:
    """Validated server-owned route for a TrustGraph knowledge target."""

    name: str
    api_base: str
    flow_id: str
    collection: str
    trustgraph_workspace: str
    ontology_id: str
    credential_ref: str
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 30.0
    max_sparql_chars: int = 8_000
    max_results: int = 100
    max_response_chars: int = 131_072
    max_context_items: int = 50

    def __post_init__(self) -> None:
        for field_name in (
            "name",
            "collection",
            "trustgraph_workspace",
            "ontology_id",
            "credential_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )

        flow_id = _required_text(self.flow_id, "flow_id", 128)
        if not _FLOW_ID_PATTERN.fullmatch(flow_id):
            raise ValueError("flow_id contains unsupported path characters")
        object.__setattr__(self, "flow_id", flow_id)

        api_base = _required_text(self.api_base, "api_base", 2_048)
        if "\\" in api_base:
            raise ValueError("api_base must be a canonical HTTPS URL")
        parsed = urlsplit(api_base)
        if parsed.scheme.lower() != "https":
            raise ValueError("api_base must use HTTPS")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("api_base must not contain user information")
        if parsed.query or parsed.fragment:
            raise ValueError("api_base must not contain a query or fragment")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("api_base contains an invalid port") from exc
        api_base = api_base.rstrip("/")
        validate_api_base(f"{api_base}/", require_configured=True)
        object.__setattr__(self, "api_base", api_base)

        object.__setattr__(
            self,
            "connect_timeout_seconds",
            _positive_timeout(
                self.connect_timeout_seconds,
                "connect_timeout_seconds",
                60.0,
            ),
        )
        object.__setattr__(
            self,
            "read_timeout_seconds",
            _positive_timeout(
                self.read_timeout_seconds,
                "read_timeout_seconds",
                300.0,
            ),
        )
        _bounded_integer(self.max_sparql_chars, "max_sparql_chars", 1, 32_000)
        _bounded_integer(self.max_results, "max_results", 1, 1_000)
        _bounded_integer(
            self.max_response_chars,
            "max_response_chars",
            200,
            1_000_000,
        )
        _bounded_integer(
            self.max_context_items,
            "max_context_items",
            1,
            100,
        )


@dataclass(frozen=True)
class TrustGraphRdfTerm:
    """A typed RDF object filter accepted from the analyst tool schema."""

    kind: str
    value: str
    datatype: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"iri", "literal"}:
            raise ValueError("kind must be iri or literal")
        if self.kind == "iri":
            object.__setattr__(self, "value", _normalize_iri(self.value, "value"))
            if self.datatype is not None or self.language is not None:
                raise ValueError("IRI terms cannot have datatype or language")
            return

        object.__setattr__(
            self,
            "value",
            _required_text(
                self.value,
                "value",
                _MAX_LITERAL_CHARS,
                allow_multiline=True,
            ),
        )
        if self.datatype is not None and self.language is not None:
            raise ValueError("literal datatype and language are mutually exclusive")
        if self.datatype is not None:
            object.__setattr__(
                self,
                "datatype",
                _normalize_iri(self.datatype, "datatype"),
            )
        if self.language is not None:
            language = _required_text(self.language, "language", 64)
            if not _LANGUAGE_PATTERN.fullmatch(language):
                raise ValueError("language is not a valid language tag")
            object.__setattr__(self, "language", language)

    @classmethod
    def from_tool(cls, raw: Any) -> "TrustGraphRdfTerm":
        if not isinstance(raw, Mapping):
            raise ValueError("object must be an RDF term object")
        if set(raw) - {"kind", "value", "datatype", "language"}:
            raise ValueError("object contains unsupported fields")
        for required_field in ("kind", "value"):
            if not isinstance(raw.get(required_field), str):
                raise ValueError(f"object {required_field} must be a string")
        for optional_field in ("datatype", "language"):
            if optional_field in raw and not isinstance(
                raw[optional_field],
                str,
            ):
                raise ValueError(
                    f"object {optional_field} must be a string",
                )
        return cls(
            kind=raw["kind"],
            value=raw["value"],
            datatype=raw.get("datatype"),
            language=raw.get("language"),
        )

    def to_sdk_term(self) -> Term:
        if self.kind == "iri":
            return Term(type=IRI, iri=self.value)
        return Term(
            type=LITERAL,
            value=self.value,
            datatype=self.datatype or "",
            language=self.language or "",
        )


@dataclass(frozen=True)
class TrustGraphTripleQuery:
    """A bounded S/P/O query with a server-defined graph choice."""

    subject: str | None = None
    predicate: str | None = None
    object: TrustGraphRdfTerm | None = None
    graph: str = "knowledge"
    limit: int = 50

    def __post_init__(self) -> None:
        if self.subject is not None:
            object.__setattr__(
                self,
                "subject",
                _normalize_iri(self.subject, "subject"),
            )
        if self.predicate is not None:
            object.__setattr__(
                self,
                "predicate",
                _normalize_iri(self.predicate, "predicate"),
            )
        if self.object is not None and not isinstance(
            self.object,
            TrustGraphRdfTerm,
        ):
            raise ValueError("object must be a TrustGraphRdfTerm")
        if self.graph not in {"knowledge", "provenance"}:
            raise ValueError("graph must be knowledge or provenance")
        _bounded_integer(self.limit, "limit", 1, 1_000)


@dataclass(frozen=True)
class TrustGraphEntitySearch:
    """A bounded semantic query over entities in the bound collection."""

    query: str
    limit: int = 10

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query",
            _required_text(
                self.query,
                "query",
                _MAX_SEARCH_QUERY_CHARS,
                allow_multiline=True,
            ),
        )
        _bounded_integer(self.limit, "limit", 1, 1_000)


@dataclass(frozen=True)
class TrustGraphRowsQuery:
    """An explicit GraphQL query against rows in the bound collection."""

    query: str
    variables: dict[str, Any] | None = None
    operation_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query",
            _required_text(
                self.query,
                "query",
                32_000,
                allow_multiline=True,
            ),
        )
        if self.variables is not None:
            if not isinstance(self.variables, Mapping) or any(
                not isinstance(key, str) for key in self.variables
            ):
                raise ValueError("variables must be an object with string keys")
            try:
                normalized_variables = json.loads(json.dumps(
                    dict(self.variables),
                    ensure_ascii=False,
                    allow_nan=False,
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError("variables must contain JSON values") from exc
            object.__setattr__(self, "variables", normalized_variables)
        if self.operation_name is not None:
            object.__setattr__(
                self,
                "operation_name",
                _required_text(
                    self.operation_name,
                    "operation_name",
                    256,
                ),
            )


@dataclass(frozen=True)
class TrustGraphSparqlQuery:
    """A bounded raw SPARQL query; syntax is validated against the target."""

    query: str
    limit: int = 100

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "query",
            _required_text(
                self.query,
                "query",
                32_000,
                allow_multiline=True,
            ),
        )
        _bounded_integer(self.limit, "limit", 1, 1_000)


def _contains_service(node: Any, seen: set[int] | None = None) -> bool:
    if isinstance(node, (str, bytes, bytearray)) or node is None:
        return False
    if seen is None:
        seen = set()
    node_id = id(node)
    if node_id in seen:
        return False
    seen.add(node_id)

    if isinstance(node, CompValue):
        if node.name == "ServiceGraphPattern":
            return True
        return any(_contains_service(value, seen) for value in node.values())
    if isinstance(node, ParseResults):
        return any(_contains_service(value, seen) for value in node)
    if isinstance(node, Mapping):
        return any(_contains_service(value, seen) for value in node.values())
    if isinstance(node, Sequence):
        return any(_contains_service(value, seen) for value in node)
    return False


def validate_sparql_query(query: str, *, max_chars: int) -> str:
    """Parse a read-only SPARQL query and return its normalized query type."""

    normalized = _required_text(
        query,
        "query",
        max_chars,
        allow_multiline=True,
    )
    try:
        parsed = parseQuery(normalized)
        query_node = parsed[1]
        query_type = _SPARQL_QUERY_TYPES.get(query_node.name)
    except Exception as exc:
        raise ValueError("query is not valid SPARQL") from exc
    if query_type is None:
        raise ValueError("query is not a supported read query")
    if _contains_service(parsed):
        raise ValueError("SPARQL SERVICE is not allowed")
    return query_type


class _RestrictedTrustGraphApi(Api):
    """Pinned official API with the repository's outbound request controls."""

    def __init__(
        self,
        *,
        target: TrustGraphTarget,
        token: str,
        session: requests.Session | None,
    ) -> None:
        super().__init__(
            url=target.api_base,
            timeout=target.read_timeout_seconds,
            token=token,
            workspace=target.trustgraph_workspace,
        )
        self._session = session or requests.Session()
        self._timeout = (
            target.connect_timeout_seconds,
            target.read_timeout_seconds,
        )
        flow_prefix = f"flow/{target.flow_id}/service/"
        self._allowed_paths = frozenset({
            "config",
            "flow",
            "collection-management",
            "librarian",
            "knowledge",
            f"{flow_prefix}embeddings",
            f"{flow_prefix}graph-embeddings",
            f"{flow_prefix}rows",
            f"{flow_prefix}triples",
            f"{flow_prefix}sparql",
        })

    def request(self, path: str, request: dict[str, Any]) -> dict[str, Any]:
        if path not in self._allowed_paths or not isinstance(request, dict):
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        body = dict(request)
        workspace = body.setdefault("workspace", self.workspace)
        if workspace != self.workspace:
            raise BusinessContextError(
                BusinessContextErrorCategory.UNAUTHORIZED,
            )
        try:
            response = self._session.post(
                f"{self.url}{path}",
                json=body,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.Timeout as exc:
            raise BusinessContextError(
                BusinessContextErrorCategory.TIMEOUT,
            ) from exc
        except requests.RequestException as exc:
            raise BusinessContextError(
                BusinessContextErrorCategory.UNAVAILABLE,
            ) from exc

        status_code = response.status_code
        if status_code in {401, 403}:
            raise BusinessContextError(
                BusinessContextErrorCategory.UNAUTHORIZED,
                status_code=status_code,
            )
        if status_code == 429 or status_code >= 500:
            raise BusinessContextError(
                BusinessContextErrorCategory.UNAVAILABLE,
                status_code=status_code,
            )
        if status_code != 200:
            raise BusinessContextError(
                BusinessContextErrorCategory.PROTOCOL_ERROR,
                status_code=status_code,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise BusinessContextError(
                BusinessContextErrorCategory.PROTOCOL_ERROR,
                status_code=status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise BusinessContextError(
                BusinessContextErrorCategory.PROTOCOL_ERROR,
                status_code=status_code,
            )
        error = payload.get("error")
        if path.endswith("/rows") and isinstance(error, Mapping):
            error_type = error.get("type")
            error_message = error.get("message")
            normalized_message = (
                error_message.casefold()
                if isinstance(error_message, str)
                else ""
            )
            if (
                error_type == "rows-query-error"
                and "no graphql schema available" in normalized_message
                and "no schemas loaded" in normalized_message
            ):
                raise BusinessContextError(
                    BusinessContextErrorCategory.NOT_CONFIGURED,
                    status_code=status_code,
                )
        try:
            if error is not None:
                check_error(payload)
        except TrustGraphException as exc:
            raise BusinessContextError(
                BusinessContextErrorCategory.UNAVAILABLE,
                status_code=status_code,
            ) from exc
        return payload


def _validated_token(value: str) -> str:
    if not isinstance(value, str):
        raise BusinessContextError(
            BusinessContextErrorCategory.NOT_CONFIGURED,
        )
    token = value.strip()
    if not token or any(ord(char) < 32 or ord(char) == 127 for char in token):
        raise BusinessContextError(
            BusinessContextErrorCategory.NOT_CONFIGURED,
        )
    return token


def _term_to_data(term: Term, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(term, Term) or depth > _MAX_RDF_STAR_DEPTH:
        raise ValueError("invalid RDF term")
    if term.type == IRI:
        return {
            "type": "iri",
            "value": _required_text(term.iri, "iri", _MAX_IRI_CHARS),
        }
    if term.type == BLANK:
        return {
            "type": "blank_node",
            "value": _required_text(term.id, "blank_node", _MAX_IRI_CHARS),
        }
    if term.type == LITERAL:
        result: dict[str, Any] = {
            "type": "literal",
            "value": _required_text(
                term.value,
                "literal",
                _MAX_LITERAL_CHARS,
                allow_multiline=True,
            ),
        }
        if term.datatype and term.language:
            raise ValueError("literal contains datatype and language")
        if term.datatype:
            result["datatype"] = _normalize_iri(term.datatype, "datatype")
        if term.language:
            language = _required_text(term.language, "language", 64)
            if not _LANGUAGE_PATTERN.fullmatch(language):
                raise ValueError("invalid language tag")
            result["language"] = language
        return result
    if term.type == TRIPLE and isinstance(term.triple, Triple):
        return {
            "type": "quoted_triple",
            "triple": _triple_to_data(term.triple, depth=depth + 1),
        }
    raise ValueError("unknown RDF term type")


def _triple_to_data(triple: Triple, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(triple, Triple):
        raise ValueError("invalid RDF triple")
    if triple.s is None or triple.p is None or triple.o is None:
        raise ValueError("incomplete RDF triple")
    result = {
        "subject": _term_to_data(triple.s, depth=depth),
        "predicate": _term_to_data(triple.p, depth=depth),
        "object": _term_to_data(triple.o, depth=depth),
    }
    if triple.g is not None:
        result["graph"] = _normalize_iri(triple.g, "graph")
    return result


def _decode_triple(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("triple is not an object")
    return _triple_to_data(_TRIPLE_TRANSLATOR.decode(dict(raw)))


def _decode_term(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("binding is not an RDF term")
    return _term_to_data(_TERM_TRANSLATOR.decode(dict(raw)))


def _context_items(payload: Any, *, limit: int) -> tuple[ContextItem, ...]:
    items: list[ContextItem] = []
    seen: set[str] = set()

    def visit(value: Any, depth: int = 0) -> None:
        if len(items) >= limit or depth > 20:
            return
        if isinstance(value, Mapping):
            for child in value.values():
                visit(child, depth + 1)
            return
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for child in value:
                visit(child, depth + 1)
            return
        if not isinstance(value, str) or value in seen:
            return
        try:
            item = ContextItem(uri=value, provider="trustgraph")
        except ValueError:
            return
        seen.add(value)
        items.append(item)

    visit(payload)
    return tuple(items)


def _bounded_json(
    payload: Mapping[str, Any],
    *,
    max_chars: int,
) -> tuple[str, bool]:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(encoded) <= max_chars:
        return encoded, False

    prefix = encoded
    operation = payload.get("operation", "trustgraph")
    while True:
        envelope = {
            "operation": operation,
            "truncated": True,
            "json_prefix": prefix,
        }
        candidate = json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(candidate) <= max_chars:
            return candidate, True
        excess = len(candidate) - max_chars
        if not prefix:
            raise ValueError("response budget cannot hold truncation envelope")
        prefix = prefix[:-max(1, excess)]


def _result(
    payload: Mapping[str, Any],
    *,
    target: TrustGraphTarget,
    truncated: bool = False,
) -> BusinessContextResult:
    text, size_truncated = _bounded_json(
        payload,
        max_chars=target.max_response_chars,
    )
    return BusinessContextResult(
        text=text,
        context_items=_context_items(
            payload,
            limit=target.max_context_items,
        ),
        truncated=truncated or size_truncated,
    )


def _normalize_ontology(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("ontology is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("ontology is not an object")
    return dict(value)


def _normalize_sparql_response(
    raw: Any,
    *,
    expected_type: str,
    limit: int,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(raw, Mapping) or raw.get("query-type") != expected_type:
        raise ValueError("unexpected SPARQL response type")
    truncated = False
    payload: dict[str, Any] = {
        "operation": "sparql",
        "query_type": expected_type,
    }

    if expected_type == "ask":
        answer = raw.get("ask-result")
        if not isinstance(answer, bool):
            raise ValueError("ASK response is not boolean")
        payload["result"] = answer
        return payload, False

    if expected_type in {"construct", "describe"}:
        triples = raw.get("triples")
        if not isinstance(triples, Sequence) or isinstance(
            triples,
            (str, bytes, bytearray),
        ):
            raise ValueError("SPARQL graph response is not a triple list")
        selected = list(triples[:limit])
        truncated = len(triples) > limit
        payload["triples"] = [_decode_triple(item) for item in selected]
        payload["truncated"] = truncated
        return payload, truncated

    variables = raw.get("variables")
    bindings = raw.get("bindings")
    if (
        not isinstance(variables, Sequence)
        or isinstance(variables, (str, bytes, bytearray))
        or not all(isinstance(item, str) and item for item in variables)
        or len(set(variables)) != len(variables)
        or not isinstance(bindings, Sequence)
        or isinstance(bindings, (str, bytes, bytearray))
    ):
        raise ValueError("SELECT response is malformed")
    selected_bindings = list(bindings[:limit])
    truncated = len(bindings) > limit
    rows: list[dict[str, Any]] = []
    for binding in selected_bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("SELECT binding is not an object")
        values = binding.get("values")
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes, bytearray))
            or len(values) != len(variables)
        ):
            raise ValueError("SELECT binding width does not match variables")
        rows.append({
            variable: _decode_term(value)
            for variable, value in zip(variables, values, strict=True)
        })
    payload["variables"] = list(variables)
    payload["rows"] = rows
    payload["truncated"] = truncated
    return payload, truncated


def _plain_text(value: Any, name: str, max_chars: int = 32_768) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if len(normalized) > max_chars:
        raise ValueError(f"{name} exceeds the maximum length")
    if any(
        (ord(char) < 32 or ord(char) == 127)
        and char not in {"\t", "\n", "\r"}
        for char in normalized
    ):
        raise ValueError(f"{name} contains control characters")
    return normalized


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise ValueError(f"{name} must be a list")
    return [
        _required_text(item, name, 2_048)
        for item in value
    ]


def _iso_timestamp(value: Any, name: str) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if not callable(isoformat):
        raise ValueError(f"{name} is not a timestamp")
    return _required_text(isoformat(), name, 128)


def _embedding_vector(value: Any) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != 1
    ):
        raise ValueError("embedding response must contain one vector")
    raw_vector = value[0]
    if not isinstance(raw_vector, Sequence) or isinstance(
        raw_vector,
        (str, bytes, bytearray),
    ) or not raw_vector:
        raise ValueError("embedding vector is empty")
    vector: list[float] = []
    for component in raw_vector:
        if isinstance(component, bool) or not isinstance(
            component,
            (int, float),
        ):
            raise ValueError("embedding component is not numeric")
        normalized = float(component)
        if not math.isfinite(normalized):
            raise ValueError("embedding component is not finite")
        vector.append(normalized)
    return vector


def _normalize_entity_results(
    raw: Any,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(raw, Sequence) or isinstance(
        raw,
        (str, bytes, bytearray),
    ):
        raise ValueError("entity response is not a list")
    selected = list(raw[:limit])
    entities: list[dict[str, Any]] = []
    for item in selected:
        if not isinstance(item, Mapping):
            raise ValueError("entity result is not an object")
        entity = _decode_term(item.get("entity"))
        score = item.get("score")
        if entity is None:
            raise ValueError("entity result has no RDF term")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError("entity score is not numeric")
        normalized_score = float(score)
        if not math.isfinite(normalized_score):
            raise ValueError("entity score is not finite")
        entities.append({"entity": entity, "score": normalized_score})
    return entities, len(raw) > limit


def _json_copy(value: Any, name: str) -> Any:
    try:
        return json.loads(json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        ))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not valid JSON") from exc


def _normalize_rows_response(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not ({"data", "errors"} & set(raw)):
        raise ValueError("GraphQL response has no data or errors")

    data = raw.get("data")
    if data is not None and not isinstance(data, Mapping):
        raise ValueError("GraphQL data is not an object")

    errors = raw.get("errors", [])
    if not isinstance(errors, Sequence) or isinstance(
        errors,
        (str, bytes, bytearray),
    ) or any(not isinstance(error, Mapping) for error in errors):
        raise ValueError("GraphQL errors are not an object list")

    extensions = raw.get("extensions")
    if extensions is not None and not isinstance(extensions, Mapping):
        raise ValueError("GraphQL extensions are not an object")

    return {
        "operation": "rows",
        "data": _json_copy(data, "GraphQL data"),
        "errors": _json_copy(list(errors), "GraphQL errors"),
        "extensions": _json_copy(extensions, "GraphQL extensions"),
    }


class TrustGraphClient:
    """Bounded read-only facade over the official TrustGraph Python API."""

    def __init__(
        self,
        target: TrustGraphTarget,
        *,
        session: requests.Session | None = None,
    ) -> None:
        if not isinstance(target, TrustGraphTarget):
            raise ValueError("target must be a TrustGraphTarget")
        self._target = target
        self._session = session

    def _api(self, bearer_token: str) -> _RestrictedTrustGraphApi:
        return _RestrictedTrustGraphApi(
            target=self._target,
            token=_validated_token(bearer_token),
            session=self._session,
        )

    @staticmethod
    def _map_sdk_error(exc: Exception) -> BusinessContextError:
        if isinstance(exc, BusinessContextError):
            return exc
        if isinstance(exc, requests.Timeout):
            return BusinessContextError(BusinessContextErrorCategory.TIMEOUT)
        if isinstance(exc, requests.RequestException):
            return BusinessContextError(BusinessContextErrorCategory.UNAVAILABLE)
        if isinstance(exc, TrustGraphException):
            return BusinessContextError(BusinessContextErrorCategory.UNAVAILABLE)
        if isinstance(exc, ProtocolException):
            return BusinessContextError(BusinessContextErrorCategory.PROTOCOL_ERROR)
        return BusinessContextError(BusinessContextErrorCategory.PROTOCOL_ERROR)

    def inspect_catalog(self, *, bearer_token: str) -> BusinessContextResult:
        """Return the resources available to the bound TrustGraph workspace."""

        try:
            api = self._api(bearer_token)
            flows = _string_list(api.flow().list(), "flow")

            raw_collections = api.collection().list_collections()
            if not isinstance(raw_collections, Sequence) or isinstance(
                raw_collections,
                (str, bytes, bytearray),
            ):
                raise ValueError("collection response is not a list")
            collections = [{
                "id": _required_text(
                    getattr(collection, "collection"),
                    "collection",
                    2_048,
                ),
                "name": _plain_text(
                    getattr(collection, "name"),
                    "collection name",
                ),
                "description": _plain_text(
                    getattr(collection, "description"),
                    "collection description",
                ),
                "tags": _string_list(
                    getattr(collection, "tags"),
                    "collection tag",
                ),
            } for collection in raw_collections]

            raw_documents = api.library().get_documents()
            if not isinstance(raw_documents, Sequence) or isinstance(
                raw_documents,
                (str, bytes, bytearray),
            ):
                raise ValueError("document response is not a list")
            documents: list[dict[str, Any]] = []
            for document in raw_documents:
                parent_id = _plain_text(
                    getattr(document, "parent_id"),
                    "document parent_id",
                    2_048,
                )
                documents.append({
                    "id": _required_text(
                        getattr(document, "id"),
                        "document id",
                        2_048,
                    ),
                    "title": _plain_text(
                        getattr(document, "title"),
                        "document title",
                    ),
                    "kind": _required_text(
                        getattr(document, "kind"),
                        "document kind",
                        512,
                    ),
                    "tags": _string_list(
                        getattr(document, "tags"),
                        "document tag",
                    ),
                    "parent_id": parent_id or None,
                    "document_type": _plain_text(
                        getattr(document, "document_type"),
                        "document type",
                        512,
                    ),
                    "created_at": _iso_timestamp(
                        getattr(document, "time"),
                        "document time",
                    ),
                })

            raw_processing = api.library().get_processings()
            if not isinstance(raw_processing, Sequence) or isinstance(
                raw_processing,
                (str, bytes, bytearray),
            ):
                raise ValueError("processing response is not a list")
            processing = [{
                "id": _required_text(
                    getattr(item, "id"),
                    "processing id",
                    2_048,
                ),
                "document_id": _required_text(
                    getattr(item, "document_id"),
                    "processing document_id",
                    2_048,
                ),
                "flow": _required_text(
                    getattr(item, "flow"),
                    "processing flow",
                    2_048,
                ),
                "collection": _required_text(
                    getattr(item, "collection"),
                    "processing collection",
                    2_048,
                ),
                "tags": _string_list(
                    getattr(item, "tags"),
                    "processing tag",
                ),
                "started_at": _iso_timestamp(
                    getattr(item, "time"),
                    "processing time",
                ),
            } for item in raw_processing]

            knowledge_cores = _string_list(
                api.knowledge().list_kg_cores(),
                "knowledge core",
            )
            return _result(
                {
                    "operation": "catalog",
                    "active": {
                        "flow_id": self._target.flow_id,
                        "collection": self._target.collection,
                        "ontology_id": self._target.ontology_id,
                    },
                    "flows": flows,
                    "collections": collections,
                    "documents": documents,
                    "processing": processing,
                    "knowledge_cores": knowledge_cores,
                },
                target=self._target,
            )
        except BusinessContextError:
            raise
        except Exception as exc:
            raise self._map_sdk_error(exc) from exc

    def search_entities(
        self,
        query: TrustGraphEntitySearch,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        """Find graph entities using TrustGraph's embedding services."""

        if not isinstance(query, TrustGraphEntitySearch):
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        if query.limit > self._target.max_results:
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        try:
            flow = self._api(bearer_token).flow().id(self._target.flow_id)
            vector = _embedding_vector(flow.embeddings([query.query]))
            response = flow.request(
                "service/graph-embeddings",
                {
                    "vector": vector,
                    "collection": self._target.collection,
                    "limit": query.limit,
                },
            )
            entities, truncated = _normalize_entity_results(
                response.get("entities"),
                limit=query.limit,
            )
            return _result(
                {
                    "operation": "entity_search",
                    "query": query.query,
                    "entities": entities,
                    "truncated": truncated,
                },
                target=self._target,
                truncated=truncated,
            )
        except BusinessContextError:
            raise
        except Exception as exc:
            raise self._map_sdk_error(exc) from exc

    def query_rows(
        self,
        query: TrustGraphRowsQuery,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        """Run an explicit GraphQL rows query without materializing a table."""

        if not isinstance(query, TrustGraphRowsQuery):
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        try:
            response = self._api(bearer_token).flow().id(
                self._target.flow_id,
            ).rows_query(
                query.query,
                collection=self._target.collection,
                variables=query.variables,
                operation_name=query.operation_name,
            )
            return _result(
                _normalize_rows_response(response),
                target=self._target,
            )
        except BusinessContextError:
            raise
        except Exception as exc:
            raise self._map_sdk_error(exc) from exc

    def get_ontology(self, *, bearer_token: str) -> BusinessContextResult:
        try:
            values = self._api(bearer_token).config().get([
                ConfigKey(type="ontology", key=self._target.ontology_id),
            ])
            matches = [
                value
                for value in values
                if value.type == "ontology"
                and value.key == self._target.ontology_id
            ]
            if len(matches) != 1 or matches[0].value is None:
                raise BusinessContextError(
                    BusinessContextErrorCategory.NOT_CONFIGURED,
                )
            ontology = _normalize_ontology(matches[0].value)
            return _result(
                {
                    "operation": "ontology",
                    "ontology_id": self._target.ontology_id,
                    "ontology": ontology,
                },
                target=self._target,
            )
        except BusinessContextError:
            raise
        except Exception as exc:
            raise self._map_sdk_error(exc) from exc

    def query_triples(
        self,
        query: TrustGraphTripleQuery,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        if not isinstance(query, TrustGraphTripleQuery):
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        if query.limit > self._target.max_results:
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        graph_iri = (
            PROVENANCE_GRAPH_IRI if query.graph == "provenance" else ""
        )
        request: dict[str, Any] = {
            "collection": self._target.collection,
            "limit": query.limit,
            "streaming": False,
            "g": graph_iri,
        }
        if query.subject is not None:
            request["s"] = _TERM_TRANSLATOR.encode(
                Term(type=IRI, iri=query.subject),
            )
        if query.predicate is not None:
            request["p"] = _TERM_TRANSLATOR.encode(
                Term(type=IRI, iri=query.predicate),
            )
        if query.object is not None:
            request["o"] = _TERM_TRANSLATOR.encode(query.object.to_sdk_term())

        try:
            response = self._api(bearer_token).flow().id(
                self._target.flow_id,
            ).request("service/triples", request)
            raw_triples = response.get("response")
            if not isinstance(raw_triples, Sequence) or isinstance(
                raw_triples,
                (str, bytes, bytearray),
            ):
                raise ValueError("triples response is not a list")
            selected = list(raw_triples[:query.limit])
            truncated = len(raw_triples) > query.limit
            payload = {
                "operation": "triples",
                "graph": query.graph,
                "named_graph": graph_iri or None,
                "triples": [_decode_triple(item) for item in selected],
                "truncated": truncated,
            }
            return _result(
                payload,
                target=self._target,
                truncated=truncated,
            )
        except BusinessContextError:
            raise
        except Exception as exc:
            raise self._map_sdk_error(exc) from exc

    def query_sparql(
        self,
        query: TrustGraphSparqlQuery,
        *,
        bearer_token: str,
    ) -> BusinessContextResult:
        if not isinstance(query, TrustGraphSparqlQuery):
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        if query.limit > self._target.max_results:
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            )
        try:
            query_type = validate_sparql_query(
                query.query,
                max_chars=self._target.max_sparql_chars,
            )
        except (TypeError, ValueError) as exc:
            raise BusinessContextError(
                BusinessContextErrorCategory.INVALID_REQUEST,
            ) from exc

        try:
            response = self._api(bearer_token).flow().id(
                self._target.flow_id,
            ).sparql_query(
                query.query,
                collection=self._target.collection,
                limit=query.limit,
            )
            payload, truncated = _normalize_sparql_response(
                response,
                expected_type=query_type,
                limit=query.limit,
            )
            return _result(
                payload,
                target=self._target,
                truncated=truncated,
            )
        except BusinessContextError:
            raise
        except Exception as exc:
            raise self._map_sdk_error(exc) from exc


__all__ = [
    "PROVENANCE_GRAPH_IRI",
    "TrustGraphClient",
    "TrustGraphEntitySearch",
    "TrustGraphRdfTerm",
    "TrustGraphRowsQuery",
    "TrustGraphSparqlQuery",
    "TrustGraphTarget",
    "TrustGraphTripleQuery",
    "is_trustgraph_enabled",
    "validate_sparql_query",
]
