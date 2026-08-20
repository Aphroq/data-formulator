// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC, useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import {
    Alert,
    Box,
    Button,
    Checkbox,
    CircularProgress,
    Collapse,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    IconButton,
    FormControlLabel,
    Stack,
    Switch,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import SaveAsOutlinedIcon from '@mui/icons-material/SaveAsOutlined';
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { ApiRequestError } from '../app/apiClient';
import {
    compileRecipe,
    listRecipeParameterCandidates,
    RecipeParameterCandidate,
    RecipeParameterConfiguration,
    suggestRecipeParameterConfigurations,
} from '../app/recipeApi';
import {
    DataFormulatorState,
    dfSelectors,
    type ModelConfig,
} from '../app/dfSlice';
import { floatingPillSx } from '../app/tokens';
import { iconVar } from '../app/layout';
import {
    Chart,
    computeRecipeArtifactFingerprint,
} from '../components/ComponentType';
import { buildSessionWorkflowContext } from './SessionDistill';
import { buildDistillModelConfig, buildLeafEvents } from './workflowContext';


export const isChartRecipeArtifactCurrent = (chart: Chart): boolean => Boolean(
    chart.recipeArtifactId
    && chart.recipeArtifactFingerprint
    && chart.recipeArtifactFingerprint === computeRecipeArtifactFingerprint(chart)
);

interface RecipeParameterDraft extends RecipeParameterConfiguration {
    selected: boolean;
}

export interface RecipeParameterAiContext {
    model: Record<string, unknown>;
    workflowContext?: Record<string, unknown>;
    timeoutSeconds?: number;
}


export const SaveAsRecipeDialog: FC<{
    chart: Chart;
    open: boolean;
    onClose: () => void;
    aiContext?: RecipeParameterAiContext;
}> = ({ chart, open, onClose, aiContext }) => {
    const { t } = useTranslation();
    const translation = useRef(t);
    translation.current = t;
    const navigate = useNavigate();
    const defaultName = useMemo(
        () => chart.title?.trim() || t('recipes.defaultName'),
        [chart.id, chart.title, t],
    );
    const [name, setName] = useState(defaultName);
    const [description, setDescription] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [candidates, setCandidates] = useState<RecipeParameterCandidate[]>([]);
    const [parameterDrafts, setParameterDrafts] = useState<Record<string, RecipeParameterDraft>>({});
    const [loadingCandidates, setLoadingCandidates] = useState(false);
    const [organizing, setOrganizing] = useState(false);
    const [suggestionMessage, setSuggestionMessage] = useState('');
    const [suggestionError, setSuggestionError] = useState('');
    const [unmatchedSuggestions, setUnmatchedSuggestions] = useState<string[]>([]);
    const [showOtherCandidates, setShowOtherCandidates] = useState(false);

    useEffect(() => {
        if (!open) return;
        setName(defaultName);
        setDescription('');
        setError('');
        setSaving(false);
        setCandidates([]);
        setParameterDrafts({});
        setOrganizing(false);
        setSuggestionMessage('');
        setSuggestionError('');
        setUnmatchedSuggestions([]);
        setShowOtherCandidates(false);
        if (!chart.recipeArtifactId || !isChartRecipeArtifactCurrent(chart)) return;
        let cancelled = false;
        setLoadingCandidates(true);
        void listRecipeParameterCandidates([chart.recipeArtifactId])
            .then(next => {
                if (cancelled) return;
                setCandidates(next);
                setParameterDrafts(Object.fromEntries(next.map(item => [
                    item.candidate_id,
                    {
                        candidate_id: item.candidate_id,
                        selected: false,
                        name: item.name,
                        description: item.description ?? '',
                        mode: 'keep',
                    },
                ])));
            })
            .catch(reason => {
                if (cancelled) return;
                setError(
                    reason instanceof ApiRequestError
                        ? reason.apiError.message
                        : translation.current('recipes.parameterCandidatesFailed'),
                );
            })
            .finally(() => {
                if (!cancelled) setLoadingCandidates(false);
            });
        return () => {
            cancelled = true;
        };
    }, [chart.recipeArtifactId, defaultName, open]);

    const organizeParameters = async () => {
        if (
            !aiContext
            || !chart.recipeArtifactId
            || !isChartRecipeArtifactCurrent(chart)
        ) return;
        setOrganizing(true);
        setSuggestionError('');
        setSuggestionMessage('');
        setUnmatchedSuggestions([]);
        try {
            const result = await suggestRecipeParameterConfigurations({
                targetArtifactIds: [chart.recipeArtifactId],
                model: aiContext.model,
                workflowContext: aiContext.workflowContext,
                name: name.trim(),
                description: description.trim(),
                timeoutSeconds: aiContext.timeoutSeconds,
            });
            setParameterDrafts(current => {
                const next: Record<string, RecipeParameterDraft> = Object.fromEntries(
                    Object.entries(current).map(
                        ([candidateId, draft]) => [candidateId, { ...draft, selected: false }],
                    ),
                );
                for (const suggestion of result.suggestions) {
                    if (!next[suggestion.candidate_id]) continue;
                    next[suggestion.candidate_id] = { ...suggestion, selected: true };
                }
                return next;
            });
            setUnmatchedSuggestions(result.unmatched);
            setSuggestionMessage(
                result.suggestions.length > 0
                    ? t('recipes.aiParameterSuggestionsApplied', {
                        count: result.suggestions.length,
                    })
                    : result.unmatched.length === 0
                        ? t('recipes.aiParameterNoMatches')
                        : '',
            );
            setShowOtherCandidates(result.suggestions.length === 0);
        } catch (reason) {
            setSuggestionError(
                reason instanceof ApiRequestError
                    ? reason.apiError.message
                    : t('recipes.aiParameterSuggestionsFailed'),
            );
        } finally {
            setOrganizing(false);
        }
    };

    const save = async () => {
        if (!chart.recipeArtifactId || !isChartRecipeArtifactCurrent(chart)) {
            setError(t('recipes.artifactStale'));
            return;
        }
        setSaving(true);
        setError('');
        try {
            const parameterConfigurations = candidates.flatMap(candidate => {
                const draft = parameterDrafts[candidate.candidate_id];
                if (!draft?.selected) return [];
                return [{
                    candidate_id: candidate.candidate_id,
                    name: draft.name,
                    description: draft.description,
                    mode: draft.mode,
                } satisfies RecipeParameterConfiguration];
            });
            const saved = await compileRecipe({
                targetArtifactIds: [chart.recipeArtifactId],
                name: name.trim(),
                description: description.trim(),
                parameterConfigurations,
            });
            onClose();
            navigate(`/automation?version=${encodeURIComponent(saved.version.version_id)}`);
        } catch (reason) {
            setError(
                reason instanceof ApiRequestError
                    ? reason.apiError.message
                    : t('recipes.saveFailed'),
            );
        } finally {
            setSaving(false);
        }
    };

    const selectedCandidates = candidates.filter(candidate => (
        parameterDrafts[candidate.candidate_id]?.selected
    ));
    const otherCandidates = candidates.filter(candidate => (
        !parameterDrafts[candidate.candidate_id]?.selected
    ));
    const renderCandidate = (candidate: RecipeParameterCandidate) => {
        const draft = parameterDrafts[candidate.candidate_id] ?? {
            candidate_id: candidate.candidate_id,
            selected: false,
            name: candidate.name,
            description: candidate.description ?? '',
            mode: 'keep' as const,
        };
        return (
            <Box
                key={candidate.candidate_id}
                sx={{
                    border: 1,
                    borderColor: draft.selected ? 'primary.light' : 'divider',
                    borderRadius: 1.5,
                    px: 1.25,
                    py: 1,
                    bgcolor: draft.selected ? 'action.hover' : 'transparent',
                }}
            >
                <Stack direction="row" spacing={1} alignItems="flex-start">
                    <Checkbox
                        size="small"
                        checked={draft.selected}
                        inputProps={{ 'aria-label': draft.name }}
                        onChange={event => setParameterDrafts(current => ({
                            ...current,
                            [candidate.candidate_id]: {
                                ...draft,
                                selected: event.target.checked,
                            },
                        }))}
                        sx={{ mt: -0.5, ml: -0.5 }}
                    />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="body2" fontWeight={600}>
                            {draft.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            {t(`recipes.parameterCandidateKind.${candidate.kind}`)} · {t('recipes.currentValue', {
                                value: String(candidate.default),
                            })}
                        </Typography>
                        {draft.description && (
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                                {draft.description}
                            </Typography>
                        )}
                        {draft.selected && (
                            <FormControlLabel
                                sx={{ mt: 0.5, ml: 0 }}
                                control={(
                                    <Switch
                                        size="small"
                                        checked={draft.mode === 'ask'}
                                        onChange={event => setParameterDrafts(current => ({
                                            ...current,
                                            [candidate.candidate_id]: {
                                                ...draft,
                                                mode: event.target.checked ? 'ask' : 'keep',
                                            },
                                        }))}
                                    />
                                )}
                                label={(
                                    <Typography variant="caption" color="text.secondary">
                                        {t(draft.mode === 'ask'
                                            ? 'recipes.askEveryRun'
                                            : 'recipes.keepCurrentDefault')}
                                    </Typography>
                                )}
                            />
                        )}
                    </Box>
                </Stack>
            </Box>
        );
    };

    return (
        <Dialog open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="sm">
            <DialogTitle>{t('recipes.saveAsRecipe')}</DialogTitle>
            <DialogContent>
                <DialogContentText sx={{ mb: 2 }}>
                    {t('recipes.saveDescription')}
                </DialogContentText>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
                <TextField
                    autoFocus
                    fullWidth
                    required
                    label={t('recipes.name')}
                    value={name}
                    slotProps={{ htmlInput: { maxLength: 200 } }}
                    onChange={event => setName(event.target.value)}
                    sx={{ mb: 2 }}
                />
                <TextField
                    fullWidth
                    multiline
                    minRows={3}
                    label={t('recipes.description')}
                    value={description}
                    slotProps={{ htmlInput: { maxLength: 2000 } }}
                    onChange={event => setDescription(event.target.value)}
                />
                <Box sx={{ mt: 2.5 }}>
                    <Stack direction="row" spacing={1} alignItems="center">
                        <Typography variant="subtitle2" sx={{ flex: 1 }}>
                            {t('recipes.adjustableValues')}
                        </Typography>
                        <Tooltip title={aiContext ? '' : t('recipes.selectModelForAiSuggestions')}>
                            <span>
                                <Button
                                    size="small"
                                    variant="outlined"
                                    startIcon={organizing
                                        ? <CircularProgress size={14} color="inherit" />
                                        : <AutoAwesomeOutlinedIcon fontSize="small" />}
                                    disabled={
                                        !aiContext
                                        || organizing
                                        || saving
                                        || loadingCandidates
                                    }
                                    onClick={() => void organizeParameters()}
                                >
                                    {t(organizing
                                        ? 'recipes.organizingParameters'
                                        : 'recipes.organizeParametersWithAi')}
                                </Button>
                            </span>
                        </Tooltip>
                    </Stack>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1 }}>
                        {t('recipes.adjustableValuesDescription')}
                    </Typography>
                    {suggestionMessage && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                            {suggestionMessage}
                        </Typography>
                    )}
                    {unmatchedSuggestions.length > 0 && (
                        <Alert severity="info" variant="outlined" sx={{ mb: 1, py: 0 }}>
                            {t('recipes.unmatchedParameterSuggestions', {
                                values: unmatchedSuggestions.join(', '),
                            })}
                        </Alert>
                    )}
                    {suggestionError && (
                        <Alert severity="warning" variant="outlined" sx={{ mb: 1 }}>
                            {suggestionError}
                        </Alert>
                    )}
                    {loadingCandidates ? (
                        <Stack direction="row" spacing={1} alignItems="center" sx={{ py: 1 }}>
                            <CircularProgress size={18} />
                            <Typography variant="body2" color="text.secondary">
                                {t('recipes.findingAdjustableValues')}
                            </Typography>
                        </Stack>
                    ) : candidates.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">
                            {t('recipes.noAdjustableValues')}
                        </Typography>
                    ) : (
                        <Stack spacing={1}>
                            {selectedCandidates.length > 0 && (
                                <Typography variant="caption" color="text.secondary">
                                    {t('recipes.selectedAdjustableValues')}
                                </Typography>
                            )}
                            {selectedCandidates.map(renderCandidate)}
                            {otherCandidates.length > 0 && (
                                <>
                                    <Button
                                        size="small"
                                        variant="text"
                                        onClick={() => setShowOtherCandidates(value => !value)}
                                        sx={{ alignSelf: 'flex-start', px: 0, textTransform: 'none' }}
                                    >
                                        {t(showOtherCandidates
                                            ? 'recipes.hideOtherAdjustableValues'
                                            : 'recipes.showOtherAdjustableValues', {
                                            count: otherCandidates.length,
                                        })}
                                    </Button>
                                    <Collapse in={showOtherCandidates} unmountOnExit>
                                        <Stack spacing={1}>
                                            {otherCandidates.map(renderCandidate)}
                                        </Stack>
                                    </Collapse>
                                </>
                            )}
                        </Stack>
                    )}
                </Box>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose} disabled={saving}>{t('app.cancel')}</Button>
                <Button
                    variant="contained"
                    onClick={save}
                    disabled={saving || loadingCandidates || !name.trim()}
                    startIcon={saving ? <CircularProgress size={16} color="inherit" /> : undefined}
                >
                    {t('recipes.save')}
                </Button>
            </DialogActions>
        </Dialog>
    );
};


export const SaveAsRecipeButton: FC<{ chart: Chart; compact?: boolean }> = ({ chart, compact = false }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const tables = useSelector(dfSelectors.getAllTables);
    const charts = useSelector((state: DataFormulatorState) => state.charts);
    const conceptShelfItems = useSelector(
        (state: DataFormulatorState) => state.conceptShelfItems,
    );
    const activeWorkspace = useSelector(
        (state: DataFormulatorState) => state.activeWorkspace,
    );
    const selectedModelId = useSelector(
        (state: DataFormulatorState) => state.selectedModelId,
    );
    const selectedModel = useSelector((state: DataFormulatorState) => (
        [...state.globalModels, ...state.models]
            .find(model => model.id === state.selectedModelId)
    ));
    const timeoutSeconds = useSelector(
        (state: DataFormulatorState) => state.config.formulateTimeoutSeconds,
    );
    const current = isChartRecipeArtifactCurrent(chart);
    const tooltip = current ? t('recipes.saveAsRecipe') : t('recipes.artifactStale');
    const aiContext = useMemo<RecipeParameterAiContext | undefined>(() => {
        if (!selectedModel || selectedModel.id !== selectedModelId) return undefined;
        const targetTable = tables.find(table => (
            table.id === chart.tableRef || table.displayId === chart.tableRef
        ));
        let workflowContext: Record<string, unknown> | undefined;
        if (activeWorkspace && targetTable) {
            const events = buildLeafEvents(
                targetTable,
                tables,
                charts,
                conceptShelfItems,
            );
            if (events?.length) {
                const built = buildSessionWorkflowContext(activeWorkspace, [{
                    thread_id: targetTable.id,
                    label: targetTable.displayId || targetTable.id,
                    events,
                }]);
                workflowContext = built?.payload as unknown as Record<string, unknown>;
            }
        }
        return {
            model: buildDistillModelConfig(selectedModel as ModelConfig),
            workflowContext,
            timeoutSeconds,
        };
    }, [
        activeWorkspace,
        chart.tableRef,
        charts,
        conceptShelfItems,
        selectedModel,
        selectedModelId,
        tables,
        timeoutSeconds,
    ]);

    return (
        <>
            <Tooltip title={tooltip} placement="bottom">
                <span>
                    <IconButton
                        size="small"
                        aria-label={t('recipes.saveAsRecipe')}
                        disabled={!current}
                        onClick={(event) => {
                            event.stopPropagation();
                            setOpen(true);
                        }}
                        sx={compact ? {
                            p: 0.5,
                            color: 'primary.main',
                            '&:hover': { transform: 'scale(1.15)' },
                        } : floatingPillSx}
                    >
                        <SaveAsOutlinedIcon sx={{ fontSize: iconVar.lg }} />
                    </IconButton>
                </span>
            </Tooltip>
            <SaveAsRecipeDialog
                chart={chart}
                open={open}
                onClose={() => setOpen(false)}
                aiContext={aiContext}
            />
        </>
    );
};
