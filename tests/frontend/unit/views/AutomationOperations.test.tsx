import React from 'react';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    listSchedules: vi.fn(),
    createSchedule: vi.fn(),
    updateSchedule: vi.fn(),
    setScheduleEnabled: vi.fn(),
    listAutomationRuns: vi.fn(),
    cancelAutomationRun: vi.fn(),
    getRunManifest: vi.fn(),
    getRunEvents: vi.fn(),
}));

vi.mock('../../../../src/app/automationApi', () => ({
    listSchedules: mocks.listSchedules,
    createSchedule: mocks.createSchedule,
    updateSchedule: mocks.updateSchedule,
    setScheduleEnabled: mocks.setScheduleEnabled,
    listAutomationRuns: mocks.listAutomationRuns,
    cancelAutomationRun: mocks.cancelAutomationRun,
    getRunManifest: mocks.getRunManifest,
    getRunEvents: mocks.getRunEvents,
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => ({
            'automation.schedules.title': 'Schedules',
            'automation.schedules.description': 'Schedules stay pinned to this version.',
            'automation.schedules.name': 'Schedule name',
            'automation.schedules.mode': 'Schedule type',
            'automation.schedules.modeDaily': 'Daily',
            'automation.schedules.modeCron': 'Cron',
            'automation.schedules.dailyTime': 'Daily time',
            'automation.schedules.cron': 'Cron expression',
            'automation.schedules.timezone': 'Timezone',
            'automation.schedules.create': 'Create schedule',
            'automation.schedules.save': 'Save schedule',
            'automation.schedules.edit': 'Edit schedule',
            'automation.schedules.cancelEdit': 'Cancel editing',
            'automation.schedules.enable': 'Enable schedule',
            'automation.schedules.disable': 'Disable schedule',
            'automation.schedules.enabled': 'Enabled',
            'automation.schedules.disabled': 'Disabled',
            'automation.schedules.nextRun': `Next run ${values?.date}`,
            'automation.schedules.empty': 'No schedule for this version.',
            'automation.schedules.loadFailed': 'Schedules could not be loaded.',
            'automation.schedules.actionFailed': 'Schedule action failed.',
            'automation.runs.title': 'Runs Inbox',
            'automation.runs.description': 'Persistent manual and scheduled runs.',
            'automation.runs.refresh': 'Refresh runs',
            'automation.runs.filter': 'Run status',
            'automation.runs.all': 'All runs',
            'automation.runs.empty': 'No runs yet.',
            'automation.runs.loadFailed': 'Runs could not be loaded.',
            'automation.runs.cancel': 'Cancel run',
            'automation.runs.inspect': 'Inspect run',
            'automation.runs.reviewRecipe': 'Review recipe',
            'automation.runs.needsReview': 'Schema drift needs review.',
            'automation.runs.attempts': `${values?.count} attempts`,
            'automation.runs.trigger.manual': 'Manual',
            'automation.runs.trigger.scheduled': 'Scheduled',
            'automation.runs.status.queued': 'Queued',
            'automation.runs.status.running': 'Running',
            'automation.runs.status.succeeded': 'Succeeded',
            'automation.runs.status.failed': 'Failed',
            'automation.runs.status.needs_review': 'Needs review',
            'automation.runs.status.cancelled': 'Cancelled',
            'automation.runs.artifactTitle': 'Run audit',
            'automation.runs.manifest': 'Manifest',
            'automation.runs.events': 'Events',
            'automation.runs.noEvents': 'No events.',
            'automation.runs.close': 'Close',
            'automation.runs.artifactFailed': 'Run audit could not be loaded.',
            'recipes.stepKind.load': 'Load data',
        }[key] ?? key),
    }),
}));

import { RunsInbox, SchedulePanel } from '../../../../src/views/AutomationOperations';


const schedule = {
    schedule_id: `sch_${'1'.repeat(32)}`,
    version_id: `rv_${'1'.repeat(64)}`,
    name: 'Daily totals',
    cron_expression: '0 9 * * *',
    timezone: 'UTC',
    enabled: true,
    next_run_at: '2026-08-21T09:00:00Z',
    created_at: '2026-08-20T00:00:00Z',
    updated_at: '2026-08-20T00:00:00Z',
};

const recipe = {
    recipe_id: 'rcp_1',
    name: 'Regional totals',
    description: '',
    created_by: 'user:alice',
    created_at: '2026-08-20T00:00:00Z',
    updated_at: '2026-08-20T00:00:00Z',
    versions: [{
        version_id: schedule.version_id,
        recipe_id: 'rcp_1',
        recipe_hash: 'sha256:a',
        status: 'published' as const,
        created_at: '2026-08-20T00:00:00Z',
        validated_at: '2026-08-20T00:00:00Z',
        published_at: '2026-08-20T00:00:00Z',
        archived_at: null,
        validation_run_id: 'run_validation',
    }],
};

const needsReviewRun = {
    run_id: `run_${'2'.repeat(32)}`,
    version_id: schedule.version_id,
    schedule_id: schedule.schedule_id,
    trigger: 'scheduled' as const,
    scheduled_for: '2026-08-21T09:00:00Z',
    status: 'needs_review' as const,
    attempt_count: 1,
    available_at: '2026-08-21T09:00:00Z',
    cancel_requested_at: null,
    artifact: {
        run_id: `run_${'3'.repeat(32)}`,
        path: `artifacts/recipe-runs/run_${'3'.repeat(32)}`,
        manifest_hash: 'sha256:a',
        binding_hash: 'sha256:b',
    },
    error: { code: 'SCHEMA_DRIFT', message: 'Schema changed.' },
    created_at: '2026-08-21T09:00:00Z',
    updated_at: '2026-08-21T09:00:05Z',
};

const queuedRun = {
    ...needsReviewRun,
    run_id: `run_${'4'.repeat(32)}`,
    schedule_id: null,
    trigger: 'manual' as const,
    status: 'queued' as const,
    attempt_count: 0,
    artifact: null,
    error: null,
};

function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>(next => {
        resolve = next;
    });
    return { promise, resolve };
}


beforeEach(() => {
    vi.clearAllMocks();
    mocks.listSchedules.mockResolvedValue([]);
    mocks.createSchedule.mockResolvedValue(schedule);
    mocks.updateSchedule.mockResolvedValue(schedule);
    mocks.setScheduleEnabled.mockResolvedValue({ ...schedule, enabled: false });
    mocks.listAutomationRuns.mockResolvedValue([needsReviewRun, queuedRun]);
    mocks.cancelAutomationRun.mockResolvedValue({ ...queuedRun, status: 'cancelled' });
    mocks.getRunManifest.mockResolvedValue({
        run_id: needsReviewRun.artifact.run_id,
        recipe_id: recipe.recipe_id,
        version_id: schedule.version_id,
        kind: 'automation',
        status: 'needs_review',
        binding_hash: 'sha256:b',
        error: { code: 'schema_drift', exception_type: 'RecipeSchemaDriftError', message: 'Schema changed.' },
        files: { 'events.jsonl': { hash: 'sha256:c', size: 10 } },
    });
    mocks.getRunEvents.mockResolvedValue([{
        sequence: 0,
        step_id: 'step_1',
        kind: 'load',
        status: 'needs_review',
        recorded_at: '2026-08-21T09:00:05Z',
        details: { duration_ms: 12 },
    }]);
});


describe('Schedule panel', () => {
    it('creates a daily schedule by converting local controls to canonical Cron', async () => {
        render(<SchedulePanel versionId={schedule.version_id} versionStatus="published" />);

        expect(await screen.findByText('No schedule for this version.')).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText(/Schedule name/), { target: { value: 'Morning totals' } });
        fireEvent.change(screen.getByLabelText('Daily time'), { target: { value: '08:35' } });
        fireEvent.change(screen.getByLabelText(/Timezone/), { target: { value: 'Asia/Shanghai' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create schedule' }));

        await waitFor(() => expect(mocks.createSchedule).toHaveBeenCalledWith({
            versionId: schedule.version_id,
            name: 'Morning totals',
            cronExpression: '35 8 * * *',
            timezone: 'Asia/Shanghai',
        }));
    });

    it('edits and disables an existing fixed-version schedule', async () => {
        mocks.listSchedules.mockResolvedValue([schedule]);
        render(<SchedulePanel versionId={schedule.version_id} versionStatus="published" />);

        expect(await screen.findByText('Daily totals')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Edit schedule' }));
        fireEvent.change(screen.getByLabelText(/Schedule name/), { target: { value: 'Weekday totals' } });
        fireEvent.change(screen.getByLabelText(/Cron expression/), { target: { value: '30 8 * * 1-5' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }));

        await waitFor(() => expect(mocks.updateSchedule).toHaveBeenCalledWith(
            schedule.schedule_id,
            {
                name: 'Weekday totals',
                cronExpression: '30 8 * * 1-5',
                timezone: 'UTC',
            },
        ));
        fireEvent.click(screen.getByRole('button', { name: 'Disable schedule' }));
        await waitFor(() => expect(mocks.setScheduleEnabled).toHaveBeenCalledWith(
            schedule.schedule_id,
            false,
        ));
    });
});


describe('Runs Inbox', () => {
    it('surfaces Needs Review evidence, opens verified audit data, and returns to the Recipe', async () => {
        const onSelectVersion = vi.fn();
        render(
            <RunsInbox
                workspaceId="ws-1"
                recipes={[recipe]}
                refreshToken={0}
                onSelectVersion={onSelectVersion}
            />,
        );

        const inbox = await screen.findByRole('region', { name: 'Runs Inbox' });
        expect(within(inbox).getByText('Schema drift needs review.')).toBeInTheDocument();
        expect(within(inbox).getByText('SCHEMA_DRIFT')).toBeInTheDocument();
        fireEvent.click(within(inbox).getByRole('button', { name: 'Review recipe' }));
        expect(onSelectVersion).toHaveBeenCalledWith(schedule.version_id);

        fireEvent.click(within(inbox).getByRole('button', { name: 'Inspect run' }));
        const dialog = await screen.findByRole('dialog', { name: 'Run audit' });
        expect(mocks.getRunManifest).toHaveBeenCalledWith(needsReviewRun.run_id);
        expect(mocks.getRunEvents).toHaveBeenCalledWith(needsReviewRun.run_id);
        expect(within(dialog).getByText('events.jsonl')).toBeInTheDocument();
        expect(within(dialog).getByText('Load data')).toBeInTheDocument();
    });

    it('cancels queued work and can filter the persistent inbox', async () => {
        render(<RunsInbox workspaceId="ws-1" recipes={[recipe]} refreshToken={0} onSelectVersion={vi.fn()} />);

        const inbox = await screen.findByRole('region', { name: 'Runs Inbox' });
        fireEvent.click(within(inbox).getByRole('button', { name: 'Cancel run' }));
        await waitFor(() => expect(mocks.cancelAutomationRun).toHaveBeenCalledWith(queuedRun.run_id));

        fireEvent.mouseDown(within(inbox).getByRole('combobox', { name: 'Run status' }));
        fireEvent.click(screen.getByRole('option', { name: 'Failed' }));
        await waitFor(() => expect(mocks.listAutomationRuns).toHaveBeenLastCalledWith({
            limit: 50,
            status: 'failed',
        }));
    });

    it('does not apply a stale Run list after the active Workspace changes', async () => {
        const first = deferred<typeof needsReviewRun[]>();
        mocks.listAutomationRuns
            .mockReturnValueOnce(first.promise)
            .mockResolvedValueOnce([]);
        const { rerender } = render(
            <RunsInbox workspaceId="ws-1" recipes={[recipe]} refreshToken={0} onSelectVersion={vi.fn()} />,
        );

        rerender(
            <RunsInbox workspaceId="ws-2" recipes={[]} refreshToken={0} onSelectVersion={vi.fn()} />,
        );
        expect(await screen.findByText('No runs yet.')).toBeInTheDocument();

        await act(async () => first.resolve([needsReviewRun]));
        expect(screen.queryByText('SCHEMA_DRIFT')).not.toBeInTheDocument();
    });
});
