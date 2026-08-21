// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useEffect, useState } from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Alert,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    MenuItem,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useTranslation } from 'react-i18next';

import { apiRequest } from '../app/apiClient';
import { getUrls } from '../app/utils';

type RequestState = 'idle' | 'loading' | 'success' | 'error';

interface Connection {
    api_base: string;
    trustgraph_workspace: string;
    flow_id: string;
    tool_group: string;
    has_credential: boolean;
}

interface ConnectionResponse {
    status: 'disabled' | 'configured' | 'unconfigured';
    source?: 'workspace' | 'server';
    connection: Connection | null;
}

interface Props {
    open: boolean;
    workspaceId: string;
    onClose: () => void;
    onStatusChange: (status: 'configured' | 'unconfigured') => void;
}

const defaults = {
    api_base: '',
    trustgraph_workspace: 'default',
    flow_id: 'default',
    tool_group: 'data-formulator-readonly',
    bearer_token: '',
};

export const TrustGraphConnectionDialog: React.FC<Props> = ({
    open,
    workspaceId,
    onClose,
    onStatusChange,
}) => {
    const { t } = useTranslation();
    const [draft, setDraft] = useState(defaults);
    const [source, setSource] = useState<'workspace' | 'server' | null>(null);
    const [hasCredential, setHasCredential] = useState(false);
    const [flows, setFlows] = useState<string[]>([]);
    const [loadState, setLoadState] = useState<RequestState>('idle');
    const [actionState, setActionState] = useState<RequestState>('idle');
    const [message, setMessage] = useState<string | null>(null);

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        setLoadState('loading');
        setActionState('idle');
        setMessage(null);
        setFlows([]);
        apiRequest<ConnectionResponse>(getUrls().BUSINESS_CONTEXT_CONNECTION, {
            headers: { 'X-Workspace-Id': workspaceId },
        }).then(({ data }) => {
            if (cancelled) return;
            const connection = data.connection;
            setDraft(connection ? {
                api_base: connection.api_base,
                trustgraph_workspace: connection.trustgraph_workspace,
                flow_id: connection.flow_id,
                tool_group: connection.tool_group,
                bearer_token: '',
            } : defaults);
            setSource(data.source ?? null);
            setHasCredential(connection?.has_credential === true);
            setLoadState('success');
        }).catch((error: Error) => {
            if (cancelled) return;
            setLoadState('error');
            setMessage(error.message);
        });
        return () => { cancelled = true; };
    }, [open, workspaceId]);

    const setField = (field: keyof typeof draft, value: string) => {
        setDraft((current) => ({ ...current, [field]: value }));
        setActionState('idle');
        setMessage(null);
    };

    const requestBody = () => JSON.stringify(draft);

    const testConnection = async () => {
        setActionState('loading');
        setMessage(null);
        try {
            const { data } = await apiRequest<{ flows: string[] }>(
                getUrls().BUSINESS_CONTEXT_CONNECTION_TEST,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Workspace-Id': workspaceId,
                    },
                    body: requestBody(),
                },
            );
            setFlows(data.flows);
            if (data.flows.length > 0 && !data.flows.includes(draft.flow_id)) {
                setDraft((current) => ({
                    ...current,
                    flow_id: data.flows.includes('default') ? 'default' : data.flows[0],
                }));
            }
            setActionState('success');
            setMessage(t('workspace.trustGraphConnectionSucceeded'));
        } catch (error) {
            setActionState('error');
            setMessage(error instanceof Error ? error.message : t('workspace.trustGraphConnectionFailed'));
        }
    };

    const save = async () => {
        setActionState('loading');
        setMessage(null);
        try {
            await apiRequest<ConnectionResponse>(getUrls().BUSINESS_CONTEXT_CONNECTION, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Workspace-Id': workspaceId,
                },
                body: requestBody(),
            });
            setActionState('success');
            onStatusChange('configured');
            onClose();
        } catch (error) {
            setActionState('error');
            setMessage(error instanceof Error ? error.message : t('workspace.trustGraphSaveFailed'));
        }
    };

    const removeOverride = async () => {
        setActionState('loading');
        setMessage(null);
        try {
            const { data } = await apiRequest<{ status: 'configured' | 'unconfigured' }>(
                getUrls().BUSINESS_CONTEXT_CONNECTION,
                {
                    method: 'DELETE',
                    headers: { 'X-Workspace-Id': workspaceId },
                },
            );
            onStatusChange(data.status);
            onClose();
        } catch (error) {
            setActionState('error');
            setMessage(error instanceof Error ? error.message : t('workspace.trustGraphRemoveFailed'));
        }
    };

    const busy = loadState === 'loading' || actionState === 'loading';
    const flowOptions = flows.length > 0
        ? flows
        : Array.from(new Set([draft.flow_id || 'default']));

    return (
        <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
            <DialogTitle>{t('workspace.trustGraphConnectionTitle')}</DialogTitle>
            <DialogContent>
                <Stack spacing={2} sx={{ pt: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                        {t('workspace.trustGraphConnectionDescription')}
                    </Typography>
                    {source === 'server' && (
                        <Alert severity="info">{t('workspace.trustGraphUsingServerDefault')}</Alert>
                    )}
                    {message && (
                        <Alert severity={actionState === 'success' ? 'success' : 'error'}>{message}</Alert>
                    )}
                    <TextField
                        label={t('workspace.trustGraphApiBase')}
                        value={draft.api_base}
                        onChange={(event) => setField('api_base', event.target.value)}
                        disabled={busy}
                        placeholder="https://trustgraph.example"
                        fullWidth
                    />
                    <TextField
                        label={t('workspace.trustGraphWorkspace')}
                        value={draft.trustgraph_workspace}
                        onChange={(event) => setField('trustgraph_workspace', event.target.value)}
                        disabled={busy}
                        fullWidth
                    />
                    <TextField
                        label={t('workspace.trustGraphReaderKey')}
                        value={draft.bearer_token}
                        onChange={(event) => setField('bearer_token', event.target.value)}
                        disabled={busy}
                        type="password"
                        placeholder={hasCredential ? t('workspace.trustGraphReaderKeyStored') : ''}
                        helperText={t('workspace.trustGraphReaderKeyHint')}
                        autoComplete="new-password"
                        fullWidth
                    />
                    <Stack direction="row" spacing={1} alignItems="center">
                        <Button variant="outlined" onClick={testConnection} disabled={busy || !draft.api_base}>
                            {t('workspace.trustGraphTestAndLoadFlows')}
                        </Button>
                        {flows.length > 0 && (
                            <Typography variant="caption" color="text.secondary">
                                {t('workspace.trustGraphFlowsFound', { count: flows.length })}
                            </Typography>
                        )}
                    </Stack>
                    <TextField
                        select
                        label={t('workspace.trustGraphFlow')}
                        value={draft.flow_id}
                        onChange={(event) => setField('flow_id', event.target.value)}
                        disabled={busy}
                        helperText={t('workspace.trustGraphFlowHint')}
                        fullWidth
                    >
                        {flowOptions.map((flow) => <MenuItem key={flow} value={flow}>{flow}</MenuItem>)}
                    </TextField>
                    <Accordion disableGutters elevation={0} sx={{ border: 1, borderColor: 'divider' }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography>{t('workspace.trustGraphAdvanced')}</Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                            <TextField
                                label={t('workspace.trustGraphToolScope')}
                                value={draft.tool_group}
                                onChange={(event) => setField('tool_group', event.target.value)}
                                disabled={busy}
                                helperText={t('workspace.trustGraphToolScopeHint')}
                                fullWidth
                            />
                        </AccordionDetails>
                    </Accordion>
                </Stack>
            </DialogContent>
            <DialogActions>
                {source === 'workspace' && (
                    <Button color="error" onClick={removeOverride} disabled={busy} sx={{ mr: 'auto' }}>
                        {t('workspace.trustGraphRemoveOverride')}
                    </Button>
                )}
                <Button onClick={onClose} disabled={busy}>{t('workspace.cancel')}</Button>
                <Button variant="contained" onClick={save} disabled={busy || !draft.api_base}>
                    {t('workspace.trustGraphSave')}
                </Button>
            </DialogActions>
        </Dialog>
    );
};
