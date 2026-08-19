// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import type { ContextItem } from '../components/ComponentType';

export const MAX_CONTEXT_ITEMS = 50;
const MAX_URI_CHARS = 2_048;
const MAX_TITLE_CHARS = 512;
const MAX_PROVIDER_CHARS = 64;
const CONTROL_CHARACTER = /[\u0000-\u001f]/;

function normalizeOptionalText(value: unknown, maxChars: number): string | undefined {
    if (typeof value !== 'string') return undefined;
    const normalized = value.trim();
    if (!normalized || normalized.length > maxChars || CONTROL_CHARACTER.test(normalized)) {
        return undefined;
    }
    return normalized;
}

function normalizeUri(value: unknown): string | undefined {
    if (typeof value !== 'string') return undefined;
    const uri = value.trim();
    if (!uri || uri.length > MAX_URI_CHARS || CONTROL_CHARACTER.test(uri) || uri.includes('\\')) {
        return undefined;
    }

    try {
        const parsed = new URL(uri);
        const protocol = parsed.protocol.toLowerCase();
        if (protocol === 'http:' || protocol === 'https:') {
            if (!parsed.hostname || parsed.username || parsed.password) return undefined;
        } else if (protocol === 'urn:') {
            if (!uri.slice(uri.indexOf(':') + 1)) return undefined;
        } else {
            return undefined;
        }
    } catch {
        return undefined;
    }
    return uri;
}

/**
 * Revalidate untrusted streamed or restored evidence, preserving first-seen
 * order and matching the backend's per-event cap.
 */
export function normalizeContextItems(value: unknown): ContextItem[] {
    if (!Array.isArray(value)) return [];

    const normalized: ContextItem[] = [];
    const seen = new Set<string>();
    for (const candidate of value) {
        if (!candidate || typeof candidate !== 'object') continue;
        const source = candidate as Record<string, unknown>;
        const uri = normalizeUri(source.uri);
        if (!uri || seen.has(uri)) continue;

        const item: ContextItem = { uri };
        const title = normalizeOptionalText(source.title, MAX_TITLE_CHARS);
        const provider = normalizeOptionalText(source.provider, MAX_PROVIDER_CHARS);
        if (title) item.title = title;
        if (provider) item.provider = provider;

        seen.add(uri);
        normalized.push(item);
        if (normalized.length >= MAX_CONTEXT_ITEMS) break;
    }
    return normalized;
}

function mergeContextItems(
    existing: readonly ContextItem[],
    incoming: readonly ContextItem[],
): ContextItem[] {
    return normalizeContextItems([...existing, ...incoming]);
}

/**
 * Small run-local accumulator. Each artifact receives an immutable `all()`
 * snapshot of the evidence available when it was produced; the final TextTurn
 * receives the final run-wide snapshot. Constructor seeds carry citations
 * forward when a persisted turn is resumed.
 */
export class ContextItemAccumulator {
    private runItems: ContextItem[];

    constructor(seed: unknown = []) {
        this.runItems = normalizeContextItems(seed);
    }

    add(value: unknown): void {
        const incoming = normalizeContextItems(value);
        this.runItems = mergeContextItems(this.runItems, incoming);
    }

    all(): ContextItem[] {
        return this.runItems.map(item => ({ ...item }));
    }
}

/** Return a safe external href, or undefined for URNs/invalid historical data. */
export function getOpenableContextUri(uri: string): string | undefined {
    const normalized = normalizeUri(uri);
    if (!normalized) return undefined;
    const protocol = new URL(normalized).protocol.toLowerCase();
    return protocol === 'http:' || protocol === 'https:' ? normalized : undefined;
}
