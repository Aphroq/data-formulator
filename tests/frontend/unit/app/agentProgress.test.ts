import { describe, expect, it } from 'vitest';

import {
    applyBusinessContextToolProgress,
    beginBusinessContextProgress,
    businessContextProgress,
    createBusinessContextProgressState,
    settleBusinessContextProgress,
    settleLatestProgressStep,
} from '../../../../src/app/agentProgress';

describe('agent business-context progress', () => {
    it('uses one generic label only for the high-level business query', () => {
        const translate = (key: string) => key === 'dataThread.checkingBusinessKnowledge'
            ? 'checking business knowledge...'
            : key;

        expect(businessContextProgress('query_business_context', translate)).toBe(
            'checking business knowledge...',
        );
        expect(businessContextProgress('knowledge_query', translate)).toBeUndefined();
    });

    it('settles the latest pending step for success and failure', () => {
        const successful = ['✓ loaded skill', 'checking business knowledge...'];
        settleLatestProgressStep(successful, false);
        expect(successful).toEqual([
            '✓ loaded skill',
            '✓ checking business knowledge...',
        ]);

        const failed = ['checking business knowledge...'];
        settleLatestProgressStep(failed, true);
        expect(failed).toEqual(['✗ checking business knowledge...']);
    });

    it('updates each query round in place and adds only a new round or finalization', () => {
        const translate = (key: string, options?: Record<string, unknown>) => (
            `${key}${options?.index ? `:${options.index}` : ''}`
        );
        const steps = ['✓ loaded skill'];
        const state = createBusinessContextProgressState();

        expect(beginBusinessContextProgress(
            steps,
            'query_business_context',
            translate,
            state,
        )).toBe(true);
        expect(steps).toEqual([
            '✓ loaded skill',
            'dataThread.checkingBusinessKnowledge',
        ]);

        for (const phase of ['searching', 'filtering', 'summarizing', 'completed']) {
            const event = {
                type: 'tool_progress',
                tool: 'query_business_context',
                query_index: 1,
                phase,
                thought: 'must not be rendered',
            };
            expect(applyBusinessContextToolProgress(
                steps,
                event,
                translate,
                state,
            )).toBe(true);
            expect(steps).toHaveLength(2);
        }
        expect(steps[1]).toBe('✓ dataThread.businessKnowledgeCompleted:1');

        applyBusinessContextToolProgress(
            steps,
            {
                tool: 'query_business_context',
                query_index: 2,
                phase: 'searching',
            },
            translate,
            state,
        );
        expect(steps).toHaveLength(3);
        expect(steps[2]).toBe('dataThread.businessKnowledgeSearching:2');

        applyBusinessContextToolProgress(
            steps,
            {
                tool: 'query_business_context',
                query_index: null,
                phase: 'finalizing',
            },
            translate,
            state,
        );
        expect(steps).toHaveLength(4);
        expect(steps[3]).toBe('dataThread.businessKnowledgeFinalizing');

        settleBusinessContextProgress(steps, state, false);
        expect(steps[3]).toBe('✓ dataThread.businessKnowledgeFinalizing');
        expect(steps.join(' ')).not.toContain('must not be rendered');
    });

    it('settles an early failure without changing an earlier tool row', () => {
        const steps = ['✓ loaded skill'];
        const state = createBusinessContextProgressState();
        const translate = (key: string) => key;
        beginBusinessContextProgress(
            steps,
            'query_business_context',
            translate,
            state,
        );

        settleBusinessContextProgress(steps, state, true);

        expect(steps).toEqual([
            '✓ loaded skill',
            '✗ dataThread.checkingBusinessKnowledge',
        ]);
        expect(applyBusinessContextToolProgress(
            steps,
            {
                tool: 'query_business_context',
                query_index: 1,
                phase: 'unknown',
            },
            translate,
            state,
        )).toBe(false);
    });
});
