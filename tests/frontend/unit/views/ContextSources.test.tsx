import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, params?: Record<string, unknown>) => {
            if (key === 'contextSources.title') return `Sources (${String(params?.count)})`;
            if (key === 'contextSources.open') return `Open source: ${String(params?.title)}`;
            return key;
        },
    }),
}));

import { ContextSources } from '../../../../src/views/ContextSources';

describe('ContextSources', () => {
    it('renders nothing when no valid sources exist', () => {
        const { container } = render(<ContextSources items={[
            { uri: 'javascript:alert(1)', title: 'Unsafe' },
        ] as any} />);

        expect(container).toBeEmptyDOMElement();
    });

    it('opens only safe HTTP(S) sources in an isolated tab and keeps URNs non-clickable', () => {
        render(<ContextSources items={[
            { uri: 'https://example.com/evidence', title: 'Public evidence', provider: 'trustgraph' },
            { uri: 'urn:example:internal', title: 'Internal record', provider: 'trustgraph' },
            { uri: 'javascript:alert(1)', title: 'Unsafe' },
        ] as any} />);

        fireEvent.click(screen.getByRole('button', { name: 'Sources (2)' }));

        const link = screen.getByRole('link', { name: 'Open source: Public evidence' });
        expect(link).toHaveAttribute('href', 'https://example.com/evidence');
        expect(link).toHaveAttribute('target', '_blank');
        expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        expect(screen.getByText('Internal record').closest('a')).toBeNull();
        expect(screen.queryByText('Unsafe')).toBeNull();
    });
});
