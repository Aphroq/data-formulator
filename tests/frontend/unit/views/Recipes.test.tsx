import React from 'react';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
            'recipes.title': 'Recipes',
            'recipes.subtitle': 'Deterministic workflows',
            'recipes.savedRecipes': 'Saved Recipes',
            'recipes.status.draft': 'Draft',
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
            'recipes.runSummary': 'Run summary',
            'recipes.runId': `Run ID: ${values?.runId}`,
            'recipes.runDuration': `Duration: ${values?.duration} ms`,
            'recipes.lastStep': `Last step: ${values?.step}`,
            'recipes.runStatus.succeeded': 'Succeeded',
            'recipes.runStatus.failed': 'Failed',
            'recipes.runStatus.needs_review': 'Needs review',
            'recipes.refreshAfterActionFailed': 'Action completed, but Recipes could not be refreshed.',
            'recipes.actionFailed': 'The Recipe action failed.',
        }[key] ?? key),
    }),
}));

import { Recipes } from '../../../../src/views/Recipes';


const version = {
    version_id: 'rv_1',
    recipe_id: 'rcp_1',
    recipe_hash: `sha256:${'a'.repeat(64)}`,
    status: 'draft',
    created_at: '2026-08-18T00:00:00Z',
    validated_at: null,
    published_at: null,
    archived_at: null,
    validation_run_id: null,
};

const recipe = {
    recipe_id: 'rcp_1',
    name: 'Regional totals',
    description: 'Refresh and chart regional totals.',
    created_by: 'user:alice',
    created_at: '2026-08-18T00:00:00Z',
    updated_at: '2026-08-18T00:00:00Z',
    versions: [version],
};

const detail = {
    recipe: { ...recipe, versions: undefined },
    version,
    spec: {
        recipe_id: 'rcp_1',
        version_id: 'rv_1',
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
        final_outputs: [],
    },
    workflow_markdown: '# Regional totals',
};

const runResult = {
    status: 'succeeded',
    run: { run_id: 'run_1', kind: 'manual', status: 'succeeded', manifest_hash: 'sha256:a' },
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

const deferred = <T,>() => {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>(next => { resolve = next; });
    return { promise, resolve };
};


beforeEach(() => {
    vi.clearAllMocks();
    state.activeWorkspace = { id: 'ws-1', displayName: 'Regional analysis' };
    state.serverConfig.AUTOMATION_ENABLED = true;
    mocks.listRecipes.mockResolvedValue([recipe]);
    mocks.getRecipeVersion.mockResolvedValue(detail);
    mocks.dryRunRecipe.mockResolvedValue({
        result: {
            ...runResult,
            run: { ...runResult.run, kind: 'dry_run' },
        },
        version: { ...version, status: 'validated' },
    });
    mocks.runRecipe.mockResolvedValue(runResult);
});


describe('Recipes page', () => {
    it('shows persisted inputs and steps and starts validation through the API', async () => {
        render(<MemoryRouter initialEntries={['/recipes']}><Recipes /></MemoryRouter>);

        expect(await screen.findByRole('heading', { name: 'Regional totals' })).toBeInTheDocument();
        expect(screen.getByText('warehouse')).toBeInTheDocument();
        expect(screen.getByText('Load data')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Dry run' }));

        await waitFor(() => {
            expect(mocks.dryRunRecipe).toHaveBeenCalledWith('rv_1', {});
        });
        expect(await screen.findByText('Dry run succeeded')).toBeInTheDocument();
        expect(screen.getByText('Run summary')).toBeInTheDocument();
        expect(screen.getByText('Duration: 125 ms')).toBeInTheDocument();
    });

    it('shows immutable version metadata instead of the mutable catalog name', async () => {
        mocks.listRecipes.mockResolvedValue([{
            ...recipe,
            name: 'Latest catalog name',
            description: 'Latest catalog description',
        }]);
        mocks.getRecipeVersion.mockResolvedValue({
            ...detail,
            recipe: {
                ...detail.recipe,
                name: 'Latest catalog name',
                description: 'Latest catalog description',
            },
            spec: {
                ...detail.spec,
                name: 'Immutable version name',
                description: 'Immutable version description',
            },
        });

        render(<MemoryRouter initialEntries={['/recipes']}><Recipes /></MemoryRouter>);

        expect(await screen.findByRole('heading', { name: 'Immutable version name' })).toBeInTheDocument();
        expect(screen.getByText('Immutable version description')).toBeInTheDocument();
    });

    it('ignores an older detail response after the selected URL version changes', async () => {
        const first = deferred<typeof detail>();
        const secondVersion = { ...version, version_id: 'rv_2' };
        const secondDetail = {
            ...detail,
            version: secondVersion,
            spec: {
                ...detail.spec,
                version_id: 'rv_2',
                name: 'Second immutable version',
            },
        };
        mocks.listRecipes.mockResolvedValue([{
            ...recipe,
            versions: [version, secondVersion],
        }]);
        mocks.getRecipeVersion.mockImplementation((versionId: string) => (
            versionId === 'rv_1' ? first.promise : Promise.resolve(secondDetail)
        ));

        render(
            <MemoryRouter initialEntries={['/recipes?version=rv_1']}>
                <Recipes />
            </MemoryRouter>,
        );

        fireEvent.click(await screen.findByText('Version 1'));
        expect(await screen.findByRole('heading', { name: 'Second immutable version' })).toBeInTheDocument();

        await act(async () => first.resolve(detail));
        expect(screen.getByRole('heading', { name: 'Second immutable version' })).toBeInTheDocument();
    });

    it('keeps a successful run result when the follow-up refresh fails', async () => {
        const publishedVersion = { ...version, status: 'published' };
        const publishedRecipe = { ...recipe, versions: [publishedVersion] };
        mocks.listRecipes
            .mockResolvedValueOnce([publishedRecipe])
            .mockRejectedValueOnce(new Error('refresh failed'));
        mocks.getRecipeVersion.mockResolvedValue({
            ...detail,
            version: publishedVersion,
        });

        render(<MemoryRouter initialEntries={['/recipes']}><Recipes /></MemoryRouter>);
        fireEvent.click(await screen.findByRole('button', { name: 'Run now' }));

        expect(await screen.findByText('Run run_1 succeeded.')).toBeInTheDocument();
        expect(screen.getByText('Run summary')).toBeInTheDocument();
        expect(screen.getByText('Action completed, but Recipes could not be refreshed.')).toBeInTheDocument();
        expect(screen.queryByText('The Recipe action failed.')).not.toBeInTheDocument();
    });
});
