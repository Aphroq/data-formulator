// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC } from 'react';
import { Box, IconButton, Tooltip } from '@mui/material';
import AddCircleIcon from '@mui/icons-material/AddCircle';
import AutoModeOutlinedIcon from '@mui/icons-material/AutoModeOutlined';
import FolderOutlinedIcon from '@mui/icons-material/FolderOutlined';
import LightbulbOutlinedIcon from '@mui/icons-material/LightbulbOutlined';
import { Link as RouterLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { RelationalDBIcon } from '../icons';
import { REFERENCE } from '../app/layout';
import { sidebarEdge } from '../app/tokens';


export type WorkspaceNavigationTab = 'sources' | 'sessions' | 'knowledge';


interface WorkspaceNavigationRailProps {
    activeTab?: WorkspaceNavigationTab;
    automationActive?: boolean;
    automationEnabled: boolean;
    panelOpen?: boolean;
    standalone?: boolean;
    onAddData: () => void;
    onSelectTab: (tab: WorkspaceNavigationTab) => void;
}


export const WorkspaceNavigationRail: FC<WorkspaceNavigationRailProps> = ({
    activeTab,
    automationActive = false,
    automationEnabled,
    panelOpen = false,
    standalone = false,
    onAddData,
    onSelectTab,
}) => {
    const { t } = useTranslation();
    const selected = (tab: WorkspaceNavigationTab) => panelOpen && activeTab === tab;
    const itemSx = (isSelected: boolean) => ({
        color: isSelected ? 'primary.main' : 'text.secondary',
        bgcolor: isSelected ? 'action.selected' : 'transparent',
        borderRadius: 1,
        '&:hover': { bgcolor: 'action.hover' },
    });

    return (
        <Box
            component="nav"
            aria-label={t('appBar.primaryNavigation')}
            sx={{
                width: REFERENCE.rail,
                minWidth: REFERENCE.rail,
                height: '100%',
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                pt: 1,
                gap: 0.5,
                bgcolor: 'background.paper',
                ...(standalone ? { borderRight: `1px solid ${sidebarEdge.border}` } : {}),
            }}
        >
            <Tooltip title={t('sidebar.openUpload', { defaultValue: 'Add data' })} placement="right">
                <IconButton
                    size="small"
                    onClick={onAddData}
                    aria-label={t('sidebar.openUpload', { defaultValue: 'Add data' })}
                    sx={{
                        color: 'primary.main',
                        borderRadius: 1,
                        '&:hover': { bgcolor: 'action.hover' },
                    }}
                >
                    <AddCircleIcon fontSize="small" />
                </IconButton>
            </Tooltip>
            <Tooltip title={t('sidebar.sessions', { defaultValue: 'Saved workspaces' })} placement="right">
                <IconButton
                    size="small"
                    onClick={() => onSelectTab('sessions')}
                    aria-label={t('sidebar.sessions', { defaultValue: 'Saved workspaces' })}
                    aria-pressed={selected('sessions')}
                    sx={itemSx(selected('sessions'))}
                >
                    <FolderOutlinedIcon fontSize="small" />
                </IconButton>
            </Tooltip>
            <Tooltip title={t('sidebar.openDataConnectors', { defaultValue: 'Data connectors' })} placement="right">
                <IconButton
                    size="small"
                    onClick={() => onSelectTab('sources')}
                    aria-label={t('sidebar.openDataConnectors', { defaultValue: 'Data connectors' })}
                    aria-pressed={selected('sources')}
                    sx={itemSx(selected('sources'))}
                >
                    <RelationalDBIcon fontSize="small" />
                </IconButton>
            </Tooltip>
            <Tooltip title={t('sidebar.knowledge', { defaultValue: 'Agent knowledge' })} placement="right">
                <IconButton
                    size="small"
                    onClick={() => onSelectTab('knowledge')}
                    aria-label={t('sidebar.knowledge', { defaultValue: 'Agent knowledge' })}
                    aria-pressed={selected('knowledge')}
                    sx={itemSx(selected('knowledge'))}
                >
                    <LightbulbOutlinedIcon fontSize="small" />
                </IconButton>
            </Tooltip>
            {automationEnabled && (
                <Tooltip title={t('appBar.automation')} placement="right">
                    <IconButton
                        component={RouterLink}
                        to="/automation"
                        size="small"
                        aria-label={t('appBar.automation')}
                        aria-current={automationActive ? 'page' : undefined}
                        sx={itemSx(automationActive)}
                    >
                        <AutoModeOutlinedIcon fontSize="small" />
                    </IconButton>
                </Tooltip>
            )}
        </Box>
    );
};
