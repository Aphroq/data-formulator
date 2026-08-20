// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Alert,
    Box,
    Button,
    Card,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    IconButton,
    MenuItem,
    Stack,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import AddOutlinedIcon from '@mui/icons-material/AddOutlined';
import EditCalendarOutlinedIcon from '@mui/icons-material/EditCalendarOutlined';
import ExpandMoreOutlinedIcon from '@mui/icons-material/ExpandMoreOutlined';
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined';
import { useTranslation } from 'react-i18next';

import { ApiRequestError } from '../app/apiClient';
import {
    AutomationRun,
    AutomationRunEvent,
    AutomationRunManifest,
    AutomationRunResult,
    AutomationRunStatus,
    AutomationSchedule,
    AutomationParameterPolicy,
    cancelAutomationRun,
    createSchedule,
    getRunEvents,
    getRunManifest,
    getRunResult,
    listAutomationRuns,
    listSchedules,
    setScheduleEnabled,
    updateSchedule,
} from '../app/automationApi';
import { RecipeParameter, RecipeSummary, RecipeVersionStatus } from '../app/recipeApi';
import {
    parameterDisplayName,
    parameterInputType,
    parameterValueText,
    typedParameterValues,
} from '../app/recipeParameters';
import { AutomationRunResultView } from './AutomationRunResultView';


const browserTimezone = () => {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
        return 'UTC';
    }
};

const displayDate = (value: string) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const apiMessage = (reason: unknown, fallback: string) => (
    reason instanceof ApiRequestError ? reason.apiError.message : fallback
);

const runStatusColor = (status: AutomationRunStatus) => {
    if (status === 'succeeded') return 'success' as const;
    if (status === 'failed') return 'error' as const;
    if (status === 'needs_review') return 'warning' as const;
    if (status === 'running') return 'info' as const;
    return 'default' as const;
};

const dailyCronTime = (expression: string) => {
    const match = expression.match(/^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$/);
    if (!match) return null;
    const minute = Number(match[1]);
    const hour = Number(match[2]);
    if (minute > 59 || hour > 23) return null;
    return `${match[2].padStart(2, '0')}:${match[1].padStart(2, '0')}`;
};

type ScheduleParameterDraft = {
    source: 'literal' | 'scheduled';
    value: string;
    offsetDays: number;
};

const initialScheduleParameterDrafts = (
    parameters: RecipeParameter[],
): Record<string, ScheduleParameterDraft> => Object.fromEntries(
    parameters.map(parameter => [parameter.id, {
        source: 'literal',
        value: parameterValueText(parameter.default),
        offsetDays: 0,
    }]),
);

const scheduleParameterDrafts = (
    parameters: RecipeParameter[],
    policy: Record<string, AutomationParameterPolicy>,
): Record<string, ScheduleParameterDraft> => Object.fromEntries(
    parameters.map(parameter => {
        const entry = policy[parameter.id];
        if (entry?.source === 'scheduled_date' || entry?.source === 'scheduled_datetime') {
            return [parameter.id, {
                source: 'scheduled',
                value: parameterValueText(parameter.default),
                offsetDays: entry.offset_days,
            }];
        }
        return [parameter.id, {
            source: 'literal',
            value: parameterValueText(entry?.source === 'literal'
                ? entry.value
                : parameter.default),
            offsetDays: 0,
        }];
    }),
);

const scheduleParameterPolicy = (
    parameters: RecipeParameter[],
    drafts: Record<string, ScheduleParameterDraft>,
): Record<string, AutomationParameterPolicy> => {
    const result: Record<string, AutomationParameterPolicy> = {};
    for (const parameter of parameters) {
        const draft = drafts[parameter.id] ?? {
            source: 'literal' as const,
            value: '',
            offsetDays: 0,
        };
        if (draft.source === 'scheduled') {
            if (parameter.type !== 'date' && parameter.type !== 'datetime') {
                throw new TypeError(parameter.name);
            }
            result[parameter.id] = {
                source: parameter.type === 'date'
                    ? 'scheduled_date'
                    : 'scheduled_datetime',
                offset_days: draft.offsetDays,
            };
            continue;
        }
        const typed = typedParameterValues(
            [parameter],
            { [parameter.id]: draft.value },
        );
        if (parameter.id in typed) {
            result[parameter.id] = {
                source: 'literal',
                value: typed[parameter.id],
            };
        }
    }
    return result;
};


export const SchedulePanel: FC<{
    versionId: string;
    versionStatus: RecipeVersionStatus;
    parameters: RecipeParameter[];
}> = ({ versionId, versionStatus, parameters }) => {
    const { t } = useTranslation();
    const [schedules, setSchedules] = useState<AutomationSchedule[]>([]);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState('');
    const [error, setError] = useState('');
    const [editingId, setEditingId] = useState('');
    const [formOpen, setFormOpen] = useState(false);
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [name, setName] = useState('');
    const [mode, setMode] = useState<'daily' | 'cron'>('daily');
    const [dailyTime, setDailyTime] = useState('09:00');
    const [cronExpression, setCronExpression] = useState('0 9 * * *');
    const [timezone, setTimezone] = useState(browserTimezone);
    const [parameterDrafts, setParameterDrafts] = useState<
        Record<string, ScheduleParameterDraft>
    >(() => initialScheduleParameterDrafts(parameters));
    const requestSequence = useRef(0);
    const translation = useRef(t);
    translation.current = t;

    const load = useCallback(async () => {
        const sequence = ++requestSequence.current;
        setLoading(true);
        setError('');
        try {
            const next = await listSchedules();
            if (requestSequence.current !== sequence) return;
            setSchedules(next.filter(item => item.version_id === versionId));
        } catch (reason) {
            if (requestSequence.current !== sequence) return;
            setError(apiMessage(
                reason,
                translation.current('automation.schedules.loadFailed'),
            ));
        } finally {
            if (requestSequence.current === sequence) setLoading(false);
        }
    }, [versionId]);

    useEffect(() => {
        setEditingId('');
        setFormOpen(false);
        setShowAdvanced(false);
        setName('');
        setMode('daily');
        setDailyTime('09:00');
        setCronExpression('0 9 * * *');
        setTimezone(browserTimezone());
        setParameterDrafts(initialScheduleParameterDrafts(parameters));
        void load();
        return () => {
            requestSequence.current += 1;
        };
    }, [load, parameters]);

    const formCron = () => {
        if (mode === 'cron') return cronExpression.trim();
        if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(dailyTime)) {
            throw new TypeError(t('automation.schedules.invalidTime'));
        }
        const [hour, minute] = dailyTime.split(':').map(Number);
        return `${minute} ${hour} * * *`;
    };

    const resetForm = () => {
        setEditingId('');
        setFormOpen(false);
        setShowAdvanced(false);
        setName('');
        setMode('daily');
        setDailyTime('09:00');
        setCronExpression('0 9 * * *');
        setTimezone(browserTimezone());
        setParameterDrafts(initialScheduleParameterDrafts(parameters));
    };

    const startCreate = () => {
        setEditingId('');
        setFormOpen(true);
        setShowAdvanced(false);
        setName(t('automation.schedules.defaultName'));
        setMode('daily');
        setDailyTime('09:00');
        setCronExpression('0 9 * * *');
        setTimezone(browserTimezone());
        setParameterDrafts(initialScheduleParameterDrafts(parameters));
        setError('');
    };

    const save = async () => {
        if (busyId) return;
        setBusyId(editingId || 'create');
        setError('');
        try {
            const cron = formCron();
            let parameterPolicy: Record<string, AutomationParameterPolicy>;
            try {
                parameterPolicy = scheduleParameterPolicy(parameters, parameterDrafts);
            } catch (reason) {
                const parameterName = reason instanceof TypeError ? reason.message : '';
                throw new Error(t('recipes.invalidParameter', { name: parameterName }));
            }
            const saved = editingId
                ? await updateSchedule(editingId, {
                    name: name.trim(),
                    cronExpression: cron,
                    timezone: timezone.trim(),
                    parameterPolicy,
                })
                : await createSchedule({
                    versionId,
                    name: name.trim(),
                    cronExpression: cron,
                    timezone: timezone.trim(),
                    parameterPolicy,
                });
            setSchedules(current => {
                const without = current.filter(item => item.schedule_id !== saved.schedule_id);
                return [saved, ...without];
            });
            resetForm();
        } catch (reason) {
            setError(apiMessage(reason, reason instanceof Error
                ? reason.message
                : t('automation.schedules.actionFailed')));
        } finally {
            setBusyId('');
        }
    };

    const edit = (schedule: AutomationSchedule) => {
        const time = dailyCronTime(schedule.cron_expression);
        setEditingId(schedule.schedule_id);
        setFormOpen(true);
        setShowAdvanced(time === null);
        setName(schedule.name);
        setMode(time === null ? 'cron' : 'daily');
        if (time !== null) setDailyTime(time);
        setCronExpression(schedule.cron_expression);
        setTimezone(schedule.timezone);
        setParameterDrafts(scheduleParameterDrafts(
            parameters,
            schedule.parameter_policy ?? {},
        ));
        setError('');
    };

    const toggle = async (schedule: AutomationSchedule) => {
        if (busyId) return;
        setBusyId(schedule.schedule_id);
        setError('');
        try {
            const updated = await setScheduleEnabled(
                schedule.schedule_id,
                !schedule.enabled,
            );
            setSchedules(current => current.map(item => (
                item.schedule_id === updated.schedule_id ? updated : item
            )));
        } catch (reason) {
            setError(apiMessage(reason, t('automation.schedules.actionFailed')));
        } finally {
            setBusyId('');
        }
    };

    const canCreate = versionStatus === 'published';
    const scheduleTiming = (schedule: AutomationSchedule) => {
        const time = dailyCronTime(schedule.cron_expression);
        if (time === null) return t('automation.schedules.customSummary');
        return t('automation.schedules.dailySummary', { time });
    };
    const updateParameterDraft = (
        parameterId: string,
        patch: Partial<ScheduleParameterDraft>,
    ) => setParameterDrafts(current => ({
        ...current,
        [parameterId]: {
            ...(current[parameterId] ?? {
                source: 'literal',
                value: '',
                offsetDays: 0,
            }),
            ...patch,
        },
    }));
    const relativeDayLabel = (offsetDays: number) => {
        if (offsetDays === -1) return t('automation.schedules.previousDay');
        if (offsetDays === 0) return t('automation.schedules.runDay');
        if (offsetDays === 1) return t('automation.schedules.nextDay');
        return t('automation.schedules.dayOffset', { count: offsetDays });
    };
    const scheduleParametersSummary = (schedule: AutomationSchedule) => parameters
        .flatMap(parameter => {
            const entry = (schedule.parameter_policy ?? {})[parameter.id];
            if (!entry) return [];
            const value = entry.source === 'literal'
                ? String(entry.value)
                : relativeDayLabel(entry.offset_days);
            return [`${parameter.name}: ${value}`];
        })
        .join(' · ');

    return (
        <Card component="section" aria-label={t('automation.schedules.title')} variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" spacing={1.5} alignItems="flex-start">
                <Box sx={{ flex: 1 }}>
                    <Typography variant="h6" component="h3">{t('automation.schedules.title')}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        {t('automation.schedules.description')}
                    </Typography>
                </Box>
                {canCreate && !formOpen && (
                    <Button size="small" startIcon={<AddOutlinedIcon />} onClick={startCreate}>
                        {t('automation.schedules.add')}
                    </Button>
                )}
            </Stack>
            {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}

            {loading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}><CircularProgress size={24} /></Box>
            ) : schedules.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                    {t('automation.schedules.empty')}
                </Typography>
            ) : (
                <Stack spacing={1} sx={{ mt: 2 }}>
                    {schedules.map(schedule => (
                        <Box key={schedule.schedule_id} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5 }}>
                            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'flex-start', sm: 'center' }}>
                                <Box sx={{ flex: 1, minWidth: 0 }}>
                                    <Typography fontWeight={600}>{schedule.name}</Typography>
                                    <Typography variant="body2" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                        {scheduleTiming(schedule)} · {schedule.timezone}
                                    </Typography>
                                    {parameters.length > 0 && (
                                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                            {scheduleParametersSummary(schedule)}
                                        </Typography>
                                    )}
                                    {schedule.enabled && (
                                        <Typography variant="caption" color="text.secondary">
                                            {t('automation.schedules.nextRun', { date: displayDate(schedule.next_run_at) })}
                                        </Typography>
                                    )}
                                </Box>
                                <Chip
                                    size="small"
                                    color={schedule.enabled ? 'success' : 'default'}
                                    label={t(`automation.schedules.${schedule.enabled ? 'enabled' : 'disabled'}`)}
                                />
                                <Button
                                    size="small"
                                    startIcon={<EditCalendarOutlinedIcon />}
                                    disabled={Boolean(busyId)}
                                    onClick={() => edit(schedule)}
                                >
                                    {t('automation.schedules.edit')}
                                </Button>
                                <Button
                                    size="small"
                                    color={schedule.enabled ? 'inherit' : 'primary'}
                                    startIcon={schedule.enabled
                                        ? <PauseCircleOutlineIcon />
                                        : <PlayCircleOutlineIcon />}
                                    disabled={Boolean(busyId) || (!schedule.enabled && versionStatus !== 'published')}
                                    onClick={() => void toggle(schedule)}
                                >
                                    {t(`automation.schedules.${schedule.enabled ? 'disable' : 'enable'}`)}
                                </Button>
                            </Stack>
                        </Box>
                    ))}
                </Stack>
            )}

            {(formOpen || editingId) && (
                <Box sx={{ mt: 2, p: 2, borderRadius: 1.5, bgcolor: 'action.hover' }}>
                    <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1.5 }}>
                        {t(editingId
                            ? 'automation.schedules.formEditTitle'
                            : 'automation.schedules.formCreateTitle')}
                    </Typography>
                    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1.5 }}>
                        <TextField
                            required
                            size="small"
                            label={t('automation.schedules.name')}
                            value={name}
                            inputProps={{ maxLength: 200 }}
                            onChange={event => setName(event.target.value)}
                        />
                        {mode === 'daily' ? (
                            <TextField
                                size="small"
                                type="time"
                                label={t('automation.schedules.dailyTime')}
                                value={dailyTime}
                                onChange={event => setDailyTime(event.target.value)}
                                slotProps={{ inputLabel: { shrink: true } }}
                            />
                        ) : showAdvanced ? (
                            <TextField
                                required
                                size="small"
                                label={t('automation.schedules.cron')}
                                value={cronExpression}
                                inputProps={{ maxLength: 200 }}
                                onChange={event => setCronExpression(event.target.value)}
                            />
                        ) : null}
                    </Box>
                    <Button
                        size="small"
                        color="inherit"
                        endIcon={<ExpandMoreOutlinedIcon sx={{ transform: showAdvanced ? 'rotate(180deg)' : 'none' }} />}
                        sx={{ mt: 1 }}
                        onClick={() => setShowAdvanced(current => !current)}
                    >
                        {t(showAdvanced
                            ? 'automation.schedules.fewerSettings'
                            : 'automation.schedules.moreSettings')}
                    </Button>
                    {showAdvanced && (
                        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1.5, mt: 1 }}>
                            <TextField
                                select
                                size="small"
                                label={t('automation.schedules.mode')}
                                value={mode}
                                onChange={event => setMode(event.target.value as 'daily' | 'cron')}
                            >
                                <MenuItem value="daily">{t('automation.schedules.modeDaily')}</MenuItem>
                                <MenuItem value="cron">{t('automation.schedules.modeCron')}</MenuItem>
                            </TextField>
                            <TextField
                                required
                                size="small"
                                label={t('automation.schedules.timezone')}
                                value={timezone}
                                inputProps={{ maxLength: 100 }}
                                onChange={event => setTimezone(event.target.value)}
                            />
                        </Box>
                    )}
                    {parameters.length > 0 && (
                        <Box sx={{ mt: 2 }}>
                            <Divider sx={{ mb: 2 }} />
                            <Typography variant="subtitle2">
                                {t('automation.schedules.runParameters')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 1.5 }}>
                                {t('automation.schedules.runParametersHelp')}
                            </Typography>
                            <Stack spacing={1.25}>
                                {parameters.map(parameter => {
                                    const draft = parameterDrafts[parameter.id] ?? {
                                        source: 'literal' as const,
                                        value: '',
                                        offsetDays: 0,
                                    };
                                    const supportsScheduled = parameter.type === 'date'
                                        || parameter.type === 'datetime';
                                    if (!supportsScheduled) {
                                        return (
                                            <TextField
                                                key={parameter.id}
                                                size="small"
                                                select={parameter.type === 'boolean'}
                                                type={parameterInputType(parameter)}
                                                required={parameter.required}
                                                label={parameter.name}
                                                helperText={parameter.description || undefined}
                                                value={draft.value}
                                                onChange={event => updateParameterDraft(
                                                    parameter.id,
                                                    { value: event.target.value },
                                                )}
                                            >
                                                {parameter.type === 'boolean' ? [
                                                    <MenuItem key="true" value="true">{t('recipes.true')}</MenuItem>,
                                                    <MenuItem key="false" value="false">{t('recipes.false')}</MenuItem>,
                                                ] : undefined}
                                            </TextField>
                                        );
                                    }
                                    return (
                                        <Box key={parameter.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.25, bgcolor: 'background.paper' }}>
                                            <Typography variant="body2" fontWeight={600} sx={{ mb: 1 }}>
                                                {parameter.name}
                                            </Typography>
                                            {parameter.description && (
                                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: -0.5, mb: 1 }}>
                                                    {parameter.description}
                                                </Typography>
                                            )}
                                            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1 }}>
                                                <TextField
                                                    select
                                                    size="small"
                                                    label={t('automation.schedules.valueSource')}
                                                    value={draft.source}
                                                    onChange={event => updateParameterDraft(
                                                        parameter.id,
                                                        { source: event.target.value as 'literal' | 'scheduled' },
                                                    )}
                                                >
                                                    <MenuItem value="literal">{t('automation.schedules.fixedValue')}</MenuItem>
                                                    <MenuItem value="scheduled">{t('automation.schedules.relativeValue')}</MenuItem>
                                                </TextField>
                                                {draft.source === 'literal' ? (
                                                    <TextField
                                                        size="small"
                                                        type={parameterInputType(parameter)}
                                                        required={parameter.required}
                                                        label={t('automation.schedules.value')}
                                                        value={draft.value}
                                                        onChange={event => updateParameterDraft(
                                                            parameter.id,
                                                            { value: event.target.value },
                                                        )}
                                                        slotProps={{ inputLabel: parameter.type === 'date' ? { shrink: true } : undefined }}
                                                    />
                                                ) : (
                                                    <TextField
                                                        select
                                                        size="small"
                                                        label={t('automation.schedules.relativeDay')}
                                                        value={draft.offsetDays}
                                                        onChange={event => updateParameterDraft(
                                                            parameter.id,
                                                            { offsetDays: Number(event.target.value) },
                                                        )}
                                                    >
                                                        <MenuItem value={-1}>{t('automation.schedules.previousDay')}</MenuItem>
                                                        <MenuItem value={0}>{t('automation.schedules.runDay')}</MenuItem>
                                                        <MenuItem value={1}>{t('automation.schedules.nextDay')}</MenuItem>
                                                    </TextField>
                                                )}
                                            </Box>
                                        </Box>
                                    );
                                })}
                            </Stack>
                        </Box>
                    )}
                    <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                        <Button
                            variant="contained"
                            disabled={Boolean(busyId) || !name.trim() || !timezone.trim()}
                            onClick={() => void save()}
                        >
                            {t(editingId ? 'automation.schedules.save' : 'automation.schedules.create')}
                        </Button>
                        <Button color="inherit" disabled={Boolean(busyId)} onClick={resetForm}>
                            {t('automation.schedules.cancelEdit')}
                        </Button>
                        {busyId && <CircularProgress size={22} sx={{ alignSelf: 'center' }} />}
                    </Stack>
                </Box>
            )}
        </Card>
    );
};


const RunArtifactDialog: FC<{
    run: AutomationRun | null;
    recipeName: string;
    open: boolean;
    onClose: () => void;
    analysisConfig?: {
        model: Record<string, unknown>;
        timeoutSeconds: number;
    };
}> = ({ run, recipeName, open, onClose, analysisConfig }) => {
    const { t } = useTranslation();
    const [manifest, setManifest] = useState<AutomationRunManifest | null>(null);
    const [events, setEvents] = useState<AutomationRunEvent[]>([]);
    const [result, setResult] = useState<AutomationRunResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const requestSequence = useRef(0);
    const translation = useRef(t);
    translation.current = t;
    const reportParameterNames = new Map(
        (result?.report.parameters ?? []).map(parameter => [
            parameter.id,
            parameter.name,
        ]),
    );

    useEffect(() => {
        if (!open || !run) return;
        const sequence = ++requestSequence.current;
        setManifest(null);
        setEvents([]);
        setResult(null);
        setError('');
        setLoading(true);
        const pending = run.status === 'succeeded'
            ? getRunResult(run.run_id).then(nextResult => ({
                manifest: nextResult.manifest,
                events: nextResult.events,
                result: nextResult,
            }))
            : Promise.all([
                getRunManifest(run.run_id),
                getRunEvents(run.run_id),
            ]).then(([nextManifest, nextEvents]) => ({
                manifest: nextManifest,
                events: nextEvents,
                result: null,
            }));
        void pending.then(next => {
            if (requestSequence.current !== sequence) return;
            setManifest(next.manifest);
            setEvents(next.events);
            setResult(next.result);
        }).catch(reason => {
            if (requestSequence.current !== sequence) return;
            setError(apiMessage(
                reason,
                translation.current('automation.runs.artifactFailed'),
            ));
        }).finally(() => {
            if (requestSequence.current === sequence) setLoading(false);
        });
        return () => {
            requestSequence.current += 1;
        };
    }, [open, run?.run_id]);

    return (
        <Dialog
            open={open}
            onClose={onClose}
            fullWidth
            maxWidth={run?.status === 'succeeded' ? 'lg' : 'sm'}
            aria-labelledby="run-artifact-title"
        >
            <DialogTitle id="run-artifact-title">
                {run?.status === 'succeeded'
                    ? t('automation.runs.resultTitle', {
                        name: result?.report.title || recipeName,
                    })
                    : t('automation.runs.artifactTitle')}
            </DialogTitle>
            <DialogContent dividers>
                {loading ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={28} /></Box>
                ) : error ? (
                    <Alert severity="error">{error}</Alert>
                ) : manifest ? (
                    <Stack spacing={2.5}>
                        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                            <Chip
                                size="small"
                                label={t(`automation.runs.status.${manifest.status}`)}
                                color={runStatusColor(manifest.status)}
                            />
                            {run && (
                                <Typography variant="body2" color="text.secondary">
                                    {displayDate(run.scheduled_for)} · {t(`automation.runs.trigger.${run.trigger}`)}
                                </Typography>
                            )}
                            {run && Object.entries(run.parameters ?? {}).map(([name, value]) => (
                                <Chip
                                    key={name}
                                    size="small"
                                    variant="outlined"
                                    label={`${reportParameterNames.get(name) ?? parameterDisplayName(name)}: ${String(value)}`}
                                />
                            ))}
                        </Stack>
                        {manifest.error && (
                            <Alert severity={manifest.status === 'needs_review' ? 'warning' : 'error'}>
                                {t(manifest.status === 'needs_review'
                                    ? 'automation.runs.needsReview'
                                    : 'automation.runs.failedHelp')}
                            </Alert>
                        )}
                        {result && run && (
                            <AutomationRunResultView
                                run={run}
                                result={result}
                                analysisConfig={analysisConfig}
                            />
                        )}
                        {!result && <Box>
                            <Typography variant="h6" component="h3" sx={{ mb: 1 }}>{t('automation.runs.events')}</Typography>
                            {events.length === 0 ? (
                                <Typography color="text.secondary">{t('automation.runs.noEvents')}</Typography>
                            ) : (
                                <Stack spacing={1}>
                                    {events.map(event => (
                                        <Box key={event.sequence} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.25 }}>
                                            <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                                <Chip size="small" variant="outlined" label={event.sequence + 1} />
                                                <Typography fontWeight={600}>{t(`recipes.stepKind.${event.kind}`)}</Typography>
                                                <Chip size="small" label={t(`automation.runs.eventStatus.${event.status}`)} />
                                                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                                                    {displayDate(event.recorded_at)}
                                                </Typography>
                                            </Stack>
                                        </Box>
                                    ))}
                                </Stack>
                            )}
                        </Box>}
                        <Accordion variant="outlined" disableGutters>
                            <AccordionSummary expandIcon={<ExpandMoreOutlinedIcon />}>
                                <Typography fontWeight={600}>{t('automation.runs.technicalInfo')}</Typography>
                            </AccordionSummary>
                            <AccordionDetails>
                                <Stack spacing={2}>
                                    {result && events.length > 0 && (
                                        <Box>
                                            <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
                                                {t('automation.runs.events')}
                                            </Typography>
                                            <Stack spacing={0.5}>
                                                {events.map(event => (
                                                    <Stack key={event.sequence} direction="row" spacing={1} alignItems="center">
                                                        <Typography variant="body2">
                                                            {event.sequence + 1}. {t(`recipes.stepKind.${event.kind}`)}
                                                        </Typography>
                                                        <Chip size="small" variant="outlined" label={t(`automation.runs.eventStatus.${event.status}`)} />
                                                    </Stack>
                                                ))}
                                            </Stack>
                                        </Box>
                                    )}
                                    <Box>
                                        <Typography variant="caption" color="text.secondary">
                                            {t('automation.runs.runIdentifier')}
                                        </Typography>
                                        <Typography variant="body2" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                            {manifest.run_id}
                                        </Typography>
                                    </Box>
                                    <Box>
                                        <Typography variant="caption" color="text.secondary">
                                            {t('automation.runs.versionIdentifier')}
                                        </Typography>
                                        <Typography variant="body2" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                            {manifest.version_id}
                                        </Typography>
                                    </Box>
                                    {manifest.error && (
                                        <Alert severity="info" variant="outlined">
                                            <Typography variant="body2" fontWeight={600}>{manifest.error.code}</Typography>
                                            <Typography variant="body2">{manifest.error.message}</Typography>
                                        </Alert>
                                    )}
                                    <Box>
                                        <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
                                            {t('automation.runs.outputFiles')}
                                        </Typography>
                                        <Stack spacing={0.5}>
                                            {Object.entries(manifest.files).map(([filename, descriptor]) => (
                                                <Stack key={filename} direction="row" spacing={1} justifyContent="space-between">
                                                    <Typography variant="body2" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>{filename}</Typography>
                                                    <Typography variant="caption" color="text.secondary">{descriptor.size} B</Typography>
                                                </Stack>
                                            ))}
                                        </Stack>
                                    </Box>
                                </Stack>
                            </AccordionDetails>
                        </Accordion>
                    </Stack>
                ) : null}
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>{t('automation.runs.close')}</Button>
            </DialogActions>
        </Dialog>
    );
};


export const RunsInbox: FC<{
    workspaceId: string;
    recipes: RecipeSummary[];
    refreshToken: number;
    onSelectVersion: (versionId: string) => void;
    analysisConfig?: {
        model: Record<string, unknown>;
        timeoutSeconds: number;
    };
}> = ({ workspaceId, recipes, refreshToken, onSelectVersion, analysisConfig }) => {
    const { t } = useTranslation();
    const [runs, setRuns] = useState<AutomationRun[]>([]);
    const [filter, setFilter] = useState<AutomationRunStatus | 'all'>('all');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [busyRunId, setBusyRunId] = useState('');
    const [artifactRun, setArtifactRun] = useState<AutomationRun | null>(null);
    const requestSequence = useRef(0);
    const translation = useRef(t);
    translation.current = t;

    const versionNames = useMemo(() => new Map(
        recipes.flatMap(recipe => recipe.versions.map(version => [
            version.version_id,
            recipe.name,
        ] as const)),
    ), [recipes]);

    const load = useCallback(async () => {
        const sequence = ++requestSequence.current;
        setLoading(true);
        setError('');
        try {
            const next = await listAutomationRuns({
                limit: 50,
                ...(filter === 'all' ? {} : { status: filter }),
            });
            if (requestSequence.current !== sequence) return;
            setRuns(next);
        } catch (reason) {
            if (requestSequence.current !== sequence) return;
            setError(apiMessage(
                reason,
                translation.current('automation.runs.loadFailed'),
            ));
        } finally {
            if (requestSequence.current === sequence) setLoading(false);
        }
    }, [filter]);

    useEffect(() => {
        setRuns([]);
        setArtifactRun(null);
        void load();
        return () => {
            requestSequence.current += 1;
        };
    }, [load, refreshToken, workspaceId]);

    const cancel = async (run: AutomationRun) => {
        if (busyRunId) return;
        setBusyRunId(run.run_id);
        setError('');
        try {
            const updated = await cancelAutomationRun(run.run_id);
            setRuns(current => current.map(item => (
                item.run_id === updated.run_id ? updated : item
            )));
        } catch (reason) {
            setError(apiMessage(reason, t('automation.runs.cancelFailed')));
        } finally {
            setBusyRunId('');
        }
    };

    return (
        <Card component="section" aria-label={t('automation.runs.title')} variant="outlined" sx={{ mt: 2, p: { xs: 2, md: 2.5 } }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', sm: 'center' }}>
                <Box sx={{ flex: 1 }}>
                    <Typography variant="h5" component="h2">{t('automation.runs.title')}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                        {t('automation.runs.description')}
                    </Typography>
                </Box>
                <TextField
                    select
                    size="small"
                    label={t('automation.runs.filter')}
                    value={filter}
                    sx={{ minWidth: 160 }}
                    onChange={event => setFilter(event.target.value as AutomationRunStatus | 'all')}
                >
                    <MenuItem value="all">{t('automation.runs.all')}</MenuItem>
                    {(['queued', 'running', 'succeeded', 'failed', 'needs_review', 'cancelled'] as AutomationRunStatus[]).map(status => (
                        <MenuItem key={status} value={status}>{t(`automation.runs.status.${status}`)}</MenuItem>
                    ))}
                </TextField>
                <Tooltip title={t('automation.runs.refresh')}>
                    <span>
                        <IconButton
                            aria-label={t('automation.runs.refresh')}
                            disabled={loading}
                            onClick={() => void load()}
                        >
                            <RefreshOutlinedIcon />
                        </IconButton>
                    </span>
                </Tooltip>
            </Stack>

            {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
            {loading && runs.length === 0 ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={28} /></Box>
            ) : runs.length === 0 ? (
                <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                    {t('automation.runs.empty')}
                </Typography>
            ) : (
                <Stack divider={<Divider flexItem />} sx={{ mt: 1.5 }}>
                    {runs.map(run => {
                        const canCancel = (run.status === 'queued' || run.status === 'running')
                            && run.cancel_requested_at === null;
                        return (
                            <Box key={run.run_id} sx={{ py: 1.5 }}>
                                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25} alignItems={{ xs: 'flex-start', md: 'center' }}>
                                    <Box sx={{ flex: 1, minWidth: 0 }}>
                                        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                            <Typography fontWeight={600}>
                                                {versionNames.get(run.version_id) ?? t('automation.runs.unknownRecipe')}
                                            </Typography>
                                            <Chip size="small" color={runStatusColor(run.status)} label={t(`automation.runs.status.${run.status}`)} />
                                            <Chip size="small" variant="outlined" label={t(`automation.runs.trigger.${run.trigger}`)} />
                                        </Stack>
                                        <Typography variant="caption" color="text.secondary">
                                            {displayDate(run.scheduled_for)}
                                        </Typography>
                                        {Object.keys(run.parameters ?? {}).length > 0 && (
                                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                                                {t('automation.runs.parameterSummary', {
                                                    values: Object.entries(run.parameters ?? {})
                                                        .map(([name, value]) => `${parameterDisplayName(name)}=${String(value)}`)
                                                        .join(' · '),
                                                })}
                                            </Typography>
                                        )}
                                    </Box>
                                    {run.artifact && (
                                        <Button
                                            size="small"
                                            startIcon={run.status === 'succeeded'
                                                ? <VisibilityOutlinedIcon />
                                                : <SearchOutlinedIcon />}
                                            onClick={() => setArtifactRun(run)}
                                        >
                                            {t(run.status === 'succeeded'
                                                ? 'automation.runs.viewResult'
                                                : 'automation.runs.inspect')}
                                        </Button>
                                    )}
                                    {run.status === 'needs_review' && (
                                        <Button size="small" color="warning" onClick={() => onSelectVersion(run.version_id)}>
                                            {t('automation.runs.reviewRecipe')}
                                        </Button>
                                    )}
                                    {canCancel && (
                                        <Button
                                            size="small"
                                            color="inherit"
                                            disabled={Boolean(busyRunId)}
                                            onClick={() => void cancel(run)}
                                        >
                                            {t('automation.runs.cancel')}
                                        </Button>
                                    )}
                                    {busyRunId === run.run_id && <CircularProgress size={20} />}
                                </Stack>
                                {run.status === 'needs_review' && (
                                    <Alert severity="warning" sx={{ mt: 1.25 }}>
                                        {t('automation.runs.needsReview')}
                                    </Alert>
                                )}
                                {run.status === 'failed' && (
                                    <Alert severity="error" sx={{ mt: 1.25 }}>
                                        {t('automation.runs.failedHelp')}
                                    </Alert>
                                )}
                            </Box>
                        );
                    })}
                </Stack>
            )}

            <RunArtifactDialog
                run={artifactRun}
                recipeName={artifactRun
                    ? versionNames.get(artifactRun.version_id) ?? t('automation.runs.unknownRecipe')
                    : ''}
                open={artifactRun !== null}
                onClose={() => setArtifactRun(null)}
                analysisConfig={analysisConfig}
            />
        </Card>
    );
};
