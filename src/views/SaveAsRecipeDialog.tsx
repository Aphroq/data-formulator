// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC, useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    IconButton,
    TextField,
    Tooltip,
} from '@mui/material';
import SaveAsOutlinedIcon from '@mui/icons-material/SaveAsOutlined';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { ApiRequestError } from '../app/apiClient';
import { compileRecipe } from '../app/recipeApi';
import { floatingPillSx } from '../app/tokens';
import { iconVar } from '../app/layout';
import {
    Chart,
    computeRecipeArtifactFingerprint,
} from '../components/ComponentType';


export const isChartRecipeArtifactCurrent = (chart: Chart): boolean => Boolean(
    chart.recipeArtifactId
    && chart.recipeArtifactFingerprint
    && chart.recipeArtifactFingerprint === computeRecipeArtifactFingerprint(chart)
);


export const SaveAsRecipeDialog: FC<{
    chart: Chart;
    open: boolean;
    onClose: () => void;
}> = ({ chart, open, onClose }) => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const defaultName = useMemo(
        () => chart.title?.trim() || t('recipes.defaultName'),
        [chart.id, chart.title, t],
    );
    const [name, setName] = useState(defaultName);
    const [description, setDescription] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        if (!open) return;
        setName(defaultName);
        setDescription('');
        setError('');
        setSaving(false);
    }, [defaultName, open]);

    const save = async () => {
        if (!chart.recipeArtifactId || !isChartRecipeArtifactCurrent(chart)) {
            setError(t('recipes.artifactStale'));
            return;
        }
        setSaving(true);
        setError('');
        try {
            const saved = await compileRecipe({
                targetArtifactIds: [chart.recipeArtifactId],
                name: name.trim(),
                description: description.trim(),
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
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose} disabled={saving}>{t('app.cancel')}</Button>
                <Button
                    variant="contained"
                    onClick={save}
                    disabled={saving || !name.trim()}
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
    const current = isChartRecipeArtifactCurrent(chart);
    const tooltip = current ? t('recipes.saveAsRecipe') : t('recipes.artifactStale');

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
            <SaveAsRecipeDialog chart={chart} open={open} onClose={() => setOpen(false)} />
        </>
    );
};
