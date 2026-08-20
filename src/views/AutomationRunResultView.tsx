// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC, useEffect, useMemo, useRef, useState } from 'react';
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Alert,
    Box,
    Button,
    CircularProgress,
    Divider,
    Stack,
    Tooltip,
    Typography,
} from '@mui/material';
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined';
import ExpandMoreOutlinedIcon from '@mui/icons-material/ExpandMoreOutlined';
import { DndProvider } from 'react-dnd';
import { HTML5Backend } from 'react-dnd-html5-backend';
import { useTranslation } from 'react-i18next';

import {
    AutomationRun,
    AutomationRunAnalysis,
    AutomationRunResult,
    AutomationRunResultOutput,
    AutomationRunTableSampleRequest,
    analyzeRunResult,
    downloadRunResultTable,
    sampleRunResultTable,
} from '../app/automationApi';
import {
    extractFieldsFromEncodingMap,
    prepVisTable,
    resolveRecommendedChart,
} from '../app/utils';
import { Chart, DictTable, FieldItem } from '../components/ComponentType';
import { Type } from '../data/types';
import { FreeDataViewFC } from './DataView';
import { SelectableDataGridDataSource } from './SelectableDataGrid';
import { VegaChartRenderer } from './VisualizationView';


const resultTable = (
    run: AutomationRun,
    output: AutomationRunResultOutput,
): DictTable => ({
    kind: 'table',
    id: `automation-result-${run.run_id}-${output.step_id}`,
    displayId: output.title || output.table.name,
    names: output.table.columns.map(column => column.name),
    metadata: Object.fromEntries(output.table.columns.map(column => [
        column.name,
        {
            type: column.type as Type,
            levels: [],
            ...(output.chart?.field_display_names[column.name]
                ? { displayName: output.chart.field_display_names[column.name] }
                : {}),
        },
    ])),
    rows: output.table.rows,
    virtual: {
        tableId: output.table.name,
        rowCount: output.table.row_count,
    },
    description: output.subtitle,
});

const resultFields = (table: DictTable): FieldItem[] => table.names.map((name, index) => ({
    id: `${table.id}-field-${index}`,
    name,
    source: 'original',
    tableRef: table.id,
}));

const resultChart = (
    run: AutomationRun,
    output: AutomationRunResultOutput,
    table: DictTable,
    fields: FieldItem[],
): Chart | null => {
    if (!output.chart) return null;
    const chart = resolveRecommendedChart(
        { chart: output.chart.spec },
        fields,
        table,
    );
    return {
        ...chart,
        id: `automation-chart-${run.run_id}-${output.step_id}`,
        source: 'trigger',
        title: output.title,
        subtitle: output.subtitle || undefined,
    };
};


const RunOutputView: FC<{
    run: AutomationRun;
    output: AutomationRunResultOutput;
}> = ({ run, output }) => {
    const { t } = useTranslation();
    const compactChart = output.table.row_count <= 3;
    const outputDescription = output.display_instruction || output.subtitle;
    const table = useMemo(() => resultTable(run, output), [run.run_id, output]);
    const fields = useMemo(() => resultFields(table), [table]);
    const chart = useMemo(
        () => resultChart(run, output, table, fields),
        [fields, output, run.run_id, table],
    );
    const fieldSemantics = useMemo(() => Object.fromEntries(
        Object.entries(output.chart?.field_display_names ?? {}).map(
            ([name, displayName]) => [name, { displayName }],
        ),
    ), [output.chart?.field_display_names]);
    const dataSource = useMemo<SelectableDataGridDataSource>(() => ({
        fetchRows: async request => {
            const { table: _table, ...query } = request;
            const sample = await sampleRunResultTable(
                run.run_id,
                output.table.name,
                query as AutomationRunTableSampleRequest,
            );
            return {
                rows: sample.rows,
                totalRowCount: sample.total_row_count,
            };
        },
        download: format => downloadRunResultTable(
            run.run_id,
            output.table.name,
            format,
        ),
    }), [output.table.name, run.run_id]);

    const [chartRows, setChartRows] = useState<Record<string, unknown>[]>(output.table.rows);
    const [chartRowsPrepared, setChartRowsPrepared] = useState(false);
    const [chartLoading, setChartLoading] = useState(false);
    const [chartError, setChartError] = useState('');

    useEffect(() => {
        setChartRows(output.table.rows);
        setChartRowsPrepared(false);
        setChartError('');
        if (!chart || output.table.row_count <= output.table.rows.length) return;

        const { aggregateFields, groupByFields } = extractFieldsFromEncodingMap(
            chart.encodingMap,
            fields,
        );
        let active = true;
        setChartLoading(true);
        void sampleRunResultTable(run.run_id, output.table.name, {
            size: 1000,
            offset: 0,
            method: 'random',
            order_by_fields: [],
            select_fields: groupByFields,
            aggregate_fields_and_functions: aggregateFields.map(([field, operation]) => [
                field ?? null,
                operation,
            ]),
        }).then(sample => {
            if (!active) return;
            setChartRows(sample.rows);
            setChartRowsPrepared(true);
        }).catch(() => {
            if (!active) return;
            setChartError(t('automation.runs.chartFailed'));
        }).finally(() => {
            if (active) setChartLoading(false);
        });
        return () => {
            active = false;
        };
    }, [chart, fields, output, run.run_id, t]);

    const visualRows = useMemo(() => {
        if (!chart) return [];
        return chartRowsPrepared
            ? chartRows
            : prepVisTable(chartRows, fields, chart.encodingMap);
    }, [chart, chartRows, chartRowsPrepared, fields]);

    const tableView = (
        <Stack spacing={1.5}>
            {output.table.columns_truncated && (
                <Alert severity="info">
                    {t('automation.runs.columnsTruncated', {
                        shown: output.table.columns.length,
                        total: output.table.column_count,
                    })}
                </Alert>
            )}
            <Box sx={{ height: 360, minHeight: 300 }}>
                <FreeDataViewFC
                    tableOverride={table}
                    dataSource={dataSource}
                    showSourceName={false}
                    showHeaderBar
                />
            </Box>
        </Stack>
    );

    return (
        <Stack
            component="section"
            aria-labelledby={`run-output-${output.step_id}`}
            spacing={2.5}
        >
            <Box>
                <Typography
                    id={`run-output-${output.step_id}`}
                    variant="h5"
                    component="h3"
                    fontWeight={600}
                >
                    {output.title}
                </Typography>
                {outputDescription && (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {outputDescription}
                    </Typography>
                )}
            </Box>

            {chart && (
                <Box
                    sx={{
                        minHeight: compactChart ? 240 : 360,
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        backgroundColor: 'background.paper',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        overflow: 'hidden',
                        py: compactChart ? 1 : 2,
                    }}
                >
                    {chartLoading ? (
                        <CircularProgress size={28} />
                    ) : chartError ? (
                        <Alert severity="error">{chartError}</Alert>
                    ) : (
                        <VegaChartRenderer
                            chart={chart}
                            conceptShelfItems={fields}
                            visTableRows={visualRows}
                            tableMetadata={table.metadata}
                            chartWidth={compactChart ? 560 : 760}
                            chartHeight={compactChart ? 200 : 320}
                            scaleFactor={1}
                            chartUnavailable={false}
                            fieldSemantics={fieldSemantics}
                        />
                    )}
                </Box>
            )}

            {chart ? (
                <Accordion variant="outlined" disableGutters>
                    <AccordionSummary
                        expandIcon={<ExpandMoreOutlinedIcon />}
                        aria-controls={`run-output-data-${output.step_id}`}
                        id={`run-output-data-toggle-${output.step_id}`}
                    >
                        <Box>
                            <Typography fontWeight={600}>
                                {t('automation.runs.supportingData')}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {t('automation.runs.supportingDataSummary', {
                                    rows: output.table.row_count,
                                    columns: output.table.column_count,
                                })}
                            </Typography>
                        </Box>
                    </AccordionSummary>
                    <AccordionDetails id={`run-output-data-${output.step_id}`}>
                        {tableView}
                    </AccordionDetails>
                </Accordion>
            ) : tableView}
        </Stack>
    );
};


export const AutomationRunResultView: FC<{
    run: AutomationRun;
    result: AutomationRunResult;
    analysisConfig?: {
        model: Record<string, unknown>;
        timeoutSeconds: number;
    };
}> = ({ run, result, analysisConfig }) => {
    const { t } = useTranslation();
    const [analysis, setAnalysis] = useState<AutomationRunAnalysis | null>(null);
    const [analysisLoading, setAnalysisLoading] = useState(false);
    const [analysisError, setAnalysisError] = useState('');
    const analysisRequestSequence = useRef(0);
    const analysisModelId = String(analysisConfig?.model.id ?? '');
    const analysisHelpId = `automation-run-analysis-help-${run.run_id}`;
    const analysisHelp = t(analysisConfig
        ? 'automation.runs.aiAnalysisHelp'
        : 'automation.runs.aiNeedsModel');

    useEffect(() => {
        analysisRequestSequence.current += 1;
        setAnalysis(null);
        setAnalysisError('');
        setAnalysisLoading(false);
        return () => {
            analysisRequestSequence.current += 1;
        };
    }, [analysisModelId, run.run_id]);

    const requestAnalysis = async () => {
        if (!analysisConfig || analysisLoading) return;
        const sequence = ++analysisRequestSequence.current;
        setAnalysisLoading(true);
        setAnalysisError('');
        try {
            const next = await analyzeRunResult(run.run_id, analysisConfig);
            if (analysisRequestSequence.current === sequence) setAnalysis(next);
        } catch {
            if (analysisRequestSequence.current === sequence) {
                setAnalysisError(t('automation.runs.aiFailed'));
            }
        } finally {
            if (analysisRequestSequence.current === sequence) {
                setAnalysisLoading(false);
            }
        }
    };

    if (result.outputs.length === 0) {
        return <Alert severity="info">{t('automation.runs.noResult')}</Alert>;
    }

    return (
        <DndProvider backend={HTML5Backend}>
            <Box component="article" sx={{ width: '100%', maxWidth: 880, mx: 'auto' }}>
                <Stack spacing={3}>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Tooltip title={analysisHelp}>
                            <span>
                                <Button
                                    size="small"
                                    variant="outlined"
                                    startIcon={analysisLoading
                                        ? <CircularProgress size={16} />
                                        : <AutoAwesomeOutlinedIcon />}
                                    disabled={!analysisConfig || analysisLoading}
                                    onClick={() => void requestAnalysis()}
                                    aria-describedby={analysisHelpId}
                                >
                                    {analysis
                                        ? t('automation.runs.aiRetry')
                                        : t('automation.runs.aiAnalysis')}
                                </Button>
                                <Box
                                    component="span"
                                    id={analysisHelpId}
                                    sx={{
                                        position: 'absolute',
                                        width: 1,
                                        height: 1,
                                        p: 0,
                                        m: -1,
                                        overflow: 'hidden',
                                        clip: 'rect(0 0 0 0)',
                                        whiteSpace: 'nowrap',
                                        border: 0,
                                    }}
                                >
                                    {analysisHelp}
                                </Box>
                            </span>
                        </Tooltip>
                    </Box>

                    {analysisError && <Alert severity="error">{analysisError}</Alert>}
                    {analysis && (
                        <Box
                            component="section"
                            role="region"
                            aria-live="polite"
                            aria-label={t('automation.runs.aiAnalysis')}
                            sx={{ p: 2, borderRadius: 1, bgcolor: 'action.hover' }}
                        >
                            <Stack direction="row" spacing={0.75} alignItems="center">
                                <AutoAwesomeOutlinedIcon color="primary" fontSize="small" />
                                <Typography variant="subtitle1" fontWeight={600}>
                                    {t('automation.runs.aiAnalysis')}
                                </Typography>
                            </Stack>
                            <Typography variant="body2" fontWeight={600} sx={{ mt: 1 }}>
                                {analysis.summary}
                            </Typography>
                            <Stack component="ul" spacing={0.75} sx={{ my: 1, pl: 2.5 }}>
                                {analysis.insights.map((insight, index) => (
                                    <Typography component="li" variant="body2" key={`${index}-${insight.finding}`}>
                                        <Box component="span" fontWeight={600}>{insight.finding}</Box>
                                        {' — '}{insight.evidence}
                                    </Typography>
                                ))}
                            </Stack>
                            {analysis.caveat && (
                                <Typography variant="body2" color="text.secondary">
                                    {analysis.caveat}
                                </Typography>
                            )}
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                                {t('automation.runs.aiGenerated')}
                            </Typography>
                        </Box>
                    )}

                    {result.outputs.map((output, index) => (
                        <React.Fragment key={output.step_id}>
                            {index > 0 && <Divider />}
                            <RunOutputView run={run} output={output} />
                        </React.Fragment>
                    ))}
                </Stack>
            </Box>
        </DndProvider>
    );
};
