// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useCallback, useEffect, useState } from 'react';
import {
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    IconButton,
    Tooltip,
} from '@mui/material';
import GitHubIcon from '@mui/icons-material/GitHub';
import { useTranslation } from 'react-i18next';

import { apiRequest } from '../app/apiClient';
import { getUrls } from '../app/utils';
import { CopilotConnectionPanel } from './CopilotConnectionPanel';

interface CopilotConnectionStatusProps {
    enabled: boolean;
    onConnectionChange?: (connected: boolean) => void;
}

export const CopilotConnectionStatus: React.FC<CopilotConnectionStatusProps> = ({
    enabled,
    onConnectionChange,
}) => {
    const { t } = useTranslation();
    const [connected, setConnected] = useState<boolean | null>(null);
    const [dialogOpen, setDialogOpen] = useState(false);
    const handleConnectionChange = useCallback((nextConnected: boolean) => {
        setConnected(nextConnected);
        onConnectionChange?.(nextConnected);
    }, [onConnectionChange]);

    useEffect(() => {
        if (!enabled) return;
        let cancelled = false;
        setConnected(null);
        apiRequest<{ connected: boolean }>(getUrls().COPILOT_AUTH_STATUS)
            .then(({ data }) => {
                if (!cancelled) setConnected(Boolean(data.connected));
            })
            .catch(() => {
                if (!cancelled) setConnected(false);
            });
        return () => { cancelled = true; };
    }, [enabled]);

    if (!enabled) return null;

    const label = connected
        ? t('model.copilotStatusConnected')
        : connected === false
            ? t('model.copilotStatusDisconnected')
            : t('model.copilotChecking');
    const color = connected ? 'success.main' : connected === false ? 'warning.main' : 'text.disabled';

    return (<>
        <Tooltip title={`${t('model.copilotManage')} — ${label}`} placement="bottom">
            <IconButton
                size="small"
                aria-label={t('model.copilotManage')}
                onClick={() => setDialogOpen(true)}
                sx={{
                    color,
                    p: 0.5,
                    '&:hover': { color, backgroundColor: 'rgba(0, 0, 0, 0.04)' },
                }}
            >
                <GitHubIcon fontSize="small" />
                <Box
                    component="span"
                    role="status"
                    aria-label={label}
                    sx={{
                        position: 'absolute',
                        width: 1,
                        height: 1,
                        p: 0,
                        m: -1,
                        overflow: 'hidden',
                        clip: 'rect(0, 0, 0, 0)',
                        whiteSpace: 'nowrap',
                        border: 0,
                    }}
                />
            </IconButton>
        </Tooltip>
        <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} fullWidth maxWidth="sm">
            <DialogTitle>{t('model.copilotManage')}</DialogTitle>
            <DialogContent>
                <CopilotConnectionPanel
                    active={dialogOpen}
                    onConnectionChange={handleConnectionChange}
                />
            </DialogContent>
            <DialogActions>
                <Button onClick={() => setDialogOpen(false)}>{t('app.close')}</Button>
            </DialogActions>
        </Dialog>
    </>);
};
