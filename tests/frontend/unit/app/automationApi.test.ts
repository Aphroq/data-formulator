import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    apiRequest: vi.fn(),
    assertDownloadResponseOk: vi.fn(),
    fetchWithIdentity: vi.fn(),
}));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: mocks.apiRequest,
    assertDownloadResponseOk: mocks.assertDownloadResponseOk,
}));

vi.mock('../../../../src/app/utils', () => ({
    fetchWithIdentity: mocks.fetchWithIdentity,
}));

import {
    analyzeRunResult,
    cancelAutomationRun,
    createSchedule,
    downloadRunResultTable,
    enqueueManualRun,
    getRunEvents,
    getRunManifest,
    getRunResult,
    getAutomationRun,
    listAutomationRuns,
    listSchedules,
    sampleRunResultTable,
    setScheduleEnabled,
    updateSchedule,
} from '../../../../src/app/automationApi';


beforeEach(() => {
    vi.clearAllMocks();
});


describe('Automation API client', () => {
    it('uses fixed-version schedule endpoints without client timing fields', async () => {
        const schedule = { schedule_id: 'sch_1', version_id: 'rv_1' };
        mocks.apiRequest.mockResolvedValue({ data: { schedule } });

        await createSchedule({
            versionId: 'rv/1',
            name: 'Daily totals',
            cronExpression: '0 9 * * *',
            timezone: 'Asia/Shanghai',
            parameterPolicy: {
                as_of: { source: 'scheduled_date', offset_days: -1 },
            },
        });
        await updateSchedule('sch/1', {
            name: 'Weekday totals',
            cronExpression: '30 8 * * 1-5',
            timezone: 'UTC',
            parameterPolicy: {
                as_of: { source: 'literal', value: '2026-08-20' },
            },
        });
        await setScheduleEnabled('sch/1', false);
        await setScheduleEnabled('sch/1', true);
        await listSchedules();

        expect(mocks.apiRequest.mock.calls.map(call => call[0])).toEqual([
            '/api/automation/schedules',
            '/api/automation/schedules/sch%2F1',
            '/api/automation/schedules/sch%2F1/disable',
            '/api/automation/schedules/sch%2F1/enable',
            '/api/automation/schedules',
        ]);
        expect(JSON.parse(mocks.apiRequest.mock.calls[0][1].body)).toEqual({
            version_id: 'rv/1',
            name: 'Daily totals',
            cron_expression: '0 9 * * *',
            timezone: 'Asia/Shanghai',
            parameter_policy: {
                as_of: { source: 'scheduled_date', offset_days: -1 },
            },
        });
        expect(JSON.parse(mocks.apiRequest.mock.calls[1][1].body)).toEqual({
            name: 'Weekday totals',
            cron_expression: '30 8 * * 1-5',
            timezone: 'UTC',
            parameter_policy: {
                as_of: { source: 'literal', value: '2026-08-20' },
            },
        });
        expect(mocks.apiRequest.mock.calls[0][1].body).not.toContain('next_run_at');
    });

    it('queues typed-parameter runs and reads only scoped audit endpoints', async () => {
        const run = { run_id: 'run_1', status: 'queued' };
        mocks.apiRequest.mockResolvedValue({ data: {
            run,
            runs: [run],
            manifest: { run_id: 'attempt_1' },
            events: [{ sequence: 0 }],
            result: { outputs: [{ kind: 'chart' }] },
            analysis: { summary: 'East leads.', insights: [], caveat: '' },
        } });

        await enqueueManualRun('rv/1', { region: 'east', row_limit: 25 });
        await listAutomationRuns({ limit: 20, status: 'needs_review' });
        await getAutomationRun('run/1');
        await cancelAutomationRun('run/1');
        await getRunManifest('run/1');
        await getRunEvents('run/1');
        await getRunResult('run/1');
        await analyzeRunResult('run/1', {
            model: { endpoint: 'openai', model: 'test-model' },
            timeoutSeconds: 45,
        });
        await sampleRunResultTable('run/1', 'table/1', {
            size: 100,
            offset: 0,
            method: 'head',
            order_by_fields: ['total'],
        });

        expect(mocks.apiRequest.mock.calls.map(call => call[0])).toEqual([
            '/api/automation/runs/manual',
            '/api/automation/runs?limit=20&status=needs_review',
            '/api/automation/runs/run%2F1',
            '/api/automation/runs/run%2F1/cancel',
            '/api/automation/runs/run%2F1/manifest',
            '/api/automation/runs/run%2F1/events',
            '/api/automation/runs/run%2F1/result',
            '/api/automation/runs/run%2F1/analysis',
            '/api/automation/runs/run%2F1/tables/table%2F1/sample',
        ]);
        expect(JSON.parse(mocks.apiRequest.mock.calls[0][1].body)).toEqual({
            version_id: 'rv/1',
            parameters: { region: 'east', row_limit: 25 },
        });
        expect(JSON.parse(mocks.apiRequest.mock.calls[7][1].body)).toEqual({
            model: { endpoint: 'openai', model: 'test-model' },
            timeout_seconds: 45,
        });
        expect(JSON.parse(mocks.apiRequest.mock.calls[8][1].body)).toEqual({
            size: 100,
            offset: 0,
            method: 'head',
            order_by_fields: ['total'],
        });
    });

    it('downloads a complete immutable Run output through the scoped endpoint', async () => {
        const blob = new Blob(['region,total\neast,40']);
        const response = { blob: vi.fn().mockResolvedValue(blob) } as unknown as Response;
        mocks.fetchWithIdentity.mockResolvedValue(response);

        await expect(downloadRunResultTable('run/1', 'table/1', 'tsv')).resolves.toBe(blob);

        expect(mocks.fetchWithIdentity).toHaveBeenCalledWith(
            '/api/automation/runs/run%2F1/tables/table%2F1/download',
            expect.objectContaining({ method: 'POST' }),
        );
        expect(JSON.parse(mocks.fetchWithIdentity.mock.calls[0][1].body)).toEqual({
            delimiter: '\t',
        });
        expect(mocks.assertDownloadResponseOk).toHaveBeenCalledWith(
            response,
            'Run result download failed',
        );
    });
});
