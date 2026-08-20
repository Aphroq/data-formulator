// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { apiRequest } from './apiClient';

export type RecipeVersionStatus = 'draft' | 'validated' | 'published' | 'archived';

export interface RecipeVersionSummary {
    version_id: string;
    recipe_id: string;
    recipe_hash: string;
    status: RecipeVersionStatus;
    created_at: string;
    validated_at: string | null;
    published_at: string | null;
    archived_at: string | null;
    validation_run_id: string | null;
}

export interface RecipeSummary {
    recipe_id: string;
    name: string;
    description: string;
    created_by: string;
    created_at: string;
    updated_at: string;
    versions: RecipeVersionSummary[];
}

export interface RecipeParameter {
    id: string;
    name: string;
    description?: string;
    type: 'string' | 'integer' | 'number' | 'boolean' | 'date' | 'datetime';
    required: boolean;
    default?: unknown;
}

export interface RecipeParameterCandidate {
    candidate_id: string;
    parameter_id: string;
    kind: 'filter' | 'limit' | 'transform';
    name: string;
    description?: string;
    type: RecipeParameter['type'];
    default: unknown;
}

export type RecipeParameterMode = 'ask' | 'keep';

export interface RecipeParameterConfiguration {
    candidate_id: string;
    name: string;
    description: string;
    mode: RecipeParameterMode;
}

export type RecipeParameterSuggestion = RecipeParameterConfiguration;

export interface RecipeParameterSuggestionResult {
    suggestions: RecipeParameterSuggestion[];
    unmatched: string[];
}

export interface RecipeInput {
    id: string;
    step_id: string;
    mode: 'refreshable' | 'pinned_snapshot' | 'external_path' | 'unresolved';
    source_id?: string;
    content_hash: string;
    expected_schema: string;
}

export interface RecipeStep {
    id: string;
    kind: 'load' | 'transform' | 'chart';
    artifact_id: string;
    dependencies: string[];
    content_hash: string;
    expected_schema: string;
    step_hash: string;
}

export interface RecipeSpec {
    recipe_id: string;
    version_id: string;
    name: string;
    description: string;
    parameters: RecipeParameter[];
    inputs: RecipeInput[];
    steps: RecipeStep[];
    final_outputs: Array<{ artifact_id: string; step_id: string; kind: string }>;
    has_unresolved_inputs?: boolean;
    [key: string]: unknown;
}

export interface RecipeVersionDetail {
    recipe: Omit<RecipeSummary, 'versions'>;
    version: RecipeVersionSummary;
    spec: RecipeSpec;
    workflow_markdown: string;
}

export interface RecipeExecutionResult {
    status: 'succeeded' | 'failed' | 'needs_review';
    run: {
        run_id: string;
        kind: 'dry_run' | 'manual';
        status: 'succeeded' | 'failed' | 'needs_review';
        manifest_hash: string;
    } | null;
    steps: Array<{
        step_id: string;
        kind: 'load' | 'transform' | 'chart';
        content_hash: string;
        schema_hash: string;
        output_path: string;
        duration_ms: number;
    }>;
    error: { code: string; exception_type: string; message: string } | null;
}

export async function compileRecipe(input: {
    targetArtifactIds: string[];
    name: string;
    description?: string;
    parameterCandidateIds?: string[];
    parameterConfigurations?: RecipeParameterConfiguration[];
}): Promise<{ version: RecipeVersionSummary; spec: RecipeSpec; workflow_markdown: string }> {
    const parameterSelection = input.parameterConfigurations !== undefined
        ? { parameter_configurations: input.parameterConfigurations }
        : { parameter_candidate_ids: input.parameterCandidateIds ?? [] };
    const { data } = await apiRequest<{
        version: RecipeVersionSummary;
        spec: RecipeSpec;
        workflow_markdown: string;
    }>('/api/recipes/compile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            target_artifact_ids: input.targetArtifactIds,
            name: input.name,
            description: input.description ?? '',
            ...parameterSelection,
        }),
    });
    return data;
}

export async function listRecipeParameterCandidates(
    targetArtifactIds: string[],
): Promise<RecipeParameterCandidate[]> {
    const { data } = await apiRequest<{ candidates: RecipeParameterCandidate[] }>(
        '/api/recipes/parameter-candidates',
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_artifact_ids: targetArtifactIds }),
        },
    );
    return data.candidates;
}

export async function suggestRecipeParameterConfigurations(input: {
    targetArtifactIds: string[];
    model: Record<string, unknown>;
    workflowContext?: Record<string, unknown>;
    name?: string;
    description?: string;
    timeoutSeconds?: number;
}): Promise<RecipeParameterSuggestionResult> {
    const { data } = await apiRequest<RecipeParameterSuggestionResult>(
        '/api/recipes/parameter-suggestions',
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_artifact_ids: input.targetArtifactIds,
                model: input.model,
                workflow_context: input.workflowContext ?? {},
                name: input.name ?? '',
                description: input.description ?? '',
                timeout_seconds: input.timeoutSeconds ?? 120,
            }),
        },
    );
    return data;
}

export async function listRecipes(): Promise<RecipeSummary[]> {
    const { data } = await apiRequest<{ recipes: RecipeSummary[] }>('/api/recipes');
    return data.recipes;
}

export async function getRecipeVersion(versionId: string): Promise<RecipeVersionDetail> {
    const { data } = await apiRequest<RecipeVersionDetail>(
        `/api/recipes/versions/${encodeURIComponent(versionId)}`,
    );
    return data;
}

async function versionAction(
    versionId: string,
    action: 'publish' | 'archive',
): Promise<RecipeVersionSummary> {
    const { data } = await apiRequest<{ version: RecipeVersionSummary }>(
        `/api/recipes/versions/${encodeURIComponent(versionId)}/${action}`,
        { method: 'POST' },
    );
    return data.version;
}

export async function dryRunRecipe(
    versionId: string,
    parameters: Record<string, unknown>,
): Promise<{ result: RecipeExecutionResult; version: RecipeVersionSummary }> {
    const { data } = await apiRequest<{
        result: RecipeExecutionResult;
        version: RecipeVersionSummary;
    }>(`/api/recipes/versions/${encodeURIComponent(versionId)}/dry-run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parameters }),
    });
    return data;
}

export const publishRecipe = (versionId: string) => versionAction(versionId, 'publish');

export async function runRecipe(
    versionId: string,
    parameters: Record<string, unknown>,
): Promise<RecipeExecutionResult> {
    const { data } = await apiRequest<{ result: RecipeExecutionResult }>(
        `/api/recipes/versions/${encodeURIComponent(versionId)}/run`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parameters }),
        },
    );
    return data.result;
}

export const archiveRecipe = (versionId: string) => versionAction(versionId, 'archive');
