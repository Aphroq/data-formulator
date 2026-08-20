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
    getRunResult: vi.fn(),
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
    getRunResult: mocks.getRunResult,
}));

vi.mock('../../../../src/views/AutomationRunResultView', () => ({
    AutomationRunResultView: () => <div>Saved run output</div>,
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => ({
            'automation.schedules.title': 'Scheduled runs',
            'automation.schedules.description': 'Runs continue after this page closes.',
            'automation.schedules.add': 'Add schedule',
            'automation.schedules.defaultName': 'Daily run',
            'automation.schedules.formCreateTitle': 'New scheduled run',
            'automation.schedules.formEditTitle': 'Edit scheduled run',
            'automation.schedules.name': 'Name',
            'automation.schedules.mode': 'Frequency',
            'automation.schedules.modeDaily': 'Daily',
            'automation.schedules.modeCron': 'Custom Cron',
            'automation.schedules.dailyTime': 'Run time',
            'automation.schedules.cron': 'Cron expression',
            'automation.schedules.timezone': 'Time zone',
            'automation.schedules.runParameters': 'Values for each run',
            'automation.schedules.runParametersHelp': 'Choose fixed or run-relative values.',
            'automation.schedules.valueSource': 'Value source',
            'automation.schedules.fixedValue': 'Fixed value',
            'automation.schedules.relativeValue': 'Follow run day',
            'automation.schedules.value': 'Value',
            'automation.schedules.relativeDay': 'Run-relative day',
            'automation.schedules.previousDay': 'Previous day',
            'automation.schedules.runDay': 'Run day',
            'automation.schedules.nextDay': 'Next day',
            'automation.schedules.moreSettings': 'More settings',
            'automation.schedules.fewerSettings': 'Hide settings',
            'automation.schedules.dailySummary': `Every day at ${values?.time}`,
            'automation.schedules.customSummary': 'Custom timing',
            'automation.schedules.create': 'Save',
            'automation.schedules.save': 'Save',
            'automation.schedules.edit': 'Edit',
            'automation.schedules.cancelEdit': 'Cancel',
            'automation.schedules.enable': 'Resume',
            'automation.schedules.disable': 'Pause',
            'automation.schedules.enabled': 'Active',
            'automation.schedules.disabled': 'Paused',
            'automation.schedules.nextRun': `Next: ${values?.date}`,
            'automation.schedules.empty': 'No scheduled runs yet.',
            'automation.schedules.loadFailed': 'Schedules could not be loaded.',
            'automation.schedules.actionFailed': 'Schedule action failed.',
            'automation.runs.title': 'Run history',
            'automation.runs.description': 'Manual and scheduled results.',
            'automation.runs.refresh': 'Refresh',
            'automation.runs.filter': 'Status',
            'automation.runs.all': 'All',
            'automation.runs.empty': 'No runs yet.',
            'automation.runs.loadFailed': 'Runs could not be loaded.',
            'automation.runs.cancel': 'Cancel',
            'automation.runs.inspect': 'View details',
            'automation.runs.viewResult': 'View result',
            'automation.runs.reviewRecipe': 'Update recipe',
            'automation.runs.needsReview': 'The source data structure changed. Update the recipe.',
            'automation.runs.failedHelp': 'This run failed. Open details for more information.',
            'automation.runs.attempts': `${values?.count} attempts`,
            'automation.runs.trigger.manual': 'Manual run',
            'automation.runs.trigger.scheduled': 'Scheduled run',
            'automation.runs.status.queued': 'Waiting',
            'automation.runs.status.running': 'Running',
            'automation.runs.status.succeeded': 'Completed',
            'automation.runs.status.failed': 'Failed',
            'automation.runs.status.needs_review': 'Needs review',
            'automation.runs.status.cancelled': 'Cancelled',
            'automation.runs.artifactTitle': 'Run details',
            'automation.runs.resultTitle': `${values?.name} — Analysis report`,
            'automation.runs.manifest': 'Manifest',
            'automation.runs.events': 'Run steps',
            'automation.runs.noEvents': 'No events.',
            'automation.runs.technicalInfo': 'Technical information',
            'automation.runs.runIdentifier': 'Run ID',
            'automation.runs.versionIdentifier': 'Published version',
            'automation.runs.outputFiles': 'Output files',
            'automation.runs.eventStatus.needs_review': 'Needs review',
            'automation.runs.close': 'Close',
            'automation.runs.artifactFailed': 'Run details could not be loaded.',
            'automation.runs.usedParameters': 'Values used by this run',
            'automation.runs.parameterSummary': `Values: ${values?.values}`,
            'recipes.invalidParameter': `Enter a valid value for ${values?.name}.`,
            'recipes.true': 'True',
            'recipes.false': 'False',
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
    parameter_policy: {},
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
    parameters: { region: 'west' },
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

const succeededRun = {
    ...needsReviewRun,
    run_id: `run_${'5'.repeat(32)}`,
    trigger: 'manual' as const,
    schedule_id: null,
    status: 'succeeded' as const,
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
    mocks.getRunResult.mockResolvedValue({
        manifest: {
            run_id: succeededRun.artifact.run_id,
            recipe_id: recipe.recipe_id,
            version_id: schedule.version_id,
            kind: 'automation',
            status: 'succeeded',
            binding_hash: 'sha256:b',
            error: null,
            files: { 'workspace/regional_totals.parquet': { hash: 'sha256:d', size: 20 } },
        },
        events: [],
        report: {
            title: 'Regional totals',
            description: 'Compare the saved totals by region.',
            parameters: [{
                id: 'region',
                name: 'Region',
                description: 'Region included in this run.',
                type: 'string',
            }],
            steps: [
                { step_id: 'step_1', kind: 'load', title: 'Orders' },
                { step_id: 'step_2', kind: 'transform', title: 'regional_totals' },
                { step_id: 'step_3', kind: 'chart', title: 'Regional totals' },
            ],
        },
        outputs: [{
            step_id: 'step_3',
            kind: 'chart',
            title: 'Regional totals',
            subtitle: '',
            display_instruction: 'Compare totals by region',
            chart: null,
            table: {
                name: 'regional_totals',
                row_count: 2,
                column_count: 2,
                columns: [
                    { name: 'region', type: 'string' },
                    { name: 'total', type: 'integer' },
                ],
                rows: [{ region: 'east', total: 40 }],
                rows_truncated: true,
                columns_truncated: false,
            },
        }],
    });
});


describe('Schedule panel', () => {
    it('creates a daily schedule by converting local controls to canonical Cron', async () => {
        render(<SchedulePanel versionId={schedule.version_id} versionStatus="published" parameters={[]} />);

        expect(await screen.findByText('No scheduled runs yet.')).toBeInTheDocument();
        expect(screen.queryByLabelText(/Name/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Add schedule' }));
        fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Morning totals' } });
        fireEvent.change(screen.getByLabelText('Run time'), { target: { value: '08:35' } });
        fireEvent.click(screen.getByRole('button', { name: 'More settings' }));
        fireEvent.change(screen.getByLabelText(/Time zone/), { target: { value: 'Asia/Shanghai' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));

        await waitFor(() => expect(mocks.createSchedule).toHaveBeenCalledWith({
            versionId: schedule.version_id,
            name: 'Morning totals',
            cronExpression: '35 8 * * *',
            timezone: 'Asia/Shanghai',
            parameterPolicy: {},
        }));
    });

    it('edits and disables an existing fixed-version schedule', async () => {
        mocks.listSchedules.mockResolvedValue([schedule]);
        render(<SchedulePanel versionId={schedule.version_id} versionStatus="published" parameters={[]} />);

        expect(await screen.findByText('Daily totals')).toBeInTheDocument();
        expect(screen.getByText(/Every day at 09:00/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
        fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Morning totals' } });
        fireEvent.change(screen.getByLabelText('Run time'), { target: { value: '08:30' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));

        await waitFor(() => expect(mocks.updateSchedule).toHaveBeenCalledWith(
            schedule.schedule_id,
            {
                name: 'Morning totals',
                cronExpression: '30 8 * * *',
                timezone: 'UTC',
                parameterPolicy: {},
            },
        ));
        fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
        await waitFor(() => expect(mocks.setScheduleEnabled).toHaveBeenCalledWith(
            schedule.schedule_id,
            false,
        ));
        expect(screen.queryByText(/Next:/)).not.toBeInTheDocument();
    });

    it('configures date values relative to the planned run and keeps typed literals', async () => {
        render(
            <SchedulePanel
                versionId={schedule.version_id}
                versionStatus="published"
                parameters={[
                    {
                        id: 'as_of',
                        name: 'As of date',
                        type: 'date',
                        required: true,
                        default: '2026-08-20',
                    },
                    {
                        id: 'row_limit',
                        name: 'Row limit',
                        type: 'integer',
                        required: true,
                        default: 100,
                    },
                ]}
            />,
        );

        expect(await screen.findByText('No scheduled runs yet.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Add schedule' }));
        fireEvent.change(screen.getByDisplayValue('100'), { target: { value: '25' } });
        fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Value source' }));
        fireEvent.click(screen.getByRole('option', { name: 'Follow run day' }));
        fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Run-relative day' }));
        fireEvent.click(screen.getByRole('option', { name: 'Previous day' }));
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));

        await waitFor(() => expect(mocks.createSchedule).toHaveBeenCalledWith(
            expect.objectContaining({
                parameterPolicy: {
                    as_of: { source: 'scheduled_date', offset_days: -1 },
                    row_limit: { source: 'literal', value: 25 },
                },
            }),
        ));
    });
});


describe('Run history', () => {
    it('opens a successful Run as its saved result instead of replaying a Workflow', async () => {
        mocks.listAutomationRuns.mockResolvedValue([succeededRun]);
        render(
            <RunsInbox
                workspaceId="ws-1"
                recipes={[recipe]}
                refreshToken={0}
                onSelectVersion={vi.fn()}
            />,
        );

        const inbox = await screen.findByRole('region', { name: 'Run history' });
        fireEvent.click(within(inbox).getByRole('button', { name: 'View result' }));

        const dialog = await screen.findByRole('dialog', { name: 'Regional totals — Analysis report' });
        expect(mocks.getRunResult).toHaveBeenCalledWith(succeededRun.run_id);
        expect(mocks.getRunManifest).not.toHaveBeenCalled();
        expect(mocks.getRunEvents).not.toHaveBeenCalled();
        expect(within(dialog).getByText('Saved run output')).toBeInTheDocument();
        expect(within(dialog).queryByText('Values used by this run')).not.toBeInTheDocument();
        expect(within(dialog).getByText('Region: west')).toBeInTheDocument();
    });

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

        const inbox = await screen.findByRole('region', { name: 'Run history' });
        expect(within(inbox).getByText('The source data structure changed. Update the recipe.')).toBeInTheDocument();
        expect(within(inbox).queryByText('SCHEMA_DRIFT')).not.toBeInTheDocument();
        expect(within(inbox).queryByText(needsReviewRun.run_id)).not.toBeInTheDocument();
        fireEvent.click(within(inbox).getByRole('button', { name: 'Update recipe' }));
        expect(onSelectVersion).toHaveBeenCalledWith(schedule.version_id);

        fireEvent.click(within(inbox).getByRole('button', { name: 'View details' }));
        const dialog = await screen.findByRole('dialog', { name: 'Run details' });
        expect(mocks.getRunManifest).toHaveBeenCalledWith(needsReviewRun.run_id);
        expect(mocks.getRunEvents).toHaveBeenCalledWith(needsReviewRun.run_id);
        expect(within(dialog).getByText('Load data')).toBeInTheDocument();
        const technicalInfo = within(dialog).getByRole('button', { name: 'Technical information' });
        expect(technicalInfo).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(technicalInfo);
        expect(within(dialog).getByText('events.jsonl')).toBeInTheDocument();
    });

    it('cancels queued work and can filter the persistent inbox', async () => {
        render(<RunsInbox workspaceId="ws-1" recipes={[recipe]} refreshToken={0} onSelectVersion={vi.fn()} />);

        const inbox = await screen.findByRole('region', { name: 'Run history' });
        fireEvent.click(within(inbox).getByRole('button', { name: 'Cancel' }));
        await waitFor(() => expect(mocks.cancelAutomationRun).toHaveBeenCalledWith(queuedRun.run_id));

        fireEvent.mouseDown(within(inbox).getByRole('combobox', { name: 'Status' }));
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
        expect(screen.queryByText('Regional totals')).not.toBeInTheDocument();
    });
});
