// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import type { RecipeParameter } from './recipeApi';


export const parameterValueText = (value: unknown): string => {
    if (value === undefined || value === null) return '';
    return String(value);
};


export const parameterDisplayName = (parameterId: string): string => parameterId
    .split(/[_-]+/)
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');


export const initialParameterValues = (
    parameters: RecipeParameter[],
): Record<string, string> => Object.fromEntries(
    parameters.map(parameter => [
        parameter.id,
        parameterValueText(parameter.default),
    ]),
);


export const parameterInputType = (parameter: RecipeParameter) => {
    if (parameter.type === 'date') return 'date';
    if (parameter.type === 'integer' || parameter.type === 'number') return 'number';
    return 'text';
};


export function typedParameterValues(
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
