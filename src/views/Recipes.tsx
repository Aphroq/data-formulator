// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC, useCallback, useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    Chip,
    CircularProgress,
    Divider,
    List,
    ListItemButton,
    ListItemText,
    MenuItem,
    Paper,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import ArchiveOutlinedIcon from '@mui/icons-material/ArchiveOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import PublishOutlinedIcon from '@mui/icons-material/PublishOutlined';
import ScienceOutlinedIcon from '@mui/icons-material/ScienceOutlined';
import { useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { ApiRequestError } from '../app/apiClient';
import type { DataFormulatorState } from '../app/dfSlice';
import {
    archiveRecipe,
    dryRunRecipe,
    getRecipeVersion,
    listRecipes,
    publishRecipe,
    RecipeExecutionResult,
    RecipeParameter,
    RecipeSummary,
    RecipeVersionDetail,
    RecipeVersionStatus,
    runRecipe,
} from '../app/recipeApi';


const statusColor = (status: RecipeVersionStatus) => {
    if (status === 'published') return 'success' as const;
    if (status === 'validated') return 'info' as const;
    if (status === 'archived') return 'default' as const;
    return 'warning' as const;
};

const shortHash = (value: string) => value.includes(':')
    ? value.split(':').at(-1)?.slice(0, 12) ?? value
    : value.slice(0, 12);

const initialParameterValues = (parameters: RecipeParameter[]) => Object.fromEntries(
    parameters.map(parameter => [
        parameter.id,
        parameter.default === undefined ? '' : String(parameter.default),
    ]),
);

function typedParameterValues(
    parameters: RecipeParameter[],
    values: Record<string, string>,
): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const parameter of parameters) {
        const raw = values[parameter.id] ?? '';
        if (raw === '') {
            if (parameter.default !== undefined || !parameter.required) continue;
            throw new TypeError(parameter.name);
        }
        if (parameter.type === 'integer') {
            const parsed = Number(raw);
            if (!Number.isInteger(parsed)) throw new TypeError(parameter.name);
            result[parameter.id] = parsed;
        } else if (parameter.type === 'number') {
            const parsed = Number(raw);
            if (!Number.isFinite(parsed)) throw new TypeError(parameter.name);
            result[parameter.id] = parsed;
        } else if (parameter.type === 'boolean') {
            if (raw !== 'true' && raw !== 'false') throw new TypeError(parameter.name);
            result[parameter.id] = raw === 'true';
        } else {
            if (!raw && parameter.required) throw new TypeError(parameter.name);
            result[parameter.id] = raw;
        }
    }
    return result;
}


export const Recipes: FC = () => {
    const { t } = useTranslation();
    const [searchParams] = useSearchParams();
    const activeWorkspace = useSelector((state: DataFormulatorState) => state.activeWorkspace);
    const enabled = useSelector(
        (state: DataFormulatorState) => state.serverConfig.AUTOMATION_ENABLED,
    );
    const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
    const [selectedVersionId, setSelectedVersionId] = useState<string>('');
    const [detail, setDetail] = useState<RecipeVersionDetail | null>(null);
    const [parameters, setParameters] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [lastRun, setLastRun] = useState<RecipeExecutionResult | null>(null);

    const loadDetail = useCallback(async (versionId: string) => {
        setSelectedVersionId(versionId);
        setDetail(null);
        setError('');
        try {
            const next = await getRecipeVersion(versionId);
            setDetail(next);
            setParameters(initialParameterValues(next.spec.parameters));
        } catch (reason) {
            setError(
                reason instanceof ApiRequestError
                    ? reason.apiError.message
                    : t('recipes.loadFailed'),
            );
        }
    }, [t]);

    const refresh = useCallback(async (preferredVersionId?: string) => {
        if (!activeWorkspace || !enabled) return;
        setLoading(true);
        setError('');
        try {
            const next = await listRecipes();
            setRecipes(next);
            const available = next.flatMap(recipe => recipe.versions.map(version => version.version_id));
            const requested = preferredVersionId || searchParams.get('version') || selectedVersionId;
            const target = requested && available.includes(requested) ? requested : available[0];
            if (target) {
                await loadDetail(target);
            } else {
                setSelectedVersionId('');
                setDetail(null);
            }
        } catch (reason) {
            setError(
                reason instanceof ApiRequestError
                    ? reason.apiError.message
                    : t('recipes.loadFailed'),
            );
        } finally {
            setLoading(false);
        }
    }, [activeWorkspace?.id, enabled, loadDetail, searchParams, selectedVersionId, t]);

    useEffect(() => {
        setRecipes([]);
        setDetail(null);
        setSelectedVersionId('');
        setLastRun(null);
        if (activeWorkspace && enabled) void refresh(searchParams.get('version') || undefined);
        // Reload only when the active Workspace or feature availability changes.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeWorkspace?.id, enabled]);

    const parameterValues = () => {
        if (!detail) return {};
        try {
            return typedParameterValues(detail.spec.parameters, parameters);
        } catch (reason) {
            const name = reason instanceof TypeError ? reason.message : '';
            throw new Error(t('recipes.invalidParameter', { name }));
        }
    };

    const perform = async (action: 'dry-run' | 'publish' | 'run' | 'archive') => {
        if (!detail || busy) return;
        if (action === 'archive' && !window.confirm(t('recipes.archiveConfirm'))) return;
        setBusy(true);
        setError('');
        setNotice('');
        setLastRun(null);
        try {
            let completedNotice = '';
            let completedError = '';
            let completedRun: RecipeExecutionResult | null = null;
            if (action === 'dry-run') {
                const response = await dryRunRecipe(detail.version.version_id, parameterValues());
                completedRun = response.result;
                if (response.result.status !== 'succeeded') {
                    completedError = response.result.error?.message || t('recipes.runFailed');
                } else {
                    completedNotice = t('recipes.dryRunSucceeded');
                }
            } else if (action === 'publish') {
                await publishRecipe(detail.version.version_id);
                completedNotice = t('recipes.publishSucceeded');
            } else if (action === 'run') {
                const result = await runRecipe(detail.version.version_id, parameterValues());
                completedRun = result;
                if (result.status !== 'succeeded') {
                    completedError = result.error?.message || t('recipes.runFailed');
                } else {
                    completedNotice = t('recipes.runSucceeded', { runId: result.run?.run_id });
                }
            } else {
                await archiveRecipe(detail.version.version_id);
                completedNotice = t('recipes.archiveSucceeded');
            }
            await refresh(detail.version.version_id);
            setLastRun(completedRun);
            setError(completedError);
            setNotice(completedNotice);
        } catch (reason) {
            setError(
                reason instanceof ApiRequestError
                    ? reason.apiError.message
                    : reason instanceof Error
                        ? reason.message
                        : t('recipes.actionFailed'),
            );
        } finally {
            setBusy(false);
        }
    };

    const status = detail?.version.status;
    const parameterFields = useMemo(() => detail?.spec.parameters ?? [], [detail]);

    if (!enabled) {
        return (
            <Box sx={{ p: 4 }}>
                <Alert severity="info">{t('recipes.unavailable')}</Alert>
            </Box>
        );
    }
    if (!activeWorkspace) {
        return (
            <Box sx={{ p: 4 }}>
                <Alert severity="info">{t('recipes.openWorkspace')}</Alert>
            </Box>
        );
    }

    return (
        <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', bgcolor: 'background.default', p: { xs: 2, md: 3 } }}>
            <Box sx={{ maxWidth: 1280, mx: 'auto' }}>
                <Typography variant="h4" component="h1" sx={{ fontWeight: 500 }}>
                    {t('recipes.title')}
                </Typography>
                <Typography color="text.secondary" sx={{ mt: 0.5, mb: 3 }}>
                    {t('recipes.subtitle')}
                </Typography>
                {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
                {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
                {lastRun?.status === 'needs_review' && (
                    <Alert severity="warning" sx={{ mb: 2 }}>{t('recipes.needsReview')}</Alert>
                )}
                <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexDirection: { xs: 'column', md: 'row' } }}>
                    <Paper variant="outlined" sx={{ width: { xs: '100%', md: 340 }, flexShrink: 0, overflow: 'hidden' }}>
                        <Box sx={{ px: 2, py: 1.5 }}>
                            <Typography fontWeight={600}>{t('recipes.savedRecipes')}</Typography>
                        </Box>
                        <Divider />
                        {loading && recipes.length === 0 ? (
                            <Box sx={{ p: 4, display: 'flex', justifyContent: 'center' }}><CircularProgress size={24} /></Box>
                        ) : recipes.length === 0 ? (
                            <Typography color="text.secondary" sx={{ p: 2 }}>{t('recipes.empty')}</Typography>
                        ) : (
                            <List disablePadding>
                                {recipes.flatMap(recipe => recipe.versions.map((version, index) => (
                                    <ListItemButton
                                        key={version.version_id}
                                        selected={selectedVersionId === version.version_id}
                                        onClick={() => void loadDetail(version.version_id)}
                                        divider
                                        alignItems="flex-start"
                                    >
                                        <ListItemText
                                            primary={recipe.name}
                                            secondary={
                                                <Stack component="span" direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
                                                    <Chip size="small" label={t(`recipes.status.${version.status}`)} color={statusColor(version.status)} />
                                                    <Typography component="span" variant="caption" color="text.secondary">
                                                        {t('recipes.versionNumber', { number: recipe.versions.length - index })}
                                                    </Typography>
                                                </Stack>
                                            }
                                        />
                                    </ListItemButton>
                                )))}
                            </List>
                        )}
                    </Paper>

                    <Paper variant="outlined" sx={{ flex: 1, minWidth: 0, width: '100%', p: { xs: 2, md: 3 } }}>
                        {!detail ? (
                            <Box sx={{ minHeight: 240, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                {loading ? <CircularProgress size={28} /> : <Typography color="text.secondary">{t('recipes.selectVersion')}</Typography>}
                            </Box>
                        ) : (
                            <Stack spacing={3}>
                                <Box>
                                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'flex-start', sm: 'center' }}>
                                        <Typography variant="h5" component="h2" sx={{ fontWeight: 500, flex: 1 }}>
                                            {detail.recipe.name}
                                        </Typography>
                                        <Chip label={t(`recipes.status.${detail.version.status}`)} color={statusColor(detail.version.status)} />
                                    </Stack>
                                    {detail.recipe.description && (
                                        <Typography color="text.secondary" sx={{ mt: 1 }}>{detail.recipe.description}</Typography>
                                    )}
                                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, fontFamily: 'monospace' }}>
                                        {t('recipes.hash')}: {shortHash(detail.version.recipe_hash)}
                                    </Typography>
                                </Box>

                                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                    {status === 'draft' && (
                                        <Button variant="contained" startIcon={<ScienceOutlinedIcon />} disabled={busy} onClick={() => void perform('dry-run')}>
                                            {t('recipes.dryRun')}
                                        </Button>
                                    )}
                                    {status === 'validated' && (
                                        <Button variant="contained" startIcon={<PublishOutlinedIcon />} disabled={busy} onClick={() => void perform('publish')}>
                                            {t('recipes.publish')}
                                        </Button>
                                    )}
                                    {status === 'published' && (
                                        <>
                                            <Button variant="contained" startIcon={<PlayArrowOutlinedIcon />} disabled={busy} onClick={() => void perform('run')}>
                                                {t('recipes.runNow')}
                                            </Button>
                                            <Button color="inherit" startIcon={<ArchiveOutlinedIcon />} disabled={busy} onClick={() => void perform('archive')}>
                                                {t('recipes.archive')}
                                            </Button>
                                        </>
                                    )}
                                    {busy && <CircularProgress size={24} sx={{ alignSelf: 'center' }} />}
                                </Stack>

                                <Divider />
                                <Box>
                                    <Typography variant="h6" component="h3" sx={{ mb: 1.5 }}>{t('recipes.parameters')}</Typography>
                                    {parameterFields.length === 0 ? (
                                        <Typography color="text.secondary">{t('recipes.noParameters')}</Typography>
                                    ) : (
                                        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
                                            {parameterFields.map(parameter => (
                                                <TextField
                                                    key={parameter.id}
                                                    select={parameter.type === 'boolean'}
                                                    type={parameter.type === 'date' ? 'date' : parameter.type === 'integer' || parameter.type === 'number' ? 'number' : 'text'}
                                                    required={parameter.required}
                                                    label={parameter.name}
                                                    value={parameters[parameter.id] ?? ''}
                                                    onChange={event => setParameters(current => ({ ...current, [parameter.id]: event.target.value }))}
                                                    slotProps={{ inputLabel: parameter.type === 'date' ? { shrink: true } : undefined }}
                                                >
                                                    {parameter.type === 'boolean' ? [
                                                        <MenuItem key="true" value="true">{t('recipes.true')}</MenuItem>,
                                                        <MenuItem key="false" value="false">{t('recipes.false')}</MenuItem>,
                                                    ] : undefined}
                                                </TextField>
                                            ))}
                                        </Box>
                                    )}
                                </Box>

                                <Box>
                                    <Typography variant="h6" component="h3" sx={{ mb: 1.5 }}>{t('recipes.inputs')}</Typography>
                                    <Stack spacing={1}>
                                        {detail.spec.inputs.map(input => (
                                            <Card key={input.id} variant="outlined" sx={{ p: 1.5 }}>
                                                <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                                    <Chip size="small" label={t(`recipes.inputMode.${input.mode}`)} />
                                                    <Typography fontWeight={500}>{input.source_id || t('recipes.localInput')}</Typography>
                                                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                                                        schema {shortHash(input.expected_schema)}
                                                    </Typography>
                                                </Stack>
                                            </Card>
                                        ))}
                                    </Stack>
                                </Box>

                                <Box>
                                    <Typography variant="h6" component="h3" sx={{ mb: 1.5 }}>{t('recipes.steps')}</Typography>
                                    <Stack spacing={1}>
                                        {detail.spec.steps.map((step, index) => (
                                            <Card key={step.id} variant="outlined" sx={{ p: 1.5 }}>
                                                <Stack direction="row" spacing={1.5} alignItems="center">
                                                    <Chip size="small" color="primary" variant="outlined" label={index + 1} />
                                                    <Box sx={{ minWidth: 0 }}>
                                                        <Typography fontWeight={500}>{t(`recipes.stepKind.${step.kind}`)}</Typography>
                                                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                                                            {shortHash(step.artifact_id)}
                                                        </Typography>
                                                    </Box>
                                                </Stack>
                                            </Card>
                                        ))}
                                    </Stack>
                                </Box>
                            </Stack>
                        )}
                    </Paper>
                </Box>
            </Box>
        </Box>
    );
};
