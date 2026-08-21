// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useEffect, useState } from 'react';
import { Box, IconButton, Tooltip } from '@mui/material';
import HubOutlinedIcon from '@mui/icons-material/HubOutlined';
import { useTranslation } from 'react-i18next';

import { apiRequest } from '../app/apiClient';
import { getUrls } from '../app/utils';
import { TrustGraphConnectionDialog } from './TrustGraphConnectionDialog';

type BusinessContextConfigurationStatus = 'disabled' | 'configured' | 'unconfigured';

interface BusinessContextStatusProps {
    workspaceId: string;
}

export const BusinessContextStatus: React.FC<BusinessContextStatusProps> = ({
    workspaceId,
}) => {
    const { t } = useTranslation();
    const [configurationStatus, setConfigurationStatus] = useState<
        BusinessContextConfigurationStatus | 'unknown' | null
    >(null);
    const [dialogOpen, setDialogOpen] = useState(false);

    useEffect(() => {
        let cancelled = false;
        setConfigurationStatus(null);
        apiRequest<{ status: BusinessContextConfigurationStatus }>(
            getUrls().BUSINESS_CONTEXT_STATUS,
            { headers: { 'X-Workspace-Id': workspaceId } },
        ).then(({ data }) => {
            if (cancelled) return;
            setConfigurationStatus(
                data.status === 'disabled'
                || data.status === 'configured'
                || data.status === 'unconfigured'
                    ? data.status
                    : 'unknown',
            );
        }).catch(() => {
            if (!cancelled) setConfigurationStatus('unknown');
        });
        return () => { cancelled = true; };
    }, [workspaceId]);

    if (configurationStatus === null || configurationStatus === 'disabled') return null;

    const label = configurationStatus === 'configured'
        ? t('workspace.businessKnowledgeConfigured')
        : configurationStatus === 'unconfigured'
            ? t('workspace.businessKnowledgeUnconfigured')
            : t('workspace.businessKnowledgeUnknown');
    const color = configurationStatus === 'configured'
        ? 'success.main'
        : configurationStatus === 'unconfigured'
            ? 'warning.main'
            : 'text.disabled';

    return (<>
        <Tooltip title={`${t('workspace.trustGraphConfigure')} — ${label}`} placement="bottom">
            <IconButton
                size="small"
                aria-label={t('workspace.trustGraphConfigure')}
                onClick={() => setDialogOpen(true)}
                sx={{
                    color,
                    p: 0.5,
                    '&:hover': { color, backgroundColor: 'rgba(0, 0, 0, 0.04)' },
                }}
            >
                <HubOutlinedIcon fontSize="small" />
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
        <TrustGraphConnectionDialog
            open={dialogOpen}
            workspaceId={workspaceId}
            onClose={() => setDialogOpen(false)}
            onStatusChange={setConfigurationStatus}
        />
    </>);
};
