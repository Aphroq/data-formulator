import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: mocks.apiRequest,
}));

import {
    cancelAutomationRun,
    createSchedule,
    enqueueManualRun,
    getRunEvents,
    getRunManifest,
    getAutomationRun,
    listAutomationRuns,
    listSchedules,
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
        });
        await updateSchedule('sch/1', {
            name: 'Weekday totals',
            cronExpression: '30 8 * * 1-5',
            timezone: 'UTC',
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
        });
        expect(JSON.parse(mocks.apiRequest.mock.calls[1][1].body)).toEqual({
            name: 'Weekday totals',
            cron_expression: '30 8 * * 1-5',
            timezone: 'UTC',
        });
        expect(mocks.apiRequest.mock.calls[0][1].body).not.toContain('next_run_at');
    });

    it('queues default-binding runs and reads only scoped audit endpoints', async () => {
        const run = { run_id: 'run_1', status: 'queued' };
        mocks.apiRequest.mockResolvedValue({ data: {
            run,
            runs: [run],
            manifest: { run_id: 'attempt_1' },
            events: [{ sequence: 0 }],
        } });

        await enqueueManualRun('rv/1');
        await listAutomationRuns({ limit: 20, status: 'needs_review' });
        await getAutomationRun('run/1');
        await cancelAutomationRun('run/1');
        await getRunManifest('run/1');
        await getRunEvents('run/1');

        expect(mocks.apiRequest.mock.calls.map(call => call[0])).toEqual([
            '/api/automation/runs/manual',
            '/api/automation/runs?limit=20&status=needs_review',
            '/api/automation/runs/run%2F1',
            '/api/automation/runs/run%2F1/cancel',
            '/api/automation/runs/run%2F1/manifest',
            '/api/automation/runs/run%2F1/events',
        ]);
        expect(JSON.parse(mocks.apiRequest.mock.calls[0][1].body)).toEqual({
            version_id: 'rv/1',
        });
        expect(mocks.apiRequest.mock.calls[0][1].body).not.toContain('parameters');
    });
});
