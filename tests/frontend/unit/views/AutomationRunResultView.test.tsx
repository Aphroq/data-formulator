import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';


const mocks = vi.hoisted(() => ({
    analyzeRunResult: vi.fn(),
}));


vi.mock('react-dnd', () => ({
    DndProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../../../src/app/automationApi', () => ({
    analyzeRunResult: mocks.analyzeRunResult,
    sampleRunResultTable: vi.fn(),
    downloadRunResultTable: vi.fn(),
}));

vi.mock('../../../../src/app/utils', () => ({
    extractFieldsFromEncodingMap: () => ({ aggregateFields: [], groupByFields: [] }),
    prepVisTable: (rows: Record<string, unknown>[]) => rows,
    resolveRecommendedChart: ({ chart }: { chart: { chart_type: string } }) => ({
        chartType: chart.chart_type,
        encodingMap: {},
        config: {},
    }),
}));

vi.mock('../../../../src/views/DataView', () => ({
    FreeDataViewFC: ({ tableOverride }: { tableOverride: { displayId: string } }) => (
        <div>Saved table: {tableOverride.displayId}</div>
    ),
}));

vi.mock('../../../../src/views/VisualizationView', () => ({
    VegaChartRenderer: ({ insightTitle }: { insightTitle?: string }) => (
        <div role="img" aria-label={`Saved chart: ${insightTitle ?? ''}`} />
    ),
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: vi.fn() },
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) => ({
            'automation.runs.supportingData': 'Supporting data',
            'automation.runs.supportingDataSummary': `${values?.rows} rows · ${values?.columns} columns`,
            'automation.runs.aiAnalysis': 'AI analysis',
            'automation.runs.aiAnalysisHelp': 'Send saved result samples to the selected model for interpretation.',
            'automation.runs.aiNeedsModel': 'Select a model to use AI analysis.',
            'automation.runs.aiGenerated': 'AI-generated. Verify against the saved data.',
            'automation.runs.aiFailed': 'AI analysis failed.',
            'automation.runs.aiRetry': 'Analyze again',
            'automation.runs.columnsTruncated': 'Some columns are hidden.',
            'automation.runs.chartFailed': 'Chart failed.',
            'automation.runs.noResult': 'No result.',
            'recipes.stepKind.load': 'Load data',
            'recipes.stepKind.transform': 'Transform data',
            'recipes.stepKind.chart': 'Create chart',
        }[key] ?? key),
    }),
}));

import { AutomationRunResultView } from '../../../../src/views/AutomationRunResultView';


beforeEach(() => {
    vi.clearAllMocks();
});


const run = {
    run_id: `run_${'1'.repeat(32)}`,
    version_id: `rv_${'2'.repeat(64)}`,
    schedule_id: null,
    trigger: 'manual' as const,
    scheduled_for: '2026-08-20T06:54:26Z',
    status: 'succeeded' as const,
    attempt_count: 1,
    available_at: '2026-08-20T06:54:26Z',
    cancel_requested_at: null,
    artifact: null,
    error: null,
    created_at: '2026-08-20T06:54:26Z',
    updated_at: '2026-08-20T06:54:30Z',
    parameters: { major_genre: 'Comedy' },
};

const table = (name: string, rows: Record<string, unknown>[]) => ({
    name,
    row_count: rows.length,
    column_count: 2,
    columns: [
        { name: 'category', type: 'string' as const },
        { name: 'value', type: 'integer' as const },
    ],
    rows,
    rows_truncated: false,
    columns_truncated: false,
});

const result = {
    manifest: {
        run_id: run.run_id,
        recipe_id: 'rcp_movies',
        version_id: run.version_id,
        kind: 'automation' as const,
        status: 'succeeded' as const,
        binding_hash: 'sha256:binding',
        error: null,
        files: {},
    },
    events: [],
    report: {
        title: 'Movie performance summary',
        description: 'Compare the selected movie segment across two saved outcomes.',
        parameters: [{
            id: 'major_genre',
            name: 'Movie genre',
            description: 'Genre included in the source data.',
            type: 'string' as const,
        }],
        steps: [
            { step_id: 'load', kind: 'load' as const, title: 'Movies' },
            { step_id: 'transform', kind: 'transform' as const, title: 'genre_summary' },
            { step_id: 'chart', kind: 'chart' as const, title: 'Movies by genre' },
        ],
    },
    outputs: [
        {
            step_id: 'chart',
            kind: 'chart' as const,
            title: 'Movies by genre',
            subtitle: 'The selected segment',
            display_instruction: 'Compare movie counts.',
            chart: {
                spec: {
                    chart_type: 'Bar Chart',
                    encodings: { x: 'category', y: 'value' },
                },
                field_metadata: {},
                field_display_names: {},
            },
            table: table('genre_summary', [{ category: 'Comedy', value: 675 }]),
        },
        {
            step_id: 'table',
            kind: 'transform' as const,
            title: 'Highest-grossing movies',
            subtitle: '',
            display_instruction: 'Review the saved rows.',
            chart: null,
            table: table('top_movies', [{ category: 'Avatar', value: 2767891499 }]),
        },
    ],
};


describe('Automation run analysis report', () => {
    it('renders every final output without repeating report and workflow helper text', () => {
        render(<AutomationRunResultView run={run} result={result} />);

        expect(screen.queryByText(result.report.description)).not.toBeInTheDocument();
        expect(screen.queryByText('The selected segment')).not.toBeInTheDocument();
        expect(screen.getByText('Compare movie counts.')).toBeInTheDocument();
        expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Movies by genre' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Highest-grossing movies' })).toBeInTheDocument();
        expect(screen.queryByText('Analysis process')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'AI analysis' })).toBeDisabled();
    });

    it('keeps chart evidence readable and reveals its saved rows on demand', () => {
        render(<AutomationRunResultView run={run} result={result} />);

        const dataToggle = screen.getByRole('button', { name: /Supporting data/ });
        expect(dataToggle).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(dataToggle);
        expect(dataToggle).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByText('Saved table: Movies by genre')).toBeVisible();

        expect(screen.getByText('Saved table: Highest-grossing movies')).toBeVisible();
    });

    it('runs a concise AI interpretation only after an explicit click', async () => {
        mocks.analyzeRunResult.mockResolvedValue({
            summary: 'Comedy contributes a substantial saved result.',
            insights: [{
                finding: 'The segment contains many movies.',
                evidence: 'The saved result contains 675 Comedy movies.',
            }],
            caveat: 'This run does not compare other genres.',
        });
        render(
            <AutomationRunResultView
                run={run}
                result={result}
                analysisConfig={{
                    model: { endpoint: 'openai', model: 'test-model' },
                    timeoutSeconds: 45,
                }}
            />,
        );

        expect(mocks.analyzeRunResult).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'AI analysis' }));

        await waitFor(() => expect(mocks.analyzeRunResult).toHaveBeenCalledWith(
            run.run_id,
            {
                model: { endpoint: 'openai', model: 'test-model' },
                timeoutSeconds: 45,
            },
        ));
        const analysis = await screen.findByRole('region', { name: 'AI analysis' });
        expect(analysis).toHaveTextContent('Comedy contributes a substantial saved result.');
        expect(analysis).toHaveTextContent('The saved result contains 675 Comedy movies.');
        expect(analysis).toHaveTextContent('This run does not compare other genres.');
        expect(analysis).toHaveTextContent('AI-generated. Verify against the saved data.');
    });
});
