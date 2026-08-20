import React from 'react';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: vi.fn(),
}));

vi.mock('../../../../src/app/utils', () => ({
    getUrls: () => ({
        COPILOT_AUTH_STATUS: '/api/copilot/auth/status',
        COPILOT_AUTH_START: '/api/copilot/auth/device/start',
        COPILOT_AUTH_POLL: '/api/copilot/auth/device/poll',
        COPILOT_AUTH_CANCEL: '/api/copilot/auth/device/cancel',
        COPILOT_AUTH_DISCONNECT: '/api/copilot/auth/disconnect',
    }),
}));

import { apiRequest } from '../../../../src/app/apiClient';
import { CopilotConnectionPanel } from '../../../../src/views/CopilotConnectionPanel';


const mockApiRequest = vi.mocked(apiRequest);

describe('CopilotConnectionPanel', () => {
    beforeEach(() => {
        mockApiRequest.mockReset();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('does not touch the auth API while the model dialog is inactive', () => {
        render(<CopilotConnectionPanel active={false} />);

        expect(mockApiRequest).not.toHaveBeenCalled();
    });

    it('starts only from an explicit click and renders no secret fields', async () => {
        mockApiRequest
            .mockResolvedValueOnce({ data: { connected: false } })
            .mockResolvedValueOnce({
                data: {
                    status: 'pending',
                    authorization_id: 'opaque-browser-handle',
                    user_code: 'ABCD-EFGH',
                    verification_uri: 'https://github.com/login/device',
                    expires_in: 900,
                    interval: 5,
                },
            });

        const { container } = render(<CopilotConnectionPanel active />);
        await screen.findByRole('button', { name: 'model.copilotConnect' });
        expect(mockApiRequest).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole('button', { name: 'model.copilotConnect' }));
        await screen.findByText('ABCD-EFGH');

        expect(mockApiRequest).toHaveBeenNthCalledWith(
            2,
            '/api/copilot/auth/device/start',
            expect.objectContaining({
                method: 'POST',
                body: '{}',
            }),
        );
        const link = screen.getByRole('link', { name: 'model.copilotOpenGitHub' });
        expect(link).toHaveAttribute('href', 'https://github.com/login/device');
        expect(link).toHaveAttribute('target', '_blank');
        expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        expect(container.textContent).not.toContain('opaque-browser-handle');
        expect(container.textContent).not.toContain('device_code');
        expect(container.textContent).not.toContain('access_token');
    });

    it('waits for the server interval before polling and stops after connection', async () => {
        vi.useFakeTimers();
        mockApiRequest
            .mockResolvedValueOnce({ data: { connected: false } })
            .mockResolvedValueOnce({
                data: {
                    status: 'pending',
                    authorization_id: 'opaque-handle',
                    user_code: 'ABCD-EFGH',
                    verification_uri: 'https://github.com/login/device',
                    expires_in: 900,
                    interval: 5,
                },
            })
            .mockResolvedValueOnce({ data: { status: 'connected' } });

        render(<CopilotConnectionPanel active />);
        await act(async () => { await Promise.resolve(); });
        fireEvent.click(screen.getByRole('button', { name: 'model.copilotConnect' }));
        await act(async () => { await Promise.resolve(); });

        expect(mockApiRequest).toHaveBeenCalledTimes(2);
        await act(async () => { await vi.advanceTimersByTimeAsync(4_999); });
        expect(mockApiRequest).toHaveBeenCalledTimes(2);

        await act(async () => { await vi.advanceTimersByTimeAsync(1); });
        await act(async () => { await Promise.resolve(); });
        expect(mockApiRequest).toHaveBeenCalledTimes(3);
        expect(screen.getByText('model.copilotConnected')).toBeInTheDocument();
        expect(mockApiRequest).toHaveBeenLastCalledWith(
            '/api/copilot/auth/device/poll',
            expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({ authorization_id: 'opaque-handle' }),
            }),
        );
    });

    it('never renders an unexpected verification URL as a link', async () => {
        mockApiRequest
            .mockResolvedValueOnce({ data: { connected: false } })
            .mockResolvedValueOnce({
                data: {
                    status: 'pending',
                    authorization_id: 'opaque-handle',
                    user_code: 'ABCD-EFGH',
                    verification_uri: 'https://evil.example/device',
                    expires_in: 900,
                    interval: 5,
                },
            });

        render(<CopilotConnectionPanel active />);
        await screen.findByRole('button', { name: 'model.copilotConnect' });
        fireEvent.click(screen.getByRole('button', { name: 'model.copilotConnect' }));
        await screen.findByText('ABCD-EFGH');

        expect(screen.queryByRole('link')).toBeNull();
    });

    it('checks persisted connection state, retests explicitly, and reports disconnect', async () => {
        const onConnectionChange = vi.fn();
        const onRetest = vi.fn();
        mockApiRequest
            .mockResolvedValueOnce({ data: { connected: true } })
            .mockResolvedValueOnce({ data: { status: 'disconnected' } });

        render(
            <CopilotConnectionPanel
                active
                onConnectionChange={onConnectionChange}
                onRetest={onRetest}
            />,
        );
        await screen.findByText('model.copilotConnected');

        expect(onConnectionChange).toHaveBeenLastCalledWith(true);
        fireEvent.click(screen.getByRole('button', { name: 'model.retest' }));
        expect(onRetest).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByRole('button', { name: 'model.copilotDisconnect' }));
        await act(async () => { await Promise.resolve(); });

        expect(mockApiRequest).toHaveBeenLastCalledWith(
            '/api/copilot/auth/disconnect',
            expect.objectContaining({ method: 'POST', body: '{}' }),
        );
        expect(onConnectionChange).toHaveBeenLastCalledWith(false);
    });
});
