// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

export type ProgressTranslator = (
    key: string,
    options?: Record<string, unknown>,
) => string;

export type BusinessContextProgressState = {
    initialStepIndex?: number;
    finalizingStepIndex?: number;
    queryStepIndexes: Map<number, number>;
};

type ToolProgressEvent = {
    tool?: unknown;
    query_index?: unknown;
    phase?: unknown;
};

const BUSINESS_CONTEXT_TOOL = 'query_business_context';
const QUERY_PHASE_KEYS = {
    searching: 'dataThread.businessKnowledgeSearching',
    filtering: 'dataThread.businessKnowledgeFiltering',
    summarizing: 'dataThread.businessKnowledgeSummarizing',
    completed: 'dataThread.businessKnowledgeCompleted',
} as const;

/** Return the one user-facing progress label owned by business context lookup. */
export function businessContextProgress(
    tool: unknown,
    translate: ProgressTranslator,
): string | undefined {
    return tool === BUSINESS_CONTEXT_TOOL
        ? translate('dataThread.checkingBusinessKnowledge')
        : undefined;
}

export function createBusinessContextProgressState(): BusinessContextProgressState {
    return { queryStepIndexes: new Map<number, number>() };
}

/** Start one high-level lookup, reusing this row for its first query round. */
export function beginBusinessContextProgress(
    steps: string[],
    tool: unknown,
    translate: ProgressTranslator,
    state: BusinessContextProgressState,
): boolean {
    const label = businessContextProgress(tool, translate);
    if (!label) return false;

    state.queryStepIndexes.clear();
    state.finalizingStepIndex = undefined;
    state.initialStepIndex = steps.length;
    steps.push(label);
    return true;
}

/** Apply a safe backend phase without exposing query text or Agent reasoning. */
export function applyBusinessContextToolProgress(
    steps: string[],
    event: ToolProgressEvent,
    translate: ProgressTranslator,
    state: BusinessContextProgressState,
): boolean {
    if (event.tool !== BUSINESS_CONTEXT_TOOL) return false;

    if (event.phase === 'finalizing') {
        if (event.query_index !== null && event.query_index !== undefined) {
            return false;
        }
        let stepIndex = state.finalizingStepIndex;
        if (stepIndex === undefined) {
            if (state.queryStepIndexes.size === 0 && state.initialStepIndex !== undefined) {
                stepIndex = state.initialStepIndex;
            } else {
                stepIndex = steps.length;
                steps.push('');
            }
            state.finalizingStepIndex = stepIndex;
        }
        steps[stepIndex] = translate('dataThread.businessKnowledgeFinalizing');
        return true;
    }

    if (
        typeof event.query_index !== 'number'
        || !Number.isInteger(event.query_index)
        || event.query_index < 1
        || typeof event.phase !== 'string'
        || !(event.phase in QUERY_PHASE_KEYS)
    ) {
        return false;
    }

    const phase = event.phase as keyof typeof QUERY_PHASE_KEYS;
    let stepIndex = state.queryStepIndexes.get(event.query_index);
    if (stepIndex === undefined) {
        if (state.queryStepIndexes.size === 0 && state.initialStepIndex !== undefined) {
            stepIndex = state.initialStepIndex;
        } else {
            stepIndex = steps.length;
            steps.push('');
        }
        state.queryStepIndexes.set(event.query_index, stepIndex);
    }
    const label = translate(QUERY_PHASE_KEYS[phase], { index: event.query_index });
    steps[stepIndex] = phase === 'completed' ? `✓ ${label}` : label;
    return true;
}

/** Close only the active business-context row; do not touch earlier tool steps. */
export function settleBusinessContextProgress(
    steps: string[],
    state: BusinessContextProgressState,
    isError: boolean,
): void {
    const queryIndexes = Array.from(state.queryStepIndexes.keys());
    const latestQuery = queryIndexes.length > 0
        ? state.queryStepIndexes.get(Math.max(...queryIndexes))
        : undefined;
    const stepIndex = state.finalizingStepIndex
        ?? latestQuery
        ?? state.initialStepIndex;
    if (stepIndex === undefined || !steps[stepIndex]) return;

    const label = steps[stepIndex].replace(/^[✓✗]\s+/, '');
    if (isError) {
        steps[stepIndex] = `✗ ${label}`;
    } else if (!steps[stepIndex].startsWith('✓')) {
        steps[stepIndex] = `✓ ${label}`;
    }
}

/** Settle the newest pending progress step while preserving prior history. */
export function settleLatestProgressStep(
    steps: string[],
    isError: boolean,
): void {
    for (let index = steps.length - 1; index >= 0; index--) {
        if (!steps[index].startsWith('✓') && !steps[index].startsWith('✗')) {
            steps[index] = `${isError ? '✗' : '✓'} ${steps[index]}`;
            break;
        }
    }
}
