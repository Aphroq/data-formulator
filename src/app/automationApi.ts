// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { apiRequest } from './apiClient';


export type AutomationRunStatus =
    | 'queued'
    | 'running'
    | 'succeeded'
    | 'failed'
    | 'needs_review'
    | 'cancelled';

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

export async function enqueueManualRun(versionId: string): Promise<AutomationRun> {
    const { data } = await apiRequest<{ run: AutomationRun }>(
        '/api/automation/runs/manual',
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version_id: versionId }),
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
