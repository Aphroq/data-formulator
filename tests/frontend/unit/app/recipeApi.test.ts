import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: mocks.apiRequest,
}));

import {
    archiveRecipe,
    compileRecipe,
    dryRunRecipe,
    getRecipeVersion,
    listRecipes,
    publishRecipe,
    runRecipe,
} from '../../../../src/app/recipeApi';


beforeEach(() => {
    vi.clearAllMocks();
});


describe('Recipe API client', () => {
    it('compiles only explicit durable artifact ids', async () => {
        const payload = { version: { version_id: 'rv_1' }, spec: {}, workflow_markdown: '# Recipe' };
        mocks.apiRequest.mockResolvedValue({ data: payload });

        await expect(compileRecipe({
            targetArtifactIds: ['art_1'],
            name: 'Revenue',
            description: 'Monthly revenue',
        })).resolves.toBe(payload);

        expect(mocks.apiRequest).toHaveBeenCalledWith('/api/recipes/compile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_artifact_ids: ['art_1'],
                name: 'Revenue',
                description: 'Monthly revenue',
            }),
        });
    });

    it('uses scoped version lifecycle endpoints and typed parameter objects', async () => {
        mocks.apiRequest
            .mockResolvedValueOnce({ data: { recipes: [{ recipe_id: 'rcp_1' }] } })
            .mockResolvedValueOnce({ data: { version: { version_id: 'rv_1' } } })
            .mockResolvedValueOnce({ data: { result: { status: 'succeeded' }, version: { status: 'validated' } } })
            .mockResolvedValueOnce({ data: { version: { status: 'published' } } })
            .mockResolvedValueOnce({ data: { result: { status: 'succeeded' } } })
            .mockResolvedValueOnce({ data: { version: { status: 'archived' } } });

        await listRecipes();
        await getRecipeVersion('rv/1');
        await dryRunRecipe('rv/1', { limit: 25 });
        await publishRecipe('rv/1');
        await runRecipe('rv/1', { limit: 25 });
        await archiveRecipe('rv/1');

        expect(mocks.apiRequest.mock.calls.map(call => call[0])).toEqual([
            '/api/recipes',
            '/api/recipes/versions/rv%2F1',
            '/api/recipes/versions/rv%2F1/dry-run',
            '/api/recipes/versions/rv%2F1/publish',
            '/api/recipes/versions/rv%2F1/run',
            '/api/recipes/versions/rv%2F1/archive',
        ]);
        expect(JSON.parse(mocks.apiRequest.mock.calls[2][1].body)).toEqual({
            parameters: { limit: 25 },
        });
        expect(JSON.parse(mocks.apiRequest.mock.calls[4][1].body)).toEqual({
            parameters: { limit: 25 },
        });
    });
});
