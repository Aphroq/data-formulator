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
    runRecipe: vi.fn(),
    archiveRecipe: vi.fn(),
}));

const state: any = {
    activeWorkspace: { id: 'ws-1', displayName: 'Regional analysis' },
    serverConfig: { AUTOMATION_ENABLED: true },
};

vi.mock('react-redux', () => ({
    useSelector: (selector: (value: any) => unknown) => selector(state),
}));

vi.mock('../../../../src/app/recipeApi', () => ({
    listRecipes: mocks.listRecipes,
    getRecipeVersion: mocks.getRecipeVersion,
    dryRunRecipe: mocks.dryRunRecipe,
    publishRecipe: mocks.publishRecipe,
    runRecipe: mocks.runRecipe,
    archiveRecipe: mocks.archiveRecipe,
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => ({
            'automation.title': 'Automation',
            'automation.subtitle': 'Manage deterministic recipes',
            'automation.openApp': 'Open App',
            'automation.unavailable': 'Automation is unavailable',
            'automation.recipes': 'Recipes',
            'automation.versionsCount': `${values?.count} versions`,
            'automation.updated': `Updated ${values?.date}`,
            'automation.versionPicker': 'Version',
            'automation.runResult.title': 'Latest run result',
            'automation.runResult.status.succeeded': 'Succeeded',
            'automation.runResult.status.failed': 'Failed',
            'automation.runResult.status.needs_review': 'Needs review',
            'automation.runResult.kind.dry_run': 'Dry run result',
            'automation.runResult.kind.manual': 'Manual run result',
            'automation.runResult.runId': 'Run ID',
            'automation.runResult.summary': `${values?.count} steps · ${values?.duration} ms`,
            'automation.runResult.steps': 'Step results',
            'automation.runResult.noSteps': 'No step result',
            'automation.runResult.finalOutput': 'Final output',
            'automation.runResult.duration': `${values?.duration} ms`,
            'automation.runResult.outputPath': 'Saved output',
            'automation.runResult.contentHash': 'content',
            'automation.runResult.schemaHash': 'schema',
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
            'recipes.dryRun': 'Dry run',
            'recipes.dryRunSucceeded': 'Dry run succeeded',
            'recipes.runNow': 'Run now',
            'recipes.runSucceeded': `Run ${values?.runId} succeeded.`,
            'recipes.runFailed': 'Run failed',
            'recipes.refreshAfterActionFailed': 'Action completed, but Automation could not be refreshed.',
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

const runResult = {
    status: 'succeeded',
    run: { run_id: 'run_2', kind: 'manual', status: 'succeeded', manifest_hash: 'sha256:a' },
    steps: [{
        step_id: 'step_1',
        kind: 'load',
        content_hash: `sha256:${'b'.repeat(64)}`,
        schema_hash: `sha256:${'c'.repeat(64)}`,
        output_path: 'workspace/data/orders.parquet',
        duration_ms: 125,
    }],
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
    mocks.runRecipe.mockResolvedValue(runResult);
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

        fireEvent.click(screen.getByRole('button', { name: 'Dry run' }));

        await waitFor(() => {
            expect(mocks.dryRunRecipe).toHaveBeenCalledWith('rv_2', {});
        });
        expect(await screen.findByText('Dry run succeeded')).toBeInTheDocument();
        const resultPanel = screen.getByRole('region', { name: 'Latest run result' });
        expect(within(resultPanel).getByText('Succeeded')).toBeInTheDocument();
        expect(within(resultPanel).getByText(/run_1/)).toBeInTheDocument();
        expect(within(resultPanel).getByText(/workspace\/data\/orders.parquet/)).toBeInTheDocument();
        expect(within(resultPanel).getByText('Final output')).toBeInTheDocument();
    });

    it('shows an execution error when a manual run fails before producing output', async () => {
        mocks.runRecipe.mockResolvedValue({
            status: 'failed',
            run: { run_id: 'run_failed', kind: 'manual', status: 'failed', manifest_hash: 'sha256:f' },
            steps: [],
            error: {
                code: 'connector_error',
                exception_type: 'RecipeConnectorError',
                message: 'The source could not be opened.',
            },
        });
        render(<MemoryRouter initialEntries={['/automation?version=rv_1']}><Automation /></MemoryRouter>);

        expect(await screen.findByText('Published')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Run now' }));

        await waitFor(() => expect(mocks.runRecipe).toHaveBeenCalledWith('rv_1', {}));
        const resultPanel = await screen.findByRole('region', { name: 'Latest run result' });
        expect(within(resultPanel).getByText('Failed')).toBeInTheDocument();
        expect(within(resultPanel).getByText('connector_error')).toBeInTheDocument();
        expect(within(resultPanel).getByText('The source could not be opened.')).toBeInTheDocument();
        expect(within(resultPanel).getByText('No step result')).toBeInTheDocument();
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

    it('keeps a successful run result when the follow-up refresh fails', async () => {
        mocks.listRecipes
            .mockResolvedValueOnce([recipe])
            .mockRejectedValueOnce(new Error('refresh failed'));

        render(<MemoryRouter initialEntries={['/automation?version=rv_1']}><Automation /></MemoryRouter>);

        expect(await screen.findByText('Published')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Run now' }));

        await waitFor(() => expect(mocks.runRecipe).toHaveBeenCalledWith('rv_1', {}));
        expect(await screen.findByRole('region', { name: 'Latest run result' })).toBeInTheDocument();
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
