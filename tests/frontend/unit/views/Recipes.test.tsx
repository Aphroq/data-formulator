import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

const state = {
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


beforeEach(() => {
    vi.clearAllMocks();
    mocks.listRecipes.mockResolvedValue([recipe]);
    mocks.getRecipeVersion.mockResolvedValue(detail);
    mocks.dryRunRecipe.mockResolvedValue({
        result: {
            status: 'succeeded',
            run: { run_id: 'run_1', kind: 'dry_run', status: 'succeeded', manifest_hash: 'sha256:a' },
            steps: [],
            error: null,
        },
        version: { ...version, status: 'validated' },
    });
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
    });
});
