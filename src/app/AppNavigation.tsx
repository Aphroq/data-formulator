// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC } from 'react';
import { Box, Button, Stack, Tooltip } from '@mui/material';
import AutoModeOutlinedIcon from '@mui/icons-material/AutoModeOutlined';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import InsightsOutlinedIcon from '@mui/icons-material/InsightsOutlined';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';


interface NavigationItemProps {
    to: string;
    label: string;
    selected: boolean;
    icon: React.ReactNode;
}


const NavigationItem: FC<NavigationItemProps> = ({ to, label, selected, icon }) => (
    <Tooltip title={label} placement="right">
        <Button
            component={RouterLink}
            to={to}
            aria-label={label}
            aria-current={selected ? 'page' : undefined}
            startIcon={icon}
            sx={{
                width: '100%',
                minWidth: 0,
                minHeight: 42,
                px: { xs: 0.75, md: 1.25 },
                justifyContent: { xs: 'center', md: 'flex-start' },
                borderRadius: 1.5,
                textTransform: 'none',
                fontWeight: selected ? 600 : 500,
                color: selected ? 'primary.main' : 'text.secondary',
                bgcolor: selected ? 'action.selected' : 'transparent',
                '&:hover': {
                    color: 'text.primary',
                    bgcolor: selected ? 'action.selected' : 'action.hover',
                },
                '& .MuiButton-startIcon': {
                    m: { xs: 0, md: '0 10px 0 0' },
                },
            }}
        >
            <Box component="span" sx={{ display: { xs: 'none', md: 'inline' } }}>
                {label}
            </Box>
        </Button>
    </Tooltip>
);


export const AppNavigation: FC<{ automationEnabled: boolean }> = ({ automationEnabled }) => {
    const { t } = useTranslation();
    const location = useLocation();
    const automationSelected = location.pathname === '/automation' || location.pathname === '/recipes';
    const aboutSelected = location.pathname === '/about';
    const appSelected = !automationSelected && !aboutSelected;

    return (
        <Box
            component="nav"
            aria-label={t('appBar.primaryNavigation')}
            sx={{
                width: { xs: 56, md: 148 },
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                borderRight: 1,
                borderColor: 'divider',
                bgcolor: 'rgba(255, 255, 255, 0.52)',
                px: { xs: 0.75, md: 1 },
                py: 1,
            }}
        >
            <Stack spacing={0.5}>
                <NavigationItem
                    to="/app"
                    label={t('appBar.app')}
                    selected={appSelected}
                    icon={<InsightsOutlinedIcon fontSize="small" />}
                />
                {automationEnabled && (
                    <NavigationItem
                        to="/automation"
                        label={t('appBar.automation')}
                        selected={automationSelected}
                        icon={<AutoModeOutlinedIcon fontSize="small" />}
                    />
                )}
            </Stack>
            <Box sx={{ flex: 1 }} />
            <NavigationItem
                to="/about"
                label={t('appBar.about')}
                selected={aboutSelected}
                icon={<InfoOutlinedIcon fontSize="small" />}
            />
        </Box>
    );
};
