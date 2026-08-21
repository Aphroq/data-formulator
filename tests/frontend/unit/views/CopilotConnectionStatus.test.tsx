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
        COPILOT_AUTH_STATUS: '/api/copilot/auth/status',
    }),
}));

vi.mock('../../../../src/views/CopilotConnectionPanel', () => ({
    CopilotConnectionPanel: ({
        active,
        onConnectionChange,
    }: {
        active: boolean;
        onConnectionChange?: (connected: boolean) => void;
    }) => (
        <button onClick={() => onConnectionChange?.(false)}>
            {active ? 'active-copilot-panel' : 'inactive-copilot-panel'}
        </button>
    ),
}));

import { apiRequest } from '../../../../src/app/apiClient';
import { CopilotConnectionStatus } from '../../../../src/views/CopilotConnectionStatus';


const mockApiRequest = vi.mocked(apiRequest);

describe('CopilotConnectionStatus', () => {
    beforeEach(() => {
        mockApiRequest.mockReset();
    });

    it('does not render or call auth endpoints when Copilot is disabled', () => {
        const { container } = render(<CopilotConnectionStatus enabled={false} />);

        expect(container).toBeEmptyDOMElement();
        expect(mockApiRequest).not.toHaveBeenCalled();
    });

    it('shows the identity connection state and opens the shared management panel', async () => {
        mockApiRequest.mockResolvedValueOnce({ data: { connected: true } });
        const onConnectionChange = vi.fn();

        render(
            <CopilotConnectionStatus
                enabled
                onConnectionChange={onConnectionChange}
            />,
        );

        expect(await screen.findByRole('status', {
            name: 'model.copilotStatusConnected',
        })).toBeInTheDocument();
        expect(mockApiRequest).toHaveBeenCalledWith('/api/copilot/auth/status');

        fireEvent.click(screen.getByRole('button', { name: 'model.copilotManage' }));

        expect(await screen.findByRole('dialog')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'active-copilot-panel' }));
        fireEvent.click(screen.getByRole('button', { name: 'app.close' }));
        expect(await screen.findByRole('status', {
            name: 'model.copilotStatusDisconnected',
        })).toBeInTheDocument();
        expect(onConnectionChange).toHaveBeenCalledWith(false);
    });

    it('keeps the management entry available when the status check fails', async () => {
        mockApiRequest.mockRejectedValueOnce(new Error('offline'));

        render(<CopilotConnectionStatus enabled />);

        expect(await screen.findByRole('status', {
            name: 'model.copilotStatusDisconnected',
        })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'model.copilotManage' })).toBeInTheDocument();
    });
});
