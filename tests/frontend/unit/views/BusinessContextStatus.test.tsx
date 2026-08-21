import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: vi.fn(),
}));

vi.mock('../../../../src/app/utils', () => ({
    getUrls: () => ({
        BUSINESS_CONTEXT_STATUS: '/api/agent/business-context-status',
    }),
}));

import { apiRequest } from '../../../../src/app/apiClient';
import { BusinessContextStatus } from '../../../../src/views/BusinessContextStatus';


const mockApiRequest = vi.mocked(apiRequest);

describe('BusinessContextStatus', () => {
    beforeEach(() => {
        mockApiRequest.mockReset();
    });

    it('renders the configured state for the current workspace', async () => {
        mockApiRequest.mockResolvedValueOnce({ data: { status: 'configured' } });

        render(<BusinessContextStatus workspaceId="workspace-ready" />);

        expect(await screen.findByRole('status', {
            name: 'workspace.businessKnowledgeConfigured',
        })).toBeInTheDocument();
        expect(mockApiRequest).toHaveBeenCalledWith(
            '/api/agent/business-context-status',
            { headers: { 'X-Workspace-Id': 'workspace-ready' } },
        );
    });

    it('shows unconfigured and refreshes when the workspace changes', async () => {
        mockApiRequest
            .mockResolvedValueOnce({ data: { status: 'configured' } })
            .mockResolvedValueOnce({ data: { status: 'unconfigured' } });
        const { rerender } = render(
            <BusinessContextStatus workspaceId="workspace-one" />,
        );
        await screen.findByRole('status', {
            name: 'workspace.businessKnowledgeConfigured',
        });

        rerender(<BusinessContextStatus workspaceId="workspace-two" />);

        expect(await screen.findByRole('status', {
            name: 'workspace.businessKnowledgeUnconfigured',
        })).toBeInTheDocument();
        expect(mockApiRequest).toHaveBeenLastCalledWith(
            '/api/agent/business-context-status',
            { headers: { 'X-Workspace-Id': 'workspace-two' } },
        );
    });

    it('renders nothing when TrustGraph is disabled', async () => {
        mockApiRequest.mockResolvedValueOnce({ data: { status: 'disabled' } });

        const { container } = render(
            <BusinessContextStatus workspaceId="workspace-disabled" />,
        );

        await vi.waitFor(() => expect(mockApiRequest).toHaveBeenCalledOnce());
        expect(container).toBeEmptyDOMElement();
    });
});
