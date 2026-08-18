// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    Chip,
    CircularProgress,
    Divider,
    FormControl,
    InputLabel,
    List,
    ListItemButton,
    ListItemText,
    MenuItem,
    NativeSelect,
    Paper,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import ArchiveOutlinedIcon from '@mui/icons-material/ArchiveOutlined';
import AutoModeOutlinedIcon from '@mui/icons-material/AutoModeOutlined';
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined';
import PublishOutlinedIcon from '@mui/icons-material/PublishOutlined';
import ScienceOutlinedIcon from '@mui/icons-material/ScienceOutlined';
import { useSelector } from 'react-redux';
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
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

const executionStatusColor = (status: RecipeExecutionResult['status']) => {
    if (status === 'succeeded') return 'success' as const;
    if (status === 'needs_review') return 'warning' as const;
    return 'error' as const;
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


const RunResultPanel: FC<{
    result: RecipeExecutionResult;
    finalOutputStepIds: string[];
}> = ({ result, finalOutputStepIds }) => {
    const { t } = useTranslation();
    const totalDuration = result.steps.reduce((total, step) => total + step.duration_ms, 0);
    const finalOutputs = new Set(finalOutputStepIds);

    return (
        <Card
            component="section"
            aria-label={t('automation.runResult.title')}
            variant="outlined"
            sx={{ p: 2, bgcolor: 'action.hover' }}
        >
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'flex-start', sm: 'center' }}>
                <Typography variant="h6" component="h3" sx={{ flex: 1 }}>
                    {t('automation.runResult.title')}
                </Typography>
                <Chip
                    size="small"
                    color={executionStatusColor(result.status)}
                    label={t(`automation.runResult.status.${result.status}`)}
                />
            </Stack>

            <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                {result.run && (
                    <>
                        <Typography variant="caption" color="text.secondary">
                            {t(`automation.runResult.kind.${result.run.kind}`)}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                            {t('automation.runResult.runId')}: {result.run.run_id}
                        </Typography>
                    </>
                )}
                <Typography variant="caption" color="text.secondary">
                    {t('automation.runResult.summary', {
                        count: result.steps.length,
                        duration: totalDuration,
                    })}
                </Typography>
            </Stack>

            {result.error && (
                <Alert severity={result.status === 'needs_review' ? 'warning' : 'error'} sx={{ mt: 1.5 }}>
                    <Typography variant="body2" fontWeight={600}>{result.error.code}</Typography>
                    <Typography variant="body2">{result.error.message}</Typography>
                </Alert>
            )}

            <Divider sx={{ my: 1.5 }} />
            <Typography variant="subtitle2" sx={{ mb: 1 }}>{t('automation.runResult.steps')}</Typography>
            {result.steps.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                    {t('automation.runResult.noSteps')}
                </Typography>
            ) : (
                <Stack spacing={1}>
                    {result.steps.map((step, index) => (
                        <Box key={`${step.step_id}-${index}`} sx={{ p: 1.25, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper' }}>
                            <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                <Chip size="small" variant="outlined" label={index + 1} />
                                <Typography variant="body2" fontWeight={600}>
                                    {t(`recipes.stepKind.${step.kind}`)}
                                </Typography>
                                {finalOutputs.has(step.step_id) && (
                                    <Chip size="small" color="primary" variant="outlined" label={t('automation.runResult.finalOutput')} />
                                )}
                                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                                    {t('automation.runResult.duration', { duration: step.duration_ms })}
                                </Typography>
                            </Stack>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75, fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                {t('automation.runResult.outputPath')}: {step.output_path}
                            </Typography>
                            <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
                                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                                    {t('automation.runResult.contentHash')} {shortHash(step.content_hash)}
                                </Typography>
                                <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                                    {t('automation.runResult.schemaHash')} {shortHash(step.schema_hash)}
                                </Typography>
                            </Stack>
                        </Box>
                    ))}
                </Stack>
            )}
        </Card>
    );
};

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
            if (!Number.isSafeInteger(parsed)) throw new TypeError(parameter.name);
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


export const Automation: FC = () => {
    const { t } = useTranslation();
    const [searchParams, setSearchParams] = useSearchParams();
    const requestedVersionId = searchParams.get('version') ?? '';
    const activeWorkspace = useSelector((state: DataFormulatorState) => state.activeWorkspace);
    const enabled = useSelector(
        (state: DataFormulatorState) => state.serverConfig.AUTOMATION_ENABLED,
    );
    const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
    const [selectedRecipeId, setSelectedRecipeId] = useState<string>('');
    const [selectedVersionId, setSelectedVersionId] = useState<string>('');
    const [detail, setDetail] = useState<RecipeVersionDetail | null>(null);
    const [parameters, setParameters] = useState<Record<string, string>>({});
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [warning, setWarning] = useState('');
    const [lastRun, setLastRun] = useState<RecipeExecutionResult | null>(null);
    const requestSequence = useRef(0);
    const translation = useRef(t);
    translation.current = t;

    const loadDetail = useCallback(async (
        versionId: string,
        sequence: number,
        clearDetail: boolean,
    ): Promise<{ applied: boolean; error?: string }> => {
        if (requestSequence.current !== sequence) return { applied: false };
        setSelectedVersionId(versionId);
        setDetail(null);
        setLastRun(null);
        setError('');
        try {
            const next = await getRecipeVersion(versionId);
            setSelectedRecipeId(next.recipe.recipe_id);
            setDetail(next);
            setParameters(initialParameterValues(next.spec.parameters));
            return { applied: true };
        } catch (reason) {
            if (requestSequence.current !== sequence) return { applied: false };
            return {
                applied: true,
                error: reason instanceof ApiRequestError
                    ? reason.apiError.message
                    : translation.current('recipes.loadFailed'),
            };
        }
    }, []);

    const refresh = useCallback(async (
        preferredVersionId?: string,
        options: { surfaceError?: boolean; preserveDetail?: boolean } = {},
    ): Promise<{ applied: boolean; error?: string }> => {
        if (!activeWorkspace || !enabled) return { applied: false };
        const sequence = ++requestSequence.current;
        const surfaceError = options.surfaceError ?? true;
        setLoading(true);
        if (surfaceError) setError('');
        try {
            const next = await listRecipes();
            if (requestSequence.current !== sequence) return { applied: false };
            setRecipes(next);
            const available = next.flatMap(recipe => recipe.versions.map(version => version.version_id));
            const target = preferredVersionId && available.includes(preferredVersionId)
                ? preferredVersionId
                : available[0];
            if (target) {
                const outcome = await loadDetail(target, sequence, !options.preserveDetail);
                if (outcome.error && surfaceError) setError(outcome.error);
                return outcome;
            } else {
                setSelectedVersionId('');
                setDetail(null);
                return { applied: true };
            }
        } catch (reason) {
            if (requestSequence.current !== sequence) return { applied: false };
            const message = reason instanceof ApiRequestError
                ? reason.apiError.message
                : translation.current('recipes.loadFailed');
            if (surfaceError) setError(message);
            return { applied: true, error: message };
        } finally {
            if (requestSequence.current === sequence) setLoading(false);
        }
    }, [activeWorkspace?.id, enabled, loadDetail]);

    useEffect(() => {
        requestSequence.current += 1;
        setRecipes([]);
        setDetail(null);
        setSelectedRecipeId('');
        setSelectedVersionId('');
        setParameters({});
        setBusy(false);
        setError('');
        setNotice('');
        setLastRun(null);
        setWarning('');
        if (activeWorkspace && enabled) void refresh(requestedVersionId || undefined);
        return () => {
            requestSequence.current += 1;
        };
    }, [activeWorkspace?.id, enabled, refresh, requestedVersionId]);

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
        const actionSequence = requestSequence.current;
        const versionId = detail.version.version_id;
        setBusy(true);
        setError('');
        setNotice('');
        setWarning('');
        setLastRun(null);
        try {
            let completedNotice = '';
            let completedRun: RecipeExecutionResult | null = null;
            let completedVersion: RecipeVersionDetail['version'] | null = null;
            if (action === 'dry-run') {
                const response = await dryRunRecipe(versionId, parameterValues());
                completedRun = response.result;
                if (response.result.status === 'succeeded') {
                    completedNotice = t('recipes.dryRunSucceeded');
                }
            } else if (action === 'publish') {
                completedVersion = await publishRecipe(versionId);
                completedNotice = t('recipes.publishSucceeded');
            } else if (action === 'run') {
                const result = await runRecipe(versionId, parameterValues());
                completedRun = result;
                if (result.status === 'succeeded') {
                    completedNotice = t('recipes.runSucceeded', { runId: result.run?.run_id });
                }
            } else {
                completedVersion = await archiveRecipe(versionId);
                completedNotice = t('recipes.archiveSucceeded');
            }
            if (requestSequence.current !== actionSequence) return;
            if (completedVersion) {
                setDetail(current => current?.version.version_id === versionId
                    ? { ...current, version: completedVersion }
                    : current);
            }
            setLastRun(completedRun);
            setNotice(completedNotice);
            const refreshOutcome = await refresh(versionId, {
                surfaceError: false,
                preserveDetail: true,
            });
            if (refreshOutcome.applied && refreshOutcome.error) {
                setWarning(t('recipes.refreshAfterActionFailed'));
            }
        } catch (reason) {
            if (requestSequence.current !== actionSequence) return;
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
    const selectedRecipe = useMemo(
        () => recipes.find(recipe => recipe.recipe_id === selectedRecipeId) ?? null,
        [recipes, selectedRecipeId],
    );

    if (!enabled) {
        return (
            <Box sx={{ p: 4 }}>
                <Alert severity="info">{t('automation.unavailable')}</Alert>
            </Box>
        );
    }
    if (!activeWorkspace) {
        return (
            <Box sx={{ p: 4 }}>
                <Alert severity="info">{t('automation.openWorkspace')}</Alert>
            </Box>
        );
    }

    return (
        <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', bgcolor: 'background.default', p: { xs: 2, md: 3 } }}>
            <Box sx={{ maxWidth: 1280, mx: 'auto' }}>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }} sx={{ mb: 3 }}>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h4" component="h1" sx={{ fontWeight: 500 }}>
                            {t('automation.title')}
                        </Typography>
                        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                            {t('automation.subtitle')}
                        </Typography>
                    </Box>
                    <Button component={RouterLink} to="/app" variant="outlined">
                        {t('automation.openApp')}
                    </Button>
                </Stack>
                {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
                {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
                {loading && recipes.length === 0 ? (
                    <Paper variant="outlined" sx={{ minHeight: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <CircularProgress size={28} />
                    </Paper>
                ) : recipes.length === 0 ? (
                    <Paper variant="outlined" sx={{ minHeight: 280, px: 3, py: 6, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
                        <AutoModeOutlinedIcon color="disabled" sx={{ fontSize: 36, mb: 1.5 }} />
                        <Typography variant="h6" fontWeight={600}>{t('automation.emptyTitle')}</Typography>
                        <Typography color="text.secondary" sx={{ mt: 0.75, maxWidth: 520 }}>
                            {t('automation.emptyDescription')}
                        </Typography>
                    </Paper>
                ) : (
                <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexDirection: { xs: 'column', md: 'row' } }}>
                    <Paper variant="outlined" sx={{ width: { xs: '100%', md: 340 }, flexShrink: 0, overflow: 'hidden' }}>
                        <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography fontWeight={600} sx={{ flex: 1 }}>{t('automation.projects')}</Typography>
                            <Chip size="small" label={recipes.length} />
                        </Box>
                        <Divider />
                        <List disablePadding aria-label={t('automation.projects')}>
                                {recipes.map(recipe => {
                                    const latestVersion = recipe.versions[0];
                                    if (!latestVersion) return null;
                                    return (
                                        <ListItemButton
                                            key={recipe.recipe_id}
                                            selected={selectedRecipeId === recipe.recipe_id}
                                            onClick={() => void loadDetail(latestVersion.version_id)}
                                            divider
                                            alignItems="flex-start"
                                        >
                                            <ListItemText
                                                primary={recipe.name}
                                                secondary={
                                                    <Box component="span" sx={{ display: 'block', mt: 0.75 }}>
                                                        <Stack component="span" direction="row" spacing={1} alignItems="center">
                                                            <Chip size="small" label={t(`recipes.status.${latestVersion.status}`)} color={statusColor(latestVersion.status)} />
                                                            <Typography component="span" variant="caption" color="text.secondary">
                                                                {t('automation.versionsCount', { count: recipe.versions.length })}
                                                            </Typography>
                                                        </Stack>
                                                        <Typography component="span" variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
                                                            {t('automation.updated', { date: new Date(recipe.updated_at).toLocaleDateString() })}
                                                        </Typography>
                                                    </Box>
                                                }
                                            />
                                        </ListItemButton>
                                    );
                                })}
                        </List>
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
                                            {detail.spec.name}
                                        </Typography>
                                        <FormControl variant="standard" size="small" sx={{ minWidth: 150 }}>
                                            <InputLabel htmlFor="automation-version-picker">{t('automation.versionPicker')}</InputLabel>
                                            <NativeSelect
                                                value={selectedVersionId}
                                                onChange={event => void loadDetail(event.target.value)}
                                                inputProps={{
                                                    id: 'automation-version-picker',
                                                    'aria-label': t('automation.versionPicker'),
                                                }}
                                            >
                                                {selectedRecipe?.versions.map((version, index) => (
                                                    <option key={version.version_id} value={version.version_id}>
                                                        {t('automation.versionOption', {
                                                            number: selectedRecipe.versions.length - index,
                                                            status: t(`recipes.status.${version.status}`),
                                                        })}
                                                    </option>
                                                ))}
                                            </NativeSelect>
                                        </FormControl>
                                        <Chip label={t(`recipes.status.${detail.version.status}`)} color={statusColor(detail.version.status)} />
                                    </Stack>
                                    {detail.spec.description && (
                                        <Typography color="text.secondary" sx={{ mt: 1 }}>{detail.spec.description}</Typography>
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

                                {lastRun && (
                                    <RunResultPanel
                                        result={lastRun}
                                        finalOutputStepIds={detail.spec.final_outputs.map(output => output.step_id)}
                                    />
                                )}

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
                )}
            </Box>
        </Box>
    );
};


// Keep the exported name for downstream imports while /recipes remains a legacy URL.
export const Recipes = Automation;
