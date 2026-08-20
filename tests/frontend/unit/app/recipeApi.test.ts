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
    listRecipeParameterCandidates,
    listRecipes,
    publishRecipe,
    runRecipe,
    suggestRecipeParameterConfigurations,
} from '../../../../src/app/recipeApi';


beforeEach(() => {
    vi.clearAllMocks();
});


describe('Recipe API client', () => {
    it('inspects, suggests metadata for, and compiles only explicit safe slots', async () => {
        const payload = { version: { version_id: 'rv_1' }, spec: {}, workflow_markdown: '# Recipe' };
        const candidates = [{
            candidate_id: 'cand_1',
            parameter_id: 'region',
            kind: 'filter',
            name: 'region',
            type: 'string',
            default: 'west',
        }];
        mocks.apiRequest
            .mockResolvedValueOnce({ data: { candidates } })
            .mockResolvedValueOnce({ data: { suggestions: [{
                candidate_id: 'cand_1',
                name: 'Sales region',
                description: 'Region included in this run.',
                mode: 'ask',
            }], unmatched: ['Top products'] } })
            .mockResolvedValueOnce({ data: payload });

        await expect(listRecipeParameterCandidates(['art_1'])).resolves.toBe(candidates);

        await expect(suggestRecipeParameterConfigurations({
            targetArtifactIds: ['art_1'],
            model: { endpoint: 'openai', model: 'test-model' },
            workflowContext: { context_id: 'ws-1', threads: [] },
            name: 'Revenue',
            description: 'Monthly revenue',
            timeoutSeconds: 45,
        })).resolves.toEqual({
            suggestions: [expect.objectContaining({ name: 'Sales region' })],
            unmatched: ['Top products'],
        });

        await expect(compileRecipe({
            targetArtifactIds: ['art_1'],
            name: 'Revenue',
            description: 'Monthly revenue',
            parameterConfigurations: [{
                candidate_id: 'cand_1',
                name: 'Sales region',
                description: 'Region included in this run.',
                mode: 'ask',
            }],
        })).resolves.toBe(payload);

        expect(mocks.apiRequest).toHaveBeenNthCalledWith(1, '/api/recipes/parameter-candidates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_artifact_ids: ['art_1'] }),
        });
        expect(mocks.apiRequest).toHaveBeenNthCalledWith(2, '/api/recipes/parameter-suggestions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_artifact_ids: ['art_1'],
                model: { endpoint: 'openai', model: 'test-model' },
                workflow_context: { context_id: 'ws-1', threads: [] },
                name: 'Revenue',
                description: 'Monthly revenue',
                timeout_seconds: 45,
            }),
        });
        expect(mocks.apiRequest).toHaveBeenNthCalledWith(3, '/api/recipes/compile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_artifact_ids: ['art_1'],
                name: 'Revenue',
                description: 'Monthly revenue',
                parameter_configurations: [{
                    candidate_id: 'cand_1',
                    name: 'Sales region',
                    description: 'Region included in this run.',
                    mode: 'ask',
                }],
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
