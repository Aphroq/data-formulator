import { describe, expect, it } from 'vitest';

import { dataFormulatorReducer, dfActions } from '../../../../src/app/dfSlice';
import { getSerializableState } from '../../../../src/app/useAutoSave';

describe('context item persistence', () => {
    it('survives workspace serialization and restore on text turns and interactions', () => {
        const contextItems = [
            {
                uri: 'https://example.com/evidence',
                title: 'Evidence',
                provider: 'trustgraph',
                kind: 'source' as const,
            },
            {
                uri: 'urn:trustgraph:agent:session-one',
                title: 'Retrieval trace',
                provider: 'trustgraph',
                kind: 'trace' as const,
            },
        ];
        const saved = {
            activeWorkspace: { id: 'ws-1', displayName: 'Workspace 1' },
            derivedTables: [{
                id: 'derived-1',
                displayId: 'Derived 1',
                names: ['value'],
                metadata: { value: { type: 'number', semanticType: '', levels: [] } },
                rows: [{ value: 1 }],
                virtual: { tableId: 'derived-1', rowCount: 1 },
                description: '',
                derive: {
                    source: [],
                    code: 'result_df = input_df',
                    outputVariable: 'result_df',
                    dialog: [],
                    trigger: {
                        tableId: '__rootless_thread__',
                        resultTableId: 'derived-1',
                        interaction: [{
                            from: 'data-agent',
                            to: 'datarec-agent',
                            role: 'instruction',
                            content: 'Build the result',
                            contextItems,
                        }],
                    },
                },
            }],
            textTurns: [{
                kind: 'text',
                id: 'textTurn-1',
                displayId: 'textTurn-1',
                textKind: 'explain',
                content: 'Final answer',
                parentNodeId: 'derived-1',
                contextItems,
                createdAt: 1,
            }],
        };

        const loaded = dataFormulatorReducer(undefined, dfActions.loadState(saved));
        const snapshot = getSerializableState(loaded);
        const restored = dataFormulatorReducer(
            undefined,
            dfActions.loadState(JSON.parse(JSON.stringify(snapshot))),
        );

        expect(restored.textTurns[0].contextItems).toEqual(contextItems);
        expect(restored.derivedTables[0].derive?.trigger.interaction?.[0].contextItems)
            .toEqual(contextItems);
    });

    it('keeps historical sessions without context items unchanged', () => {
        const loaded = dataFormulatorReducer(undefined, dfActions.loadState({
            textTurns: [{
                kind: 'text',
                id: 'legacy-turn',
                displayId: 'legacy-turn',
                textKind: 'explain',
                content: 'Legacy answer',
                parentNodeId: '__rootless_thread__',
                createdAt: 1,
            }],
        }));

        expect(loaded.textTurns[0]).not.toHaveProperty('contextItems');
    });
});
