from __future__ import annotations

import pytest

from data_formulator.datalake.workspace import Workspace
from data_formulator.recipes.compiler import CompiledRecipe
from data_formulator.recipes.models import HashDigest
from data_formulator.recipes.spec import (
    CredentialReference,
    InputMode,
    RecipeInput,
    RecipeOutput,
    RecipeSpec,
    RecipeStep,
    RecipeStepKind,
)


@pytest.fixture
def recipe_workspace(tmp_path) -> Workspace:
    return Workspace(
        "user:alice",
        root_dir=tmp_path / "workspaces",
        workspace_id="ws-1",
    )


@pytest.fixture
def compiled_recipe(recipe_workspace: Workspace) -> CompiledRecipe:
    artifact_id = "art_" + "1" * 64
    step_id = "step_" + "1" * 64
    content_hash = HashDigest.sha256(b"orders")
    schema_hash = HashDigest.sha256(b"orders-schema")
    step = RecipeStep(
        id=step_id,
        kind=RecipeStepKind.LOAD,
        artifact_id=artifact_id,
        dependencies=(),
        execution={
            "kind": "connector_query",
            "step": {
                "kind": "connector_query",
                "source_id": "warehouse",
                "table_key": "public.orders",
                "display_name": "Orders",
                "source_table": "public.orders",
            },
            "output": {
                "table_id": "orders",
                "filename": "orders.parquet",
            },
        },
        content_hash=content_hash,
        expected_schema=schema_hash,
    )
    spec = RecipeSpec(
        recipe_id="rcp_" + "2" * 64,
        name="Orders",
        description="Refresh the orders table.",
        created_by=recipe_workspace.identity_id,
        identity_id=recipe_workspace.identity_id,
        workspace_id=recipe_workspace.workspace_id,
        target_artifact_ids=(artifact_id,),
        steps=(step,),
        parameters=(),
        bindings=(),
        inputs=(RecipeInput(
            id="input_" + "1" * 64,
            step_id=step_id,
            mode=InputMode.REFRESHABLE,
            source_id="warehouse",
            credential_ref=CredentialReference("connector", "warehouse"),
            content_hash=content_hash,
            expected_schema=schema_hash,
        ),),
        final_outputs=(RecipeOutput(
            artifact_id=artifact_id,
            step_id=step_id,
            kind=RecipeStepKind.LOAD,
        ),),
        compiler_version="test-compiler/1",
    )
    return CompiledRecipe(spec=spec, workflow_markdown="# Orders\n")
