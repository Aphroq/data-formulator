// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useEffect, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Paper,
    Typography,
} from '@mui/material';
import GitHubIcon from '@mui/icons-material/GitHub';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useTranslation } from 'react-i18next';

import { apiRequest } from '../app/apiClient';
import { getUrls } from '../app/utils';
import { iconVar } from '../app/layout';


interface CopilotStatus {
    connected: boolean;
}

interface DeviceAuthorization {
    status: 'pending';
    authorization_id: string;
    user_code: string;
    verification_uri: string;
    expires_in: number;
    interval: number;
    retryAfter: number;
    pollVersion: number;
}

interface DevicePollResult {
    status: 'pending' | 'connected' | 'denied' | 'expired' | 'cancelled';
    interval?: number;
    retry_after?: number;
}

interface CopilotConnectionPanelProps {
    /** Avoid auth/status traffic while the surrounding model dialog is closed. */
    active: boolean;
    /** Refresh the identity-scoped qualified model list after auth changes. */
    onConnectionChange?: (connected: boolean) => void;
}

const SAFE_VERIFICATION_URI = 'https://github.com/login/device';

const jsonPost = (body: Record<string, unknown> = {}): RequestInit => ({
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
});

const safeErrorMessage = (error: unknown, fallback: string): string => (
    error instanceof Error ? error.message : fallback
);


export const CopilotConnectionPanel: React.FC<CopilotConnectionPanelProps> = ({
    active,
    onConnectionChange,
}) => {
    const { t } = useTranslation();
    const [connected, setConnected] = useState<boolean | null>(null);
    const [pending, setPending] = useState<DeviceAuthorization | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!active) return;
        let cancelled = false;
        apiRequest<CopilotStatus>(getUrls().COPILOT_AUTH_STATUS)
            .then(({ data }) => {
                if (!cancelled) {
                    const isConnected = Boolean(data.connected);
                    setConnected(isConnected);
                    setError(null);
                    onConnectionChange?.(isConnected);
                }
            })
            .catch(requestError => {
                if (!cancelled) {
                    setConnected(false);
                    setError(safeErrorMessage(requestError, t('model.copilotFailed')));
                    onConnectionChange?.(false);
                }
            });
        return () => { cancelled = true; };
    }, [active, onConnectionChange]);

    useEffect(() => {
        if (!active || !pending) return;
        const authorization = pending;
        const delaySeconds = Math.max(1, authorization.retryAfter || authorization.interval || 5);
        let cancelled = false;
        const timer = window.setTimeout(async () => {
            try {
                const { data } = await apiRequest<DevicePollResult>(
                    getUrls().COPILOT_AUTH_POLL,
                    jsonPost({ authorization_id: authorization.authorization_id }),
                );
                if (cancelled) return;
                if (data.status === 'connected') {
                    setConnected(true);
                    setPending(null);
                    setError(null);
                    onConnectionChange?.(true);
                    return;
                }
                if (data.status === 'pending') {
                    setPending(current => current?.authorization_id === authorization.authorization_id
                        ? {
                            ...current,
                            interval: data.interval || current.interval,
                            retryAfter: data.retry_after || data.interval || current.interval,
                            pollVersion: current.pollVersion + 1,
                        }
                        : current);
                    return;
                }
                setPending(null);
                setConnected(false);
                onConnectionChange?.(false);
                setError(t(`model.copilot${data.status[0].toUpperCase()}${data.status.slice(1)}`));
            } catch (requestError) {
                if (!cancelled) setError(safeErrorMessage(requestError, t('model.copilotFailed')));
            }
        }, delaySeconds * 1_000);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [active, pending?.authorization_id, pending?.pollVersion, onConnectionChange, t]);

    const start = async () => {
        setBusy(true);
        setError(null);
        try {
            const { data } = await apiRequest<Omit<DeviceAuthorization, 'retryAfter' | 'pollVersion'>>(
                getUrls().COPILOT_AUTH_START,
                jsonPost(),
            );
            setConnected(false);
            setPending({
                ...data,
                retryAfter: data.interval,
                pollVersion: 0,
            });
        } catch (requestError) {
            setError(safeErrorMessage(requestError, t('model.copilotFailed')));
        } finally {
            setBusy(false);
        }
    };

    const cancel = async () => {
        if (!pending) return;
        setBusy(true);
        setError(null);
        try {
            await apiRequest(
                getUrls().COPILOT_AUTH_CANCEL,
                jsonPost({ authorization_id: pending.authorization_id }),
            );
            setPending(null);
        } catch (requestError) {
            setError(safeErrorMessage(requestError, t('model.copilotFailed')));
        } finally {
            setBusy(false);
        }
    };

    const disconnect = async () => {
        setBusy(true);
        setError(null);
        try {
            await apiRequest(getUrls().COPILOT_AUTH_DISCONNECT, jsonPost());
            setConnected(false);
            setPending(null);
            onConnectionChange?.(false);
        } catch (requestError) {
            setError(safeErrorMessage(requestError, t('model.copilotFailed')));
        } finally {
            setBusy(false);
        }
    };

    const verificationUri = pending?.verification_uri === SAFE_VERIFICATION_URI
        ? SAFE_VERIFICATION_URI
        : undefined;

    return (
        <Paper variant="outlined" sx={{ px: 2, py: 1.5, mb: 2, borderRadius: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2 }}>
                <Box sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle2" sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                        <GitHubIcon fontSize="small" />
                        {t('model.copilotTitle')}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                        {t('model.copilotDescription')}
                    </Typography>
                </Box>
                {connected === null ? (
                    <CircularProgress size={iconVar.sm} aria-label={t('model.copilotChecking')} />
                ) : connected ? (
                    <Button size="small" variant="outlined" disabled={busy} onClick={disconnect}>
                        {t('model.copilotDisconnect')}
                    </Button>
                ) : !pending ? (
                    <Button
                        size="small"
                        variant="outlined"
                        disabled={busy}
                        onClick={start}
                        startIcon={busy ? <CircularProgress size={iconVar.sm} /> : undefined}
                    >
                        {t('model.copilotConnect')}
                    </Button>
                ) : null}
            </Box>

            {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}

            {connected && !pending && (
                <Typography variant="body2" color="success.main" sx={{ mt: 1 }}>
                    {t('model.copilotConnected')}
                </Typography>
            )}

            {pending && (
                <Box sx={{ mt: 1.5, display: 'grid', gap: 1 }}>
                    <Typography variant="body2">{t('model.copilotEnterCode')}</Typography>
                    <Typography
                        component="code"
                        variant="h6"
                        sx={{ letterSpacing: '0.14em', userSelect: 'all' }}
                    >
                        {pending.user_code}
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                        {verificationUri && (
                            <Button
                                component="a"
                                href={verificationUri}
                                target="_blank"
                                rel="noopener noreferrer"
                                size="small"
                                variant="contained"
                                endIcon={<OpenInNewIcon />}
                            >
                                {t('model.copilotOpenGitHub')}
                            </Button>
                        )}
                        <Button size="small" variant="text" disabled={busy} onClick={cancel}>
                            {t('model.copilotCancel')}
                        </Button>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <CircularProgress size={iconVar.xs} />
                            {t('model.copilotWaiting')}
                        </Typography>
                    </Box>
                </Box>
            )}
        </Paper>
    );
};
