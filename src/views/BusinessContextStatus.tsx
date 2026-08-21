// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useEffect, useState } from 'react';
import { Box, Tooltip, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';

import { apiRequest } from '../app/apiClient';
import { getUrls } from '../app/utils';
import { textVar } from '../app/layout';

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

    return (
        <Tooltip title={label} placement="bottom">
            <Box
                component="span"
                role="status"
                aria-label={label}
                sx={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 0.5,
                    ml: 0.5,
                    color,
                    whiteSpace: 'nowrap',
                }}
            >
                <Box
                    component="span"
                    sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'currentColor' }}
                />
                <Typography component="span" sx={{ fontSize: textVar.xxs, color: 'inherit' }}>
                    {label}
                </Typography>
            </Box>
        </Tooltip>
    );
};
