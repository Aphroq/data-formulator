# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Immutable, self-verifying artifact lineage models."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

from data_formulator.recipes.canonical import (
    FrozenJsonValue,
    canonical_sha256,
    freeze_json,
    thaw_json,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID_PATTERN = re.compile(r"^art_[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HashDigest:
    """A content digest whose algorithm is explicit on the wire."""

    algorithm: str
    digest: str

    def __post_init__(self) -> None:
        if self.algorithm != "sha256":
            raise ValueError(f"Unsupported hash algorithm: {self.algorithm!r}")
        if not _SHA256_PATTERN.fullmatch(self.digest):
            raise ValueError("SHA-256 digest must be 64 lowercase hexadecimal characters")

    @classmethod
    def sha256(cls, content: bytes) -> "HashDigest":
        if not isinstance(content, bytes):
            raise TypeError("HashDigest.sha256 requires bytes")
        return cls("sha256", hashlib.sha256(content).hexdigest())

    @classmethod
    def parse(cls, value: str) -> "HashDigest":
        if not isinstance(value, str):
            raise TypeError("Hash digest must be a string")
        algorithm, separator, digest = value.partition(":")
        if not separator:
            raise ValueError("Hash digest must include an algorithm prefix")
        return cls(algorithm, digest)

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.digest}"


class ArtifactType(str, Enum):
    LOAD = "load"
    TRANSFORM = "transform"
    CHART = "chart"
    REPORT = "report"


@dataclass(frozen=True, slots=True)
class ArtifactNode:
    """One immutable output and the durable inputs that produced it."""

    SCHEMA_VERSION: ClassVar[int] = 1

    artifact_type: ArtifactType
    identity_id: str
    workspace_id: str
    origin_id: str
    parent_ids: tuple[str, ...]
    content_hash: HashDigest
    schema_fingerprint: HashDigest
    execution: Mapping[str, FrozenJsonValue]
    created_at: datetime
    artifact_id: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            artifact_type = ArtifactType(self.artifact_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported artifact type: {self.artifact_type!r}") from exc
        object.__setattr__(self, "artifact_type", artifact_type)

        for field_name in ("identity_id", "workspace_id", "origin_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        parent_ids = tuple(self.parent_ids)
        if len(set(parent_ids)) != len(parent_ids):
            raise ValueError("parent_ids cannot contain duplicates")
        if any(not _ARTIFACT_ID_PATTERN.fullmatch(parent_id) for parent_id in parent_ids):
            raise ValueError("Every parent id must be a valid artifact id")
        if artifact_type is ArtifactType.LOAD and parent_ids:
            raise ValueError("Load artifacts cannot have parents")
        if artifact_type is not ArtifactType.LOAD and not parent_ids:
            raise ValueError(f"{artifact_type.value} artifacts require at least one parent")
        object.__setattr__(self, "parent_ids", parent_ids)

        if not isinstance(self.content_hash, HashDigest):
            raise TypeError("content_hash must be a HashDigest")
        if not isinstance(self.schema_fingerprint, HashDigest):
            raise TypeError("schema_fingerprint must be a HashDigest")
        if not isinstance(self.execution, Mapping) or not self.execution:
            raise ValueError("execution must be a non-empty JSON object")
        frozen_execution = freeze_json(self.execution)
        if not isinstance(frozen_execution, Mapping):
            raise TypeError("execution must be a JSON object")
        object.__setattr__(self, "execution", frozen_execution)

        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(timezone.utc))
        object.__setattr__(self, "artifact_id", f"art_{canonical_sha256(self.identity_payload())}")

    def identity_payload(self) -> dict[str, Any]:
        """Fields covered by ``artifact_id`` (observation time is excluded)."""
        return {
            "schema_version": self.SCHEMA_VERSION,
            "artifact_type": self.artifact_type.value,
            "identity_id": self.identity_id,
            "workspace_id": self.workspace_id,
            "origin_id": self.origin_id,
            "parent_ids": list(self.parent_ids),
            "content_hash": str(self.content_hash),
            "schema_fingerprint": str(self.schema_fingerprint),
            "execution": thaw_json(self.execution),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "artifact_id": self.artifact_id,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactNode":
        if not isinstance(data, Mapping):
            raise TypeError("Artifact node must be a JSON object")
        if data.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported artifact schema version: {data.get('schema_version')!r}"
            )

        expected_fields = {
            "schema_version",
            "artifact_id",
            "artifact_type",
            "identity_id",
            "workspace_id",
            "origin_id",
            "parent_ids",
            "content_hash",
            "schema_fingerprint",
            "execution",
            "created_at",
        }
        if set(data) != expected_fields:
            missing = sorted(expected_fields - set(data))
            unknown = sorted(set(data) - expected_fields)
            raise ValueError(f"Invalid artifact fields; missing={missing}, unknown={unknown}")

        created_at_value = data["created_at"]
        if not isinstance(created_at_value, str):
            raise TypeError("created_at must be an ISO-8601 string")
        try:
            created_at = datetime.fromisoformat(created_at_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be a valid ISO-8601 timestamp") from exc

        parent_ids_value = data["parent_ids"]
        if not isinstance(parent_ids_value, (list, tuple)):
            raise TypeError("parent_ids must be an array")

        node = cls(
            artifact_type=ArtifactType(data["artifact_type"]),
            identity_id=data["identity_id"],
            workspace_id=data["workspace_id"],
            origin_id=data["origin_id"],
            parent_ids=tuple(parent_ids_value),
            content_hash=HashDigest.parse(data["content_hash"]),
            schema_fingerprint=HashDigest.parse(data["schema_fingerprint"]),
            execution=data["execution"],
            created_at=created_at,
        )
        serialized_id = data["artifact_id"]
        if serialized_id != node.artifact_id:
            raise ValueError(
                f"Serialized artifact_id {serialized_id!r} does not match verified identity "
                f"{node.artifact_id!r}"
            )
        return node
