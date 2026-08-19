import { describe, expect, it } from 'vitest';

import {
    ContextItemAccumulator,
    getOpenableContextUri,
    normalizeContextItems,
} from '../../../../src/app/contextItems';

describe('context item normalization', () => {
    it('keeps bounded provider-neutral sources and rejects unsafe values', () => {
        const items = normalizeContextItems([
            {
                uri: ' https://example.com/evidence?id=1 ',
                title: ' Quarterly filing ',
                provider: ' trustgraph ',
            },
            { uri: 'https://example.com/evidence?id=1', title: 'duplicate' },
            { uri: 'urn:example:internal-record', title: 'Internal record' },
            { uri: 'javascript:alert(1)', title: 'unsafe' },
            { uri: 'https://user:secret@example.com/private', title: 'credentials' },
            { uri: 'https://example.com\\redirect', title: 'backslash' },
            null,
        ]);

        expect(items).toEqual([
            {
                uri: 'https://example.com/evidence?id=1',
                title: 'Quarterly filing',
                provider: 'trustgraph',
            },
            {
                uri: 'urn:example:internal-record',
                title: 'Internal record',
            },
        ]);
    });

    it('caps a streamed event at the shared frontend limit', () => {
        const items = normalizeContextItems(Array.from({ length: 60 }, (_, index) => ({
            uri: `https://example.com/source/${index}`,
        })));

        expect(items).toHaveLength(50);
        expect(items.at(-1)?.uri).toBe('https://example.com/source/49');
    });
});

describe('ContextItemAccumulator', () => {
    it('takes immutable per-interaction snapshots and keeps a deduplicated run-wide view', () => {
        const prior = { uri: 'https://example.com/prior', title: 'Prior turn' };
        const accumulator = new ContextItemAccumulator([prior]);

        accumulator.add([
            { uri: 'https://example.com/a', title: 'A' },
            { uri: 'https://example.com/b', title: 'B' },
        ]);
        const firstInteraction = accumulator.all();
        expect(firstInteraction.map(item => item.uri)).toEqual([
            'https://example.com/prior',
            'https://example.com/a',
            'https://example.com/b',
        ]);

        accumulator.add([
            { uri: 'https://example.com/b', title: 'B again' },
            { uri: 'https://example.com/c', title: 'C' },
        ]);

        expect(firstInteraction.map(item => item.uri)).toEqual([
            'https://example.com/prior',
            'https://example.com/a',
            'https://example.com/b',
        ]);
        expect(accumulator.all().map(item => item.uri)).toEqual([
            'https://example.com/prior',
            'https://example.com/a',
            'https://example.com/b',
            'https://example.com/c',
        ]);
    });
});

describe('getOpenableContextUri', () => {
    it('opens only credential-free HTTP(S) sources', () => {
        expect(getOpenableContextUri('https://example.com/evidence')).toBe(
            'https://example.com/evidence',
        );
        expect(getOpenableContextUri('urn:example:evidence')).toBeUndefined();
        expect(getOpenableContextUri('javascript:alert(1)')).toBeUndefined();
        expect(getOpenableContextUri('https://user:pass@example.com')).toBeUndefined();
    });
});
