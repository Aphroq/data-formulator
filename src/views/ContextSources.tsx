// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useMemo, useState } from 'react';
import { Box, ButtonBase, Collapse, Typography } from '@mui/material';
import ExpandMoreRoundedIcon from '@mui/icons-material/ExpandMoreRounded';
import LinkRoundedIcon from '@mui/icons-material/LinkRounded';
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded';
import { useTranslation } from 'react-i18next';

import type { ContextItem } from '../components/ComponentType';
import { getOpenableContextUri, normalizeContextItems } from '../app/contextItems';
import { textVar } from '../app/layout';

export interface ContextSourcesProps {
    items?: readonly ContextItem[];
    defaultExpanded?: boolean;
}

/** Compact, defensive renderer shared by interaction entries and TextTurns. */
export const ContextSources: React.FC<ContextSourcesProps> = ({
    items,
    defaultExpanded = false,
}) => {
    const { t } = useTranslation();
    const [expanded, setExpanded] = useState(defaultExpanded);
    const sources = useMemo(() => normalizeContextItems(items), [items]);

    if (sources.length === 0) return null;

    const label = t('contextSources.title', { count: sources.length });
    return (
        <Box
            sx={{ mt: 0.5, minWidth: 0 }}
            onClick={(event) => event.stopPropagation()}
        >
            <ButtonBase
                aria-label={label}
                aria-expanded={expanded}
                onClick={(event) => {
                    event.stopPropagation();
                    setExpanded(value => !value);
                }}
                sx={{
                    display: 'inline-flex', alignItems: 'center', gap: '3px',
                    borderRadius: '4px', px: '2px', py: '1px',
                    color: 'text.secondary',
                    '&:hover': { bgcolor: 'action.hover' },
                }}
            >
                <LinkRoundedIcon sx={{ fontSize: textVar.xs }} />
                <Typography component="span" sx={{ fontSize: textVar.xxs, lineHeight: 1.4 }}>
                    {label}
                </Typography>
                <ExpandMoreRoundedIcon sx={{
                    fontSize: textVar.sm,
                    transform: expanded ? 'rotate(180deg)' : 'none',
                    transition: 'transform 0.15s ease',
                }} />
            </ButtonBase>
            <Collapse in={expanded}>
                <Box component="ul" sx={{ listStyle: 'none', m: 0, mt: '2px', p: 0 }}>
                    {sources.map(source => {
                        const title = source.title || source.uri;
                        const href = getOpenableContextUri(source.uri);
                        const sharedSx = {
                            display: 'flex', alignItems: 'center', gap: '4px',
                            minWidth: 0, py: '1px', px: '2px',
                            borderRadius: '3px',
                            color: 'text.secondary',
                            textDecoration: 'none',
                            ...(href ? { '&:hover': { color: 'primary.main', textDecoration: 'underline' } } : {}),
                        };
                        return (
                            <Box component="li" key={source.uri} sx={{ minWidth: 0 }}>
                                {href ? (
                                    <Box
                                        component="a"
                                        href={href}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        aria-label={t('contextSources.open', { title })}
                                        title={source.uri}
                                        sx={sharedSx}
                                    >
                                        <Typography component="span" noWrap sx={{ fontSize: textVar.xxs, minWidth: 0 }}>
                                            {title}
                                        </Typography>
                                        {source.provider && (
                                            <Typography component="span" noWrap sx={{ fontSize: '9px', color: 'text.disabled' }}>
                                                {source.provider}
                                            </Typography>
                                        )}
                                        <OpenInNewRoundedIcon sx={{ fontSize: '10px', flexShrink: 0 }} />
                                    </Box>
                                ) : (
                                    <Box component="span" title={source.uri} sx={sharedSx}>
                                        <Typography component="span" noWrap sx={{ fontSize: textVar.xxs, minWidth: 0 }}>
                                            {title}
                                        </Typography>
                                        {source.provider && (
                                            <Typography component="span" noWrap sx={{ fontSize: '9px', color: 'text.disabled' }}>
                                                {source.provider}
                                            </Typography>
                                        )}
                                    </Box>
                                )}
                            </Box>
                        );
                    })}
                </Box>
            </Collapse>
        </Box>
    );
};
