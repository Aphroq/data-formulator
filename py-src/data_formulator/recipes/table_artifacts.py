# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared helpers for lineage-backed workspace tables."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq

from data_formulator.datalake.workspace_metadata import TableMetadata
from data_formulator.recipes.models import HashDigest


def parquet_artifact_hashes(workspace, metadata: TableMetadata) -> tuple[HashDigest, HashDigest]:
    """Hash the complete local parquet and its persisted Arrow schema."""
    file_path = workspace.get_file_path(metadata.filename)
    if not isinstance(file_path, Path):
        raise TypeError("Durable local artifact hashing requires a filesystem path")
    schema = pq.read_schema(file_path)
    return (
        HashDigest.sha256_file(file_path),
        HashDigest.sha256(schema.serialize().to_pybytes()),
    )


def table_artifact_id(metadata: TableMetadata) -> str | None:
    """Return the lineage artifact linked from table metadata, if any."""
    options = metadata.import_options
    if not isinstance(options, Mapping):
        return None

    direct = options.get("artifact_id")
    if isinstance(direct, str) and direct:
        return direct

    for namespace in ("data_operation", "visualize"):
        provenance = options.get(namespace)
        if not isinstance(provenance, Mapping):
            continue
        key = "artifact_id" if namespace == "data_operation" else "transform_artifact_id"
        artifact_id = provenance.get(key)
        if isinstance(artifact_id, str) and artifact_id:
            return artifact_id
    return None
