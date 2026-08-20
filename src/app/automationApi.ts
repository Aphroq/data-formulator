// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { apiRequest, assertDownloadResponseOk } from './apiClient';
import { fetchWithIdentity } from './utils';


export type AutomationRunStatus =
    | 'queued'
    | 'running'
    | 'succeeded'
    | 'failed'
    | 'needs_review'
    | 'cancelled';

export type AutomationParameterPolicy =
    | { source: 'literal'; value: unknown }
    | { source: 'scheduled_date'; offset_days: number }
    | { source: 'scheduled_datetime'; offset_days: number };

export interface AutomationSchedule {
    schedule_id: string;
    version_id: string;
    name: string;
    cron_expression: string;
    timezone: string;
    enabled: boolean;
    next_run_at: string;
    created_at: string;
    updated_at: string;
    parameter_policy: Record<string, AutomationParameterPolicy>;
}

export interface AutomationRunArtifact {
    run_id: string;
    path: string;
    manifest_hash: string;
    binding_hash: string;
}

export interface AutomationRun {
    run_id: string;
    version_id: string;
    schedule_id: string | null;
    trigger: 'scheduled' | 'manual';
    scheduled_for: string;
    status: AutomationRunStatus;
    attempt_count: number;
    available_at: string;
    cancel_requested_at: string | null;
    artifact: AutomationRunArtifact | null;
    error: { code: string; message: string } | null;
    created_at: string;
    updated_at: string;
    parameters: Record<string, unknown>;
}

export interface AutomationRunEvent {
    sequence: number;
    step_id: string;
    kind: 'load' | 'transform' | 'chart';
    status: string;
    recorded_at: string;
    details?: Record<string, unknown>;
}

export interface AutomationRunManifest {
    run_id: string;
    recipe_id: string;
    version_id: string;
    kind: 'automation';
    status: 'succeeded' | 'failed' | 'needs_review' | 'cancelled';
    binding_hash: string;
    error: { code: string; exception_type: string; message: string } | null;
    files: Record<string, { hash: string; size: number }>;
    [key: string]: unknown;
}

export interface AutomationRunResultColumn {
    name: string;
    type: 'string' | 'boolean' | 'integer' | 'number' | 'date' | 'datetime' | 'time' | 'duration';
}

export interface AutomationRunResultTable {
    name: string;
    row_count: number;
    column_count: number;
    columns: AutomationRunResultColumn[];
    rows: Record<string, unknown>[];
    rows_truncated: boolean;
    columns_truncated: boolean;
}

export interface AutomationRunResultChart {
    spec: {
        chart_type: string;
        encodings: Record<string, string>;
        config?: Record<string, unknown>;
        [key: string]: unknown;
    };
    field_metadata: Record<string, unknown>;
    field_display_names: Record<string, string>;
}

export interface AutomationRunResultOutput {
    step_id: string;
    kind: 'load' | 'transform' | 'chart';
    title: string;
    subtitle: string;
    display_instruction: string;
    chart: AutomationRunResultChart | null;
    table: AutomationRunResultTable;
}

export interface AutomationRunResultReport {
    title: string;
    description: string;
    parameters: Array<{
        id: string;
        name: string;
        description: string;
        type: 'string' | 'integer' | 'number' | 'boolean' | 'date' | 'datetime';
    }>;
    steps: Array<{
        step_id: string;
        kind: 'load' | 'transform' | 'chart';
        title: string;
    }>;
}

export interface AutomationRunResult {
    manifest: AutomationRunManifest;
    events: AutomationRunEvent[];
    report: AutomationRunResultReport;
    outputs: AutomationRunResultOutput[];
}

export interface AutomationRunAnalysisInsight {
    finding: string;
    evidence: string;
}

export interface AutomationRunAnalysis {
    summary: string;
    insights: AutomationRunAnalysisInsight[];
    caveat: string;
}

export interface AutomationRunTableSampleRequest {
    size: number;
    offset: number;
    method: 'head' | 'bottom' | 'random';
    order_by_fields: string[];
    select_fields?: string[];
    aggregate_fields_and_functions?: Array<[string | null, string]>;
    filters?: Record<string, unknown>[];
    search?: string;
}

export interface AutomationRunTableSample {
    rows: Record<string, unknown>[];
    total_row_count: number;
}

export async function listSchedules(): Promise<AutomationSchedule[]> {
    const { data } = await apiRequest<{ schedules: AutomationSchedule[] }>(
        '/api/automation/schedules',
    );
    return data.schedules;
}

export async function createSchedule(input: {
    versionId: string;
    name: string;
    cronExpression: string;
    timezone: string;
    parameterPolicy?: Record<string, AutomationParameterPolicy>;
}): Promise<AutomationSchedule> {
    const { data } = await apiRequest<{ schedule: AutomationSchedule }>(
        '/api/automation/schedules',
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                version_id: input.versionId,
                name: input.name,
                cron_expression: input.cronExpression,
                timezone: input.timezone,
                parameter_policy: input.parameterPolicy ?? {},
            }),
        },
    );
    return data.schedule;
}

export async function updateSchedule(
    scheduleId: string,
    input: {
        name?: string;
        cronExpression?: string;
        timezone?: string;
        parameterPolicy?: Record<string, AutomationParameterPolicy>;
    },
): Promise<AutomationSchedule> {
    const { data } = await apiRequest<{ schedule: AutomationSchedule }>(
        `/api/automation/schedules/${encodeURIComponent(scheduleId)}`,
        {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...(input.name === undefined ? {} : { name: input.name }),
                ...(input.cronExpression === undefined
                    ? {}
                    : { cron_expression: input.cronExpression }),
                ...(input.timezone === undefined ? {} : { timezone: input.timezone }),
                ...(input.parameterPolicy === undefined
                    ? {}
                    : { parameter_policy: input.parameterPolicy }),
            }),
        },
    );
    return data.schedule;
}

export async function setScheduleEnabled(
    scheduleId: string,
    enabled: boolean,
): Promise<AutomationSchedule> {
    const action = enabled ? 'enable' : 'disable';
    const { data } = await apiRequest<{ schedule: AutomationSchedule }>(
        `/api/automation/schedules/${encodeURIComponent(scheduleId)}/${action}`,
        { method: 'POST' },
    );
    return data.schedule;
}

export async function enqueueManualRun(
    versionId: string,
    parameters: Record<string, unknown> = {},
): Promise<AutomationRun> {
    const { data } = await apiRequest<{ run: AutomationRun }>(
        '/api/automation/runs/manual',
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version_id: versionId, parameters }),
        },
    );
    return data.run;
}

export async function listAutomationRuns(options: {
    limit?: number;
    status?: AutomationRunStatus;
} = {}): Promise<AutomationRun[]> {
    const query = new URLSearchParams();
    if (options.limit !== undefined) query.set('limit', String(options.limit));
    if (options.status !== undefined) query.set('status', options.status);
    const suffix = query.size > 0 ? `?${query.toString()}` : '';
    const { data } = await apiRequest<{ runs: AutomationRun[] }>(
        `/api/automation/runs${suffix}`,
    );
    return data.runs;
}

export async function getAutomationRun(runId: string): Promise<AutomationRun> {
    const { data } = await apiRequest<{ run: AutomationRun }>(
        `/api/automation/runs/${encodeURIComponent(runId)}`,
    );
    return data.run;
}

export async function cancelAutomationRun(runId: string): Promise<AutomationRun> {
    const { data } = await apiRequest<{ run: AutomationRun }>(
        `/api/automation/runs/${encodeURIComponent(runId)}/cancel`,
        { method: 'POST' },
    );
    return data.run;
}

export async function getRunManifest(
    runId: string,
): Promise<AutomationRunManifest> {
    const { data } = await apiRequest<{ manifest: AutomationRunManifest }>(
        `/api/automation/runs/${encodeURIComponent(runId)}/manifest`,
    );
    return data.manifest;
}

export async function getRunEvents(runId: string): Promise<AutomationRunEvent[]> {
    const { data } = await apiRequest<{ events: AutomationRunEvent[] }>(
        `/api/automation/runs/${encodeURIComponent(runId)}/events`,
    );
    return data.events;
}

export async function getRunResult(runId: string): Promise<AutomationRunResult> {
    const { data } = await apiRequest<{ result: AutomationRunResult }>(
        `/api/automation/runs/${encodeURIComponent(runId)}/result`,
    );
    return data.result;
}

export async function analyzeRunResult(
    runId: string,
    input: {
        model: Record<string, unknown>;
        timeoutSeconds?: number;
    },
): Promise<AutomationRunAnalysis> {
    const { data } = await apiRequest<{ analysis: AutomationRunAnalysis }>(
        `/api/automation/runs/${encodeURIComponent(runId)}/analysis`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: input.model,
                timeout_seconds: input.timeoutSeconds ?? 120,
            }),
        },
    );
    return data.analysis;
}

export async function sampleRunResultTable(
    runId: string,
    tableName: string,
    request: AutomationRunTableSampleRequest,
): Promise<AutomationRunTableSample> {
    const { data } = await apiRequest<AutomationRunTableSample>(
        `/api/automation/runs/${encodeURIComponent(runId)}/tables/${encodeURIComponent(tableName)}/sample`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request),
        },
    );
    return data;
}

export async function downloadRunResultTable(
    runId: string,
    tableName: string,
    format: 'csv' | 'tsv',
): Promise<Blob> {
    const response = await fetchWithIdentity(
        `/api/automation/runs/${encodeURIComponent(runId)}/tables/${encodeURIComponent(tableName)}/download`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delimiter: format === 'tsv' ? '\t' : ',' }),
        },
    );
    await assertDownloadResponseOk(response, 'Run result download failed');
    return response.blob();
}
