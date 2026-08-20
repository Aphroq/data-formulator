import React from 'react';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    listRecipes: vi.fn(),
    getRecipeVersion: vi.fn(),
    dryRunRecipe: vi.fn(),
    publishRecipe: vi.fn(),
    enqueueManualRun: vi.fn(),
    archiveRecipe: vi.fn(),
}));

const state: any = {
    activeWorkspace: { id: 'ws-1', displayName: 'Regional analysis' },
    serverConfig: { AUTOMATION_ENABLED: true },
    models: [],
    globalModels: [],
    selectedModelId: null,
    config: { formulateTimeoutSeconds: 180 },
};

vi.mock('react-redux', () => ({
    useSelector: (selector: (value: any) => unknown) => selector(state),
}));

vi.mock('../../../../src/app/recipeApi', () => ({
    listRecipes: mocks.listRecipes,
    getRecipeVersion: mocks.getRecipeVersion,
    dryRunRecipe: mocks.dryRunRecipe,
    publishRecipe: mocks.publishRecipe,
    archiveRecipe: mocks.archiveRecipe,
}));

vi.mock('../../../../src/app/automationApi', () => ({
    enqueueManualRun: mocks.enqueueManualRun,
}));

vi.mock('../../../../src/views/AutomationOperations', () => ({
    SchedulePanel: () => <section aria-label="Schedule settings">Schedule settings</section>,
    RunsInbox: () => <section aria-label="Run history">Run history</section>,
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => ({
            'automation.title': 'Automation',
            'automation.subtitle': 'Run recipes on a schedule',
            'automation.openApp': 'Open App',
            'automation.unavailable': 'Automation is unavailable',
            'automation.recipes': 'Recipes',
            'automation.versionsCount': `${values?.count} versions`,
            'automation.updated': `Updated ${values?.date}`,
            'automation.versionPicker': 'Version',
            'automation.recipeDetails': 'Recipe details',
            'automation.recipeDetailsSummary': `${values?.inputCount} inputs · ${values?.stepCount} steps`,
            'automation.inputSchema': 'Data structure',
            'automation.artifactId': 'Artifact',
            'automation.runResult.title': 'Validation result',
            'automation.runResult.status.succeeded': 'Passed',
            'automation.runResult.status.failed': 'Not passed',
            'automation.runResult.status.needs_review': 'Needs review',
            'automation.runResult.kind.dry_run': 'Recipe validation',
            'automation.runResult.kind.manual': 'Manual run result',
            'automation.runResult.runId': 'Run ID',
            'automation.runResult.summary': `${values?.count} steps · ${values?.duration} ms`,
            'automation.runResult.steps': 'Run steps',
            'automation.runResult.noSteps': 'No step result',
            'automation.runResult.needsReview': 'The source data changed.',
            'automation.runResult.failedHelp': 'Validation did not pass.',
            'automation.runResult.technicalInfo': 'Technical information',
            'automation.runResult.finalOutput': 'Result',
            'automation.runResult.duration': `${values?.duration} ms`,
            'automation.runResult.outputPath': 'Saved output',
            'automation.runResult.contentHash': 'content',
            'automation.runResult.schemaHash': 'schema',
            'automation.runs.queuedNotice': 'The run is queued. Follow its progress below.',
            'automation.runSettings': 'Run settings',
            'automation.manualParameterHelp': 'Choose values for this one-off run.',
            'automation.validationParameterHelp': 'Choose values for validation.',
            'recipes.status.draft': 'Draft',
            'recipes.status.published': 'Published',
            'recipes.versionNumber': `Version ${values?.number}`,
            'recipes.hash': 'Recipe hash',
            'recipes.parameters': 'Parameters',
            'recipes.noParameters': 'No parameters',
            'recipes.inputs': 'Inputs',
            'recipes.inputMode.refreshable': 'Refreshable',
            'recipes.steps': 'Steps',
            'recipes.stepKind.load': 'Load data',
            'recipes.dryRun': 'Validate recipe',
            'recipes.dryRunSucceeded': 'Validation passed',
            'recipes.runNow': 'Run once',
            'recipes.archive': 'Archive version',
            'recipes.runSucceeded': `Run ${values?.runId} succeeded.`,
            'recipes.runFailed': 'Run failed',
            'recipes.refreshAfterActionFailed': 'Action completed, but Automation could not be refreshed.',
            'recipes.invalidParameter': `Enter a valid value for ${values?.name}.`,
            'recipes.true': 'True',
            'recipes.false': 'False',
        }[key] ?? key),
    }),
}));

import { Automation } from '../../../../src/views/Recipes';


const version = {
    version_id: 'rv_2',
    recipe_id: 'rcp_1',
    recipe_hash: `sha256:${'a'.repeat(64)}`,
    status: 'draft',
    created_at: '2026-08-18T00:00:00Z',
    validated_at: null,
    published_at: null,
    archived_at: null,
    validation_run_id: null,
};

const publishedVersion = {
    ...version,
    version_id: 'rv_1',
    status: 'published',
    published_at: '2026-08-18T00:05:00Z',
};

const recipe = {
    recipe_id: 'rcp_1',
    name: 'Regional totals',
    description: 'Refresh and chart regional totals.',
    created_by: 'user:alice',
    created_at: '2026-08-18T00:00:00Z',
    updated_at: '2026-08-18T00:00:00Z',
    versions: [version, publishedVersion],
};

const detail = {
    recipe: { ...recipe, versions: undefined },
    version,
    spec: {
        recipe_id: 'rcp_1',
        version_id: 'rv_2',
        name: 'Regional totals',
        description: recipe.description,
        parameters: [],
        inputs: [{
            id: 'input_1',
            step_id: 'step_1',
            mode: 'refreshable',
            source_id: 'warehouse',
            content_hash: `sha256:${'b'.repeat(64)}`,
            expected_schema: `sha256:${'c'.repeat(64)}`,
        }],
        steps: [{
            id: 'step_1',
            kind: 'load',
            artifact_id: `art_${'d'.repeat(64)}`,
            dependencies: [],
            content_hash: `sha256:${'b'.repeat(64)}`,
            expected_schema: `sha256:${'c'.repeat(64)}`,
            step_hash: `sha256:${'e'.repeat(64)}`,
        }],
        final_outputs: [{
            artifact_id: `art_${'d'.repeat(64)}`,
            step_id: 'step_1',
            kind: 'table',
        }],
    },
    workflow_markdown: '# Regional totals',
};

const publishedDetail = {
    ...detail,
    version: publishedVersion,
    spec: { ...detail.spec, version_id: 'rv_1' },
};

const parameterizedPublishedDetail = {
    ...publishedDetail,
    spec: {
        ...publishedDetail.spec,
        parameters: [
            {
                id: 'region',
                name: 'Region',
                type: 'string' as const,
                required: true,
                default: 'west',
            },
            {
                id: 'row_limit',
                name: 'Row limit',
                type: 'integer' as const,
                required: true,
                default: 100,
            },
        ],
    },
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
    state.activeWorkspace = { id: 'ws-1', displayName: 'Regional analysis' };
    state.serverConfig.AUTOMATION_ENABLED = true;
    mocks.listRecipes.mockResolvedValue([recipe]);
    mocks.getRecipeVersion.mockImplementation((versionId: string) => Promise.resolve(
        versionId === 'rv_1' ? publishedDetail : detail,
    ));
    mocks.dryRunRecipe.mockResolvedValue({
        result: {
            status: 'succeeded',
            run: { run_id: 'run_1', kind: 'dry_run', status: 'succeeded', manifest_hash: 'sha256:a' },
            steps: [{
                step_id: 'step_1',
                kind: 'load',
                content_hash: `sha256:${'b'.repeat(64)}`,
                schema_hash: `sha256:${'c'.repeat(64)}`,
                output_path: 'workspace/data/orders.parquet',
                duration_ms: 12,
            }],
            error: null,
        },
        version: { ...version, status: 'validated' },
    });
    mocks.enqueueManualRun.mockResolvedValue({
        run_id: 'run_queued',
        version_id: 'rv_1',
        status: 'queued',
    });
});


describe('Automation page', () => {
    it('groups versions into one recipe and starts validation through the API', async () => {
        render(<MemoryRouter initialEntries={['/automation']}><Automation /></MemoryRouter>);

        expect(await screen.findByRole('heading', { name: 'Regional totals' })).toBeInTheDocument();
        expect(within(screen.getByRole('list', { name: 'Recipes' })).getAllByRole('button')).toHaveLength(1);
        expect(screen.getByText('2 versions')).toBeInTheDocument();
        expect(screen.getByText('warehouse')).toBeInTheDocument();
        expect(screen.getByText('Load data')).toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'Open App' })).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Validate recipe' }));

        await waitFor(() => {
            expect(mocks.dryRunRecipe).toHaveBeenCalledWith('rv_2', {});
        });
        expect(await screen.findByText('Validation passed')).toBeInTheDocument();
        const resultPanel = screen.getByRole('region', { name: 'Validation result' });
        expect(within(resultPanel).getByText('Passed')).toBeInTheDocument();
        expect(within(resultPanel).getByText('Result')).toBeInTheDocument();
        const technicalInfo = within(resultPanel).getByRole('button', { name: 'Technical information' });
        expect(technicalInfo).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(technicalInfo);
        expect(within(resultPanel).getByText(/run_1/)).toBeInTheDocument();
        expect(within(resultPanel).getByText(/workspace\/data\/orders.parquet/)).toBeInTheDocument();
    });

    it('persists a default-binding manual run in the Runs Inbox', async () => {
        render(<MemoryRouter initialEntries={['/automation?version=rv_1']}><Automation /></MemoryRouter>);

        expect(await screen.findByText('Published')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Run once' }));

        await waitFor(() => expect(mocks.enqueueManualRun).toHaveBeenCalledWith('rv_1', {}));
        expect(await screen.findByText('The run is queued. Follow its progress below.')).toBeInTheDocument();
        expect(screen.getByRole('region', { name: 'Run history' })).toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Validation result' })).not.toBeInTheDocument();
    });

    it('sends the one-off values the user selected and leaves schedule values independent', async () => {
        mocks.getRecipeVersion.mockResolvedValue(parameterizedPublishedDetail);
        render(<MemoryRouter initialEntries={['/automation?version=rv_1']}><Automation /></MemoryRouter>);

        expect(await screen.findByText('Run settings')).toBeInTheDocument();
        fireEvent.change(screen.getByDisplayValue('west'), { target: { value: 'east' } });
        fireEvent.change(screen.getByDisplayValue('100'), { target: { value: '25' } });
        fireEvent.click(screen.getByRole('button', { name: 'Run once' }));

        await waitFor(() => expect(mocks.enqueueManualRun).toHaveBeenCalledWith(
            'rv_1',
            { region: 'east', row_limit: 25 },
        ));
    });

    it('switches versions inside the selected recipe', async () => {
        render(<MemoryRouter initialEntries={['/automation']}><Automation /></MemoryRouter>);

        await screen.findByRole('heading', { name: 'Regional totals' });
        fireEvent.change(screen.getByLabelText('Version'), { target: { value: 'rv_1' } });

        await waitFor(() => {
            expect(mocks.getRecipeVersion).toHaveBeenCalledWith('rv_1');
        });
        expect(await screen.findByText('Published')).toBeInTheDocument();
    });

    it('shows immutable version metadata instead of the mutable catalog name', async () => {
        mocks.getRecipeVersion.mockResolvedValue({
            ...detail,
            recipe: { ...detail.recipe, name: 'Renamed catalog entry' },
            spec: { ...detail.spec, name: 'Immutable version name' },
        });

        render(<MemoryRouter initialEntries={['/automation']}><Automation /></MemoryRouter>);

        expect(await screen.findByRole('heading', { name: 'Immutable version name' })).toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: 'Renamed catalog entry' })).not.toBeInTheDocument();
    });

    it('ignores a stale detail response after another recipe is selected', async () => {
        const firstDetail = deferred<typeof detail>();
        const secondVersion = {
            ...version,
            version_id: 'rv_second',
            recipe_id: 'rcp_2',
        };
        const secondRecipe = {
            ...recipe,
            recipe_id: 'rcp_2',
            name: 'Second automation',
            versions: [secondVersion],
        };
        const secondDetail = {
            ...detail,
            recipe: { ...detail.recipe, recipe_id: 'rcp_2', name: 'Second automation' },
            version: secondVersion,
            spec: {
                ...detail.spec,
                recipe_id: 'rcp_2',
                version_id: 'rv_second',
                name: 'Second immutable version',
            },
        };
        mocks.listRecipes.mockResolvedValue([recipe, secondRecipe]);
        mocks.getRecipeVersion.mockImplementation((versionId: string) => (
            versionId === 'rv_2' ? firstDetail.promise : Promise.resolve(secondDetail)
        ));

        render(<MemoryRouter initialEntries={['/automation?version=rv_2']}><Automation /></MemoryRouter>);

        fireEvent.click(await screen.findByText('Second automation'));
        expect(await screen.findByRole('heading', { name: 'Second immutable version' })).toBeInTheDocument();

        await act(async () => firstDetail.resolve(detail));
        expect(screen.getByRole('heading', { name: 'Second immutable version' })).toBeInTheDocument();
    });

    it('keeps a queued run notice when the follow-up Recipe refresh fails', async () => {
        mocks.listRecipes
            .mockResolvedValueOnce([recipe])
            .mockRejectedValueOnce(new Error('refresh failed'));

        render(<MemoryRouter initialEntries={['/automation?version=rv_1']}><Automation /></MemoryRouter>);

        expect(await screen.findByText('Published')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Run once' }));

        await waitFor(() => expect(mocks.enqueueManualRun).toHaveBeenCalledWith('rv_1', {}));
        expect(await screen.findByText('The run is queued. Follow its progress below.')).toBeInTheDocument();
        expect(screen.getByText('Action completed, but Automation could not be refreshed.')).toBeInTheDocument();
        expect(screen.queryByText('recipes.actionFailed')).not.toBeInTheDocument();
    });

    it('fails closed without loading recipes when Automation is disabled', () => {
        state.serverConfig.AUTOMATION_ENABLED = false;

        render(<MemoryRouter initialEntries={['/automation']}><Automation /></MemoryRouter>);

        expect(screen.getByText('Automation is unavailable')).toBeInTheDocument();
        expect(mocks.listRecipes).not.toHaveBeenCalled();
    });
});
