# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Atomic transform + chart provenance for the analyst ``visualize`` action."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timezone
from typing import Any

from data_formulator.recipes.canonical import canonical_json_bytes
from data_formulator.recipes.lineage import ArtifactLedger, ArtifactLineageError
from data_formulator.recipes.models import ArtifactNode, ArtifactType, HashDigest
from data_formulator.recipes.table_artifacts import (
    parquet_artifact_hashes,
    table_artifact_id,
)
from data_formulator.recipes.transform_parameters import (
    normalize_transform_parameter_slots,
    validate_parameterized_transform_code,
)
from data_formulator.security.code_signing import verify_code


logger = logging.getLogger(__name__)


class MissingParentArtifactError(ArtifactLineageError):
    """A declared workspace input has no verified durable artifact."""


@dataclass(frozen=True, slots=True)
class VisualizeArtifacts:
    transform: ArtifactNode
    chart: ArtifactNode


def _normalize_input_table_names(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("At least one declared input table is required")
    names = tuple(values)
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("Every declared input table must be a non-empty string")
    if len(set(names)) != len(names):
        raise ValueError("Declared input table names must be unique")
    return names


def _artifact_output_table_id(node: ArtifactNode) -> str | None:
    execution = node.to_dict()["execution"]
    output = execution.get("output")
    if not isinstance(output, Mapping):
        return None
    table_id = output.get("table_id")
    return table_id if isinstance(table_id, str) else None


def _verify_parent_materialization(workspace, metadata, node: ArtifactNode) -> ArtifactNode:
    """Require the current table bytes/schema to match its durable parent node."""
    try:
        content_hash, schema_fingerprint = parquet_artifact_hashes(
            workspace,
            metadata,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise MissingParentArtifactError(
            f"Declared input table {metadata.name!r} cannot verify its current table"
        ) from exc
    if (
        content_hash != node.content_hash
        or schema_fingerprint != node.schema_fingerprint
    ):
        raise MissingParentArtifactError(
            f"Declared input table {metadata.name!r} does not match its current table artifact"
        )
    return node


def _resolve_parent(
    ledger: ArtifactLedger,
    workspace,
    table_name: str,
) -> ArtifactNode:
    metadata = workspace.get_table_metadata(table_name)
    if metadata is None:
        raise ValueError(f"Declared input table does not exist: {table_name}")

    linked_id = table_artifact_id(metadata)
    if linked_id is not None:
        linked = ledger.get(linked_id)
        if linked is None:
            raise MissingParentArtifactError(
                f"Declared input table {table_name!r} links to a missing artifact"
            )
        if _artifact_output_table_id(linked) != metadata.name:
            raise MissingParentArtifactError(
                f"Declared input table {table_name!r} has a mismatched artifact link"
            )
        return _verify_parent_materialization(workspace, metadata, linked)

    matches = [
        node
        for node in ledger.list_nodes()
        if node.artifact_type in (ArtifactType.LOAD, ArtifactType.TRANSFORM)
        and _artifact_output_table_id(node) == metadata.name
    ]
    if len(matches) != 1:
        raise MissingParentArtifactError(
            f"Declared input table {table_name!r} has no unambiguous parent artifact"
        )
    return _verify_parent_materialization(workspace, metadata, matches[0])


def record_visualize_artifacts(
    workspace,
    *,
    chart_id: str,
    input_table_names: Sequence[str],
    output_table_name: str,
    code: str,
    code_signature: str,
    output_variable: str,
    chart_spec: Mapping[str, Any],
    field_metadata: Mapping[str, Any],
    field_display_names: Mapping[str, Any],
    display_instruction: str,
    title: str,
    subtitle: str,
    parameter_slots: Sequence[Mapping[str, Any]] = (),
) -> VisualizeArtifacts:
    """Record one successful visualize result as an atomic two-node lineage batch."""
    names = _normalize_input_table_names(input_table_names)
    for field_name, value in (
        ("chart_id", chart_id),
        ("output_table_name", output_table_name),
        ("code", code),
        ("code_signature", code_signature),
        ("output_variable", output_variable),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} cannot be empty")
    if not verify_code(code, code_signature):
        raise ValueError("code_signature does not verify the transform code")
    slots = normalize_transform_parameter_slots(parameter_slots)
    if slots and output_variable == "params":
        raise ValueError("output_variable cannot use the reserved name 'params'")
    if slots:
        validate_parameterized_transform_code(code, slots)

    ledger = ArtifactLedger.for_workspace(workspace)
    parents = tuple(_resolve_parent(ledger, workspace, name) for name in names)
    output_metadata = workspace.get_table_metadata(output_table_name)
    if output_metadata is None:
        raise ValueError(f"Visualize output table does not exist: {output_table_name}")

    content_hash, schema_fingerprint = parquet_artifact_hashes(
        workspace,
        output_metadata,
    )
    created_at = output_metadata.created_at
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    transform_execution = {
        "kind": "python_transform",
        "code": code,
        "code_signature": code_signature,
        "output_variable": output_variable,
        "input_tables": [
            {"table_id": name, "artifact_id": parent.artifact_id}
            for name, parent in zip(names, parents)
        ],
        "output": {
            "table_id": output_metadata.name,
            "filename": output_metadata.filename,
        },
    }
    if slots:
        transform_execution["parameter_slots"] = [
            item.to_dict() for item in slots
        ]
    transform = ArtifactNode(
        artifact_type=ArtifactType.TRANSFORM,
        identity_id=workspace.identity_id,
        workspace_id=workspace.workspace_id,
        origin_id=f"visualize/{chart_id}/transform",
        parent_ids=tuple(parent.artifact_id for parent in parents),
        content_hash=content_hash,
        schema_fingerprint=schema_fingerprint,
        execution=transform_execution,
        created_at=created_at,
    )

    chart_execution = {
        "kind": "chart",
        "chart_id": chart_id,
        "chart": chart_spec,
        "field_metadata": field_metadata,
        "field_display_names": field_display_names,
        "display_instruction": display_instruction,
        "title": title,
        "subtitle": subtitle,
        "input_table": {
            "table_id": output_metadata.name,
            "artifact_id": transform.artifact_id,
        },
    }
    chart = ArtifactNode(
        artifact_type=ArtifactType.CHART,
        identity_id=workspace.identity_id,
        workspace_id=workspace.workspace_id,
        origin_id=f"visualize/{chart_id}/chart",
        parent_ids=(transform.artifact_id,),
        content_hash=HashDigest.sha256(canonical_json_bytes(chart_execution)),
        # Compatibility for a chart is governed by the data schema it consumes.
        schema_fingerprint=schema_fingerprint,
        execution=chart_execution,
        created_at=created_at,
    )

    recorded_transform, recorded_chart = ledger.record_many((transform, chart))

    # The ledger is the durable source of truth. This metadata link is a lookup
    # accelerator for subsequent same-workspace transforms, so a failure here
    # must not invalidate the already-atomic ledger batch.
    try:
        updated_options = dict(output_metadata.import_options or {})
        updated_options["artifact_id"] = recorded_transform.artifact_id
        visualize = dict(updated_options.get("visualize") or {})
        visualize.update({
            "chart_id": chart_id,
            "input_tables": list(names),
            "transform_artifact_id": recorded_transform.artifact_id,
            "chart_artifact_id": recorded_chart.artifact_id,
        })
        if slots:
            visualize["parameter_slots"] = [item.to_dict() for item in slots]
        updated_options["visualize"] = visualize
        output_metadata.import_options = updated_options
        workspace.add_table_metadata(output_metadata)
    except Exception:
        logger.warning(
            "Visualize artifacts were recorded but table metadata could not be linked",
            exc_info=True,
        )

    return VisualizeArtifacts(recorded_transform, recorded_chart)
