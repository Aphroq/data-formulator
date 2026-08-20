import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    compileRecipe: vi.fn(),
    listRecipeParameterCandidates: vi.fn(),
    suggestRecipeParameterConfigurations: vi.fn(),
    navigate: vi.fn(),
}));

vi.mock('../../../../src/app/recipeApi', () => ({
    compileRecipe: mocks.compileRecipe,
    listRecipeParameterCandidates: mocks.listRecipeParameterCandidates,
    suggestRecipeParameterConfigurations: mocks.suggestRecipeParameterConfigurations,
}));

vi.mock('react-router-dom', () => ({
    useNavigate: () => mocks.navigate,
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => ({
            'recipes.defaultName': 'Analysis Recipe',
            'recipes.saveAsRecipe': 'Save as Recipe',
            'recipes.saveDescription': 'Save this analysis as a reusable recipe.',
            'recipes.name': 'Recipe name',
            'recipes.description': 'Description',
            'recipes.adjustableValues': 'Values you can change later',
            'recipes.adjustableValuesDescription': 'Select safe inputs.',
            'recipes.findingAdjustableValues': 'Finding values…',
            'recipes.noAdjustableValues': 'No adjustable values.',
            'recipes.parameterCandidatesFailed': 'Could not inspect values.',
            'recipes.parameterCandidateKind.filter': 'Source filter',
            'recipes.parameterCandidateKind.limit': 'Row limit',
            'recipes.parameterCandidateKind.transform': 'Analysis setting',
            'recipes.currentValue': `Current: ${values?.value}`,
            'recipes.organizeParametersWithAi': 'Recommend run parameters',
            'recipes.organizingParameters': 'Recommending…',
            'recipes.aiParameterSuggestionsApplied': `Recommended ${values?.count} run parameters.`,
            'recipes.aiParameterNoMatches': 'No available value was important enough to recommend.',
            'recipes.aiParameterSuggestionsFailed': 'AI could not recommend parameters.',
            'recipes.unmatchedParameterSuggestions': `${values?.values} is fixed in this analysis.`,
            'recipes.selectModelForAiSuggestions': 'Select a model first.',
            'recipes.selectedAdjustableValues': 'Selected for this recipe',
            'recipes.showOtherAdjustableValues': `Other adjustable values (${values?.count})`,
            'recipes.hideOtherAdjustableValues': 'Hide other adjustable values',
            'recipes.askEveryRun': 'Fill in every run',
            'recipes.keepCurrentDefault': 'Use current value by default',
            'recipes.save': 'Save Recipe',
            'recipes.saveFailed': 'Save failed.',
            'recipes.artifactStale': 'Artifact stale.',
            'app.cancel': 'Cancel',
        }[key] ?? key),
    }),
}));

import {
    Chart,
    computeRecipeArtifactFingerprint,
} from '../../../../src/components/ComponentType';
import { SaveAsRecipeDialog } from '../../../../src/views/SaveAsRecipeDialog';


const chart = {
    id: 'chart-1',
    chartType: 'Bar Chart',
    encodingMap: {},
    tableRef: 'regional_totals',
    source: 'trigger',
    title: 'Regional totals',
    recipeArtifactId: `art_${'a'.repeat(64)}`,
} as Chart;
chart.recipeArtifactFingerprint = computeRecipeArtifactFingerprint(chart);


beforeEach(() => {
    vi.clearAllMocks();
    mocks.listRecipeParameterCandidates.mockResolvedValue([
        {
            candidate_id: 'cand_region',
            parameter_id: 'region',
            kind: 'filter',
            name: 'region',
            type: 'string',
            default: 'west',
        },
        {
            candidate_id: 'cand_limit',
            parameter_id: 'row_limit',
            kind: 'limit',
            name: 'Row limit',
            type: 'integer',
            default: 100,
        },
    ]);
    mocks.compileRecipe.mockResolvedValue({
        version: { version_id: 'rv_1' },
        spec: {},
        workflow_markdown: '# Regional totals',
    });
    mocks.suggestRecipeParameterConfigurations.mockResolvedValue({
        suggestions: [{
            candidate_id: 'cand_region',
            name: 'Sales region',
            description: 'Region included in this run.',
            mode: 'ask',
        }],
        unmatched: ['Top products'],
    });
});


describe('Save as Recipe dialog', () => {
    it('shows a compiler-approved transform setting with its authoring description', async () => {
        mocks.listRecipeParameterCandidates.mockResolvedValueOnce([{
            candidate_id: 'cand_top_n',
            parameter_id: 'top_n',
            kind: 'transform',
            name: 'Top genres',
            description: 'Number of highest-count genres included in the result.',
            type: 'integer',
            default: 5,
        }]);

        render(<SaveAsRecipeDialog chart={chart} open onClose={vi.fn()} />);

        fireEvent.click(await screen.findByRole('button', {
            name: 'Other adjustable values (1)',
        }));
        expect(await screen.findByText('Top genres')).toBeInTheDocument();
        expect(screen.getByText('Analysis setting · Current: 5')).toBeInTheDocument();
        expect(screen.getByText(
            'Number of highest-count genres included in the result.',
        )).toBeInTheDocument();
        expect(screen.getByRole('checkbox', { name: 'Top genres' })).not.toBeChecked();
        fireEvent.click(screen.getByRole('checkbox', { name: 'Top genres' }));

        fireEvent.click(screen.getByRole('button', { name: 'Save Recipe' }));

        await waitFor(() => expect(mocks.compileRecipe).toHaveBeenCalledWith({
            targetArtifactIds: [chart.recipeArtifactId],
            name: 'Regional totals',
            description: '',
            parameterConfigurations: [{
                candidate_id: 'cand_top_n',
                name: 'Top genres',
                description: 'Number of highest-count genres included in the result.',
                mode: 'keep',
            }],
        }));
    });

    it('leaves compiler candidates unselected and compiles only the user choices', async () => {
        render(<SaveAsRecipeDialog chart={chart} open onClose={vi.fn()} />);

        fireEvent.click(await screen.findByRole('button', {
            name: 'Other adjustable values (2)',
        }));
        expect(await screen.findByText('region')).toBeInTheDocument();
        const regionChoice = screen.getByRole('checkbox', { name: 'region' });
        const limitChoice = screen.getByRole('checkbox', { name: 'Row limit' });
        expect(regionChoice).not.toBeChecked();
        expect(limitChoice).not.toBeChecked();
        fireEvent.click(regionChoice);
        fireEvent.click(screen.getByRole('button', { name: 'Save Recipe' }));

        await waitFor(() => expect(mocks.compileRecipe).toHaveBeenCalledWith({
            targetArtifactIds: [chart.recipeArtifactId],
            name: 'Regional totals',
            description: '',
            parameterConfigurations: [{
                candidate_id: 'cand_region',
                name: 'region',
                description: '',
                mode: 'keep',
            }],
        }));
        expect(mocks.navigate).toHaveBeenCalledWith('/automation?version=rv_1');
    });

    it('uses optional AI suggestions as user-confirmed safe candidate metadata only', async () => {
        render(
            <SaveAsRecipeDialog
                chart={chart}
                open
                onClose={vi.fn()}
                aiContext={{
                    model: { endpoint: 'openai', model: 'test-model' },
                    workflowContext: { context_id: 'ws-1', threads: [] },
                    timeoutSeconds: 45,
                }}
            />,
        );

        await screen.findByRole('button', { name: 'Other adjustable values (2)' });
        fireEvent.click(screen.getByRole('button', { name: 'Recommend run parameters' }));

        expect(await screen.findByText('Sales region')).toBeInTheDocument();
        expect(screen.getByText('Region included in this run.')).toBeInTheDocument();
        expect(screen.getByText('Top products is fixed in this analysis.')).toBeInTheDocument();
        expect(screen.getByRole('switch', { name: 'Fill in every run' })).toBeChecked();
        fireEvent.click(screen.getByRole('button', { name: 'Other adjustable values (1)' }));
        expect(screen.getByRole('checkbox', { name: 'Row limit' })).not.toBeChecked();

        fireEvent.click(screen.getByRole('button', { name: 'Save Recipe' }));

        await waitFor(() => expect(mocks.compileRecipe).toHaveBeenCalledWith({
            targetArtifactIds: [chart.recipeArtifactId],
            name: 'Regional totals',
            description: '',
            parameterConfigurations: [{
                candidate_id: 'cand_region',
                name: 'Sales region',
                description: 'Region included in this run.',
                mode: 'ask',
            }],
        }));
    });

    it('keeps deterministic candidate choices usable when AI organization fails', async () => {
        mocks.suggestRecipeParameterConfigurations.mockRejectedValue(
            new Error('provider unavailable'),
        );
        render(
            <SaveAsRecipeDialog
                chart={chart}
                open
                onClose={vi.fn()}
                aiContext={{
                    model: { endpoint: 'openai', model: 'test-model' },
                    workflowContext: { context_id: 'ws-1', threads: [] },
                }}
            />,
        );

        fireEvent.click(await screen.findByRole('button', {
            name: 'Other adjustable values (2)',
        }));
        fireEvent.click(screen.getByRole('button', { name: 'Recommend run parameters' }));

        expect(
            await screen.findByText('AI could not recommend parameters.'),
        ).toBeInTheDocument();
        expect(screen.getByRole('checkbox', { name: 'region' })).not.toBeChecked();
        expect(screen.getByRole('checkbox', { name: 'Row limit' })).not.toBeChecked();

        fireEvent.click(screen.getByRole('button', { name: 'Save Recipe' }));

        await waitFor(() => expect(mocks.compileRecipe).toHaveBeenCalledWith({
            targetArtifactIds: [chart.recipeArtifactId],
            name: 'Regional totals',
            description: '',
            parameterConfigurations: [],
        }));
    });

    it('can explain a meaningful parameter even when no binding exists yet', async () => {
        mocks.listRecipeParameterCandidates.mockResolvedValueOnce([]);
        mocks.suggestRecipeParameterConfigurations.mockResolvedValueOnce({
            suggestions: [],
            unmatched: ['Top N'],
        });
        render(
            <SaveAsRecipeDialog
                chart={chart}
                open
                onClose={vi.fn()}
                aiContext={{
                    model: { endpoint: 'openai', model: 'test-model' },
                    workflowContext: { context_id: 'movies', threads: [] },
                }}
            />,
        );

        expect(await screen.findByText('No adjustable values.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Recommend run parameters' }));

        expect(await screen.findByText('Top N is fixed in this analysis.')).toBeInTheDocument();
        expect(screen.queryByText(
            'No available value was important enough to recommend.',
        )).not.toBeInTheDocument();
    });
});
