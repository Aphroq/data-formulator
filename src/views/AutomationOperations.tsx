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
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    MenuItem,
    Stack,
    TextField,
    Typography,
} from '@mui/material';
import EditCalendarOutlinedIcon from '@mui/icons-material/EditCalendarOutlined';
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined';
import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import { useTranslation } from 'react-i18next';

import { ApiRequestError } from '../app/apiClient';
import {
    AutomationRun,
    AutomationRunEvent,
    AutomationRunManifest,
    AutomationRunStatus,
    AutomationSchedule,
    cancelAutomationRun,
    createSchedule,
    getRunEvents,
    getRunManifest,
    listAutomationRuns,
    listSchedules,
    setScheduleEnabled,
    updateSchedule,
} from '../app/automationApi';
import { RecipeSummary, RecipeVersionStatus } from '../app/recipeApi';


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


export const SchedulePanel: FC<{
    versionId: string;
    versionStatus: RecipeVersionStatus;
}> = ({ versionId, versionStatus }) => {
    const { t } = useTranslation();
    const [schedules, setSchedules] = useState<AutomationSchedule[]>([]);
    const [loading, setLoading] = useState(true);
    const [busyId, setBusyId] = useState('');
    const [error, setError] = useState('');
    const [editingId, setEditingId] = useState('');
    const [name, setName] = useState('');
    const [mode, setMode] = useState<'daily' | 'cron'>('daily');
    const [dailyTime, setDailyTime] = useState('09:00');
    const [cronExpression, setCronExpression] = useState('0 9 * * *');
    const [timezone, setTimezone] = useState(browserTimezone);
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
        setName('');
        setMode('daily');
        setDailyTime('09:00');
        setCronExpression('0 9 * * *');
        setTimezone(browserTimezone());
        void load();
        return () => {
            requestSequence.current += 1;
        };
    }, [load]);

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
        setName('');
        setMode('daily');
        setDailyTime('09:00');
        setCronExpression('0 9 * * *');
        setTimezone(browserTimezone());
    };

    const save = async () => {
        if (busyId) return;
        setBusyId(editingId || 'create');
        setError('');
        try {
            const cron = formCron();
            const saved = editingId
                ? await updateSchedule(editingId, {
                    name: name.trim(),
                    cronExpression: cron,
                    timezone: timezone.trim(),
                })
                : await createSchedule({
                    versionId,
                    name: name.trim(),
                    cronExpression: cron,
                    timezone: timezone.trim(),
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
        setEditingId(schedule.schedule_id);
        setName(schedule.name);
        setMode('cron');
        setCronExpression(schedule.cron_expression);
        setTimezone(schedule.timezone);
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

    return (
        <Card component="section" aria-label={t('automation.schedules.title')} variant="outlined" sx={{ p: 2 }}>
            <Typography variant="h6" component="h3">{t('automation.schedules.title')}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {t('automation.schedules.description')}
            </Typography>
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
                                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                        {schedule.cron_expression} · {schedule.timezone}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        {t('automation.schedules.nextRun', { date: displayDate(schedule.next_run_at) })}
                                    </Typography>
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

            {(canCreate || editingId) && (
                <>
                    <Divider sx={{ my: 2 }} />
                    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1.5 }}>
                        <TextField
                            required
                            size="small"
                            label={t('automation.schedules.name')}
                            value={name}
                            inputProps={{ maxLength: 200 }}
                            onChange={event => setName(event.target.value)}
                        />
                        <TextField
                            select
                            size="small"
                            label={t('automation.schedules.mode')}
                            value={mode}
                            disabled={Boolean(editingId)}
                            onChange={event => setMode(event.target.value as 'daily' | 'cron')}
                        >
                            <MenuItem value="daily">{t('automation.schedules.modeDaily')}</MenuItem>
                            <MenuItem value="cron">{t('automation.schedules.modeCron')}</MenuItem>
                        </TextField>
                        {mode === 'daily' ? (
                            <TextField
                                size="small"
                                type="time"
                                label={t('automation.schedules.dailyTime')}
                                value={dailyTime}
                                onChange={event => setDailyTime(event.target.value)}
                                slotProps={{ inputLabel: { shrink: true } }}
                            />
                        ) : (
                            <TextField
                                required
                                size="small"
                                label={t('automation.schedules.cron')}
                                value={cronExpression}
                                inputProps={{ maxLength: 200 }}
                                onChange={event => setCronExpression(event.target.value)}
                            />
                        )}
                        <TextField
                            required
                            size="small"
                            label={t('automation.schedules.timezone')}
                            value={timezone}
                            inputProps={{ maxLength: 100 }}
                            onChange={event => setTimezone(event.target.value)}
                        />
                    </Box>
                    <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                        <Button
                            variant="contained"
                            disabled={Boolean(busyId) || !name.trim() || !timezone.trim()}
                            onClick={() => void save()}
                        >
                            {t(editingId ? 'automation.schedules.save' : 'automation.schedules.create')}
                        </Button>
                        {editingId && (
                            <Button color="inherit" disabled={Boolean(busyId)} onClick={resetForm}>
                                {t('automation.schedules.cancelEdit')}
                            </Button>
                        )}
                        {busyId && <CircularProgress size={22} sx={{ alignSelf: 'center' }} />}
                    </Stack>
                </>
            )}
        </Card>
    );
};


const RunArtifactDialog: FC<{
    run: AutomationRun | null;
    open: boolean;
    onClose: () => void;
}> = ({ run, open, onClose }) => {
    const { t } = useTranslation();
    const [manifest, setManifest] = useState<AutomationRunManifest | null>(null);
    const [events, setEvents] = useState<AutomationRunEvent[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const requestSequence = useRef(0);
    const translation = useRef(t);
    translation.current = t;

    useEffect(() => {
        if (!open || !run) return;
        const sequence = ++requestSequence.current;
        setManifest(null);
        setEvents([]);
        setError('');
        setLoading(true);
        void Promise.all([
            getRunManifest(run.run_id),
            getRunEvents(run.run_id),
        ]).then(([nextManifest, nextEvents]) => {
            if (requestSequence.current !== sequence) return;
            setManifest(nextManifest);
            setEvents(nextEvents);
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
        <Dialog open={open} onClose={onClose} fullWidth maxWidth="md" aria-labelledby="run-artifact-title">
            <DialogTitle id="run-artifact-title">{t('automation.runs.artifactTitle')}</DialogTitle>
            <DialogContent dividers>
                {loading ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={28} /></Box>
                ) : error ? (
                    <Alert severity="error">{error}</Alert>
                ) : (
                    <Stack spacing={3}>
                        <Box>
                            <Typography variant="h6" component="h3">{t('automation.runs.manifest')}</Typography>
                            {manifest && (
                                <>
                                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ my: 1 }}>
                                        <Chip size="small" label={manifest.status} color={runStatusColor(manifest.status)} />
                                        <Typography variant="caption" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                            {manifest.run_id}
                                        </Typography>
                                    </Stack>
                                    {manifest.error && (
                                        <Alert severity={manifest.status === 'needs_review' ? 'warning' : 'error'} sx={{ mb: 1 }}>
                                            <strong>{manifest.error.code}</strong> — {manifest.error.message}
                                        </Alert>
                                    )}
                                    <Stack spacing={0.5}>
                                        {Object.entries(manifest.files).map(([filename, descriptor]) => (
                                            <Stack key={filename} direction="row" spacing={1} justifyContent="space-between">
                                                <Typography variant="body2" sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>{filename}</Typography>
                                                <Typography variant="caption" color="text.secondary">{descriptor.size} B</Typography>
                                            </Stack>
                                        ))}
                                    </Stack>
                                </>
                            )}
                        </Box>
                        <Box>
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
                                                <Chip size="small" label={event.status} />
                                                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                                                    {displayDate(event.recorded_at)}
                                                </Typography>
                                            </Stack>
                                        </Box>
                                    ))}
                                </Stack>
                            )}
                        </Box>
                    </Stack>
                )}
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
}> = ({ workspaceId, recipes, refreshToken, onSelectVersion }) => {
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
                <Button startIcon={<RefreshOutlinedIcon />} disabled={loading} onClick={() => void load()}>
                    {t('automation.runs.refresh')}
                </Button>
            </Stack>

            {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
            {loading && runs.length === 0 ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={28} /></Box>
            ) : runs.length === 0 ? (
                <Typography color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                    {t('automation.runs.empty')}
                </Typography>
            ) : (
                <Stack spacing={1.25} sx={{ mt: 2 }}>
                    {runs.map(run => {
                        const canCancel = (run.status === 'queued' || run.status === 'running')
                            && run.cancel_requested_at === null;
                        return (
                            <Box key={run.run_id} sx={{ border: 1, borderColor: run.status === 'needs_review' ? 'warning.main' : 'divider', borderRadius: 1, p: 1.5 }}>
                                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25} alignItems={{ xs: 'flex-start', md: 'center' }}>
                                    <Box sx={{ flex: 1, minWidth: 0 }}>
                                        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                            <Typography fontWeight={600}>{versionNames.get(run.version_id) ?? run.version_id}</Typography>
                                            <Chip size="small" color={runStatusColor(run.status)} label={t(`automation.runs.status.${run.status}`)} />
                                            <Chip size="small" variant="outlined" label={t(`automation.runs.trigger.${run.trigger}`)} />
                                        </Stack>
                                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                            {run.run_id}
                                        </Typography>
                                        <Typography variant="caption" color="text.secondary">
                                            {displayDate(run.scheduled_for)} · {t('automation.runs.attempts', { count: run.attempt_count })}
                                        </Typography>
                                    </Box>
                                    {run.artifact && (
                                        <Button size="small" startIcon={<SearchOutlinedIcon />} onClick={() => setArtifactRun(run)}>
                                            {t('automation.runs.inspect')}
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
                                {run.error && (
                                    <Alert severity={run.status === 'needs_review' ? 'warning' : 'error'} variant="outlined" sx={{ mt: 1.25 }}>
                                        <Typography variant="body2" fontWeight={600}>{run.error.code}</Typography>
                                        <Typography variant="body2">{run.error.message}</Typography>
                                    </Alert>
                                )}
                            </Box>
                        );
                    })}
                </Stack>
            )}

            <RunArtifactDialog
                run={artifactRun}
                open={artifactRun !== null}
                onClose={() => setArtifactRun(null)}
            />
        </Card>
    );
};
