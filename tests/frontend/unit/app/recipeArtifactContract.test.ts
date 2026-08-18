import { describe, expect, it } from 'vitest';

import {
    Chart,
    computeRecipeArtifactFingerprint,
} from '../../../../src/components/ComponentType';
import { isChartRecipeArtifactCurrent } from '../../../../src/views/SaveAsRecipeDialog';


const generatedChart = (): Chart => ({
    id: 'chart-1',
    chartType: 'Bar Chart',
    tableRef: 'regional_totals',
    source: 'user',
    encodingMap: {
        x: { fieldID: 'region' },
        y: { fieldID: 'total', aggregate: 'sum' },
    },
    title: 'Regional totals',
    recipeArtifactId: `art_${'a'.repeat(64)}`,
});


describe('chart Recipe artifact contract', () => {
    it('is stable across object key ordering and ignores UI identity markers', () => {
        const chart = generatedChart();
        const fingerprint = computeRecipeArtifactFingerprint(chart);
        const reordered = {
            ...chart,
            id: 'chart-copy',
            unread: true,
            encodingMap: {
                y: { aggregate: 'sum', fieldID: 'total' },
                x: { fieldID: 'region' },
            },
            recipeArtifactFingerprint: fingerprint,
        } as Chart;

        expect(computeRecipeArtifactFingerprint(reordered)).toBe(fingerprint);
    });

    it('invalidates the artifact snapshot after reproducible chart edits', () => {
        const chart = generatedChart();
        const fingerprint = computeRecipeArtifactFingerprint(chart);
        chart.recipeArtifactFingerprint = fingerprint;
        const edited = {
            ...chart,
            encodingMap: {
                ...chart.encodingMap,
                y: { ...chart.encodingMap.y, aggregate: 'average' },
            },
        } as Chart;

        expect(isChartRecipeArtifactCurrent(chart)).toBe(true);
        expect(isChartRecipeArtifactCurrent(edited)).toBe(false);
        expect(computeRecipeArtifactFingerprint(edited)).not.toBe(fingerprint);
    });
});
