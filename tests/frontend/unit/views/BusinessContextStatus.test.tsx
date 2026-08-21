import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
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
        BUSINESS_CONTEXT_CONNECTION: '/api/agent/business-context-connection',
        BUSINESS_CONTEXT_CONNECTION_TEST: '/api/agent/business-context-connection/test',
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

    it('opens the current workspace connection dialog from the status', async () => {
        mockApiRequest
            .mockResolvedValueOnce({ data: { status: 'configured' } })
            .mockResolvedValueOnce({
                data: {
                    status: 'configured',
                    source: 'workspace',
                    connection: {
                        api_base: 'https://trustgraph.example',
                        trustgraph_workspace: 'manufacturing',
                        flow_id: 'default',
                        tool_group: 'ontology-readonly',
                        has_credential: true,
                    },
                },
            });

        render(<BusinessContextStatus workspaceId="workspace-ready" />);
        fireEvent.click(await screen.findByRole('button', {
            name: 'workspace.trustGraphConfigure',
        }));

        expect(await screen.findByRole('dialog')).toBeInTheDocument();
        expect(screen.getByDisplayValue('https://trustgraph.example')).toBeInTheDocument();
        expect(screen.queryByDisplayValue('reader-secret')).not.toBeInTheDocument();
        expect(mockApiRequest).toHaveBeenLastCalledWith(
            '/api/agent/business-context-connection',
            { headers: { 'X-Workspace-Id': 'workspace-ready' } },
        );
    });
});
