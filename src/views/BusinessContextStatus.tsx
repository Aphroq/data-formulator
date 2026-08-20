// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useEffect, useState } from 'react';
import { Box, Tooltip, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';

import { apiRequest } from '../app/apiClient';
import { getUrls } from '../app/utils';
import { textVar } from '../app/layout';

type BusinessContextReadiness = 'disabled' | 'available' | 'unavailable';

interface BusinessContextStatusProps {
    workspaceId: string;
}

export const BusinessContextStatus: React.FC<BusinessContextStatusProps> = ({
    workspaceId,
}) => {
    const { t } = useTranslation();
    const [readiness, setReadiness] = useState<BusinessContextReadiness | 'unknown' | null>(null);

    useEffect(() => {
        let cancelled = false;
        setReadiness(null);
        apiRequest<{ status: BusinessContextReadiness }>(
            getUrls().BUSINESS_CONTEXT_STATUS,
            { headers: { 'X-Workspace-Id': workspaceId } },
        ).then(({ data }) => {
            if (cancelled) return;
            setReadiness(
                data.status === 'disabled'
                || data.status === 'available'
                || data.status === 'unavailable'
                    ? data.status
                    : 'unknown',
            );
        }).catch(() => {
            if (!cancelled) setReadiness('unknown');
        });
        return () => { cancelled = true; };
    }, [workspaceId]);

    if (readiness === null || readiness === 'disabled') return null;

    const label = readiness === 'available'
        ? t('workspace.businessKnowledgeAvailable')
        : readiness === 'unavailable'
            ? t('workspace.businessKnowledgeUnavailable')
            : t('workspace.businessKnowledgeUnknown');
    const color = readiness === 'available'
        ? 'success.main'
        : readiness === 'unavailable'
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
