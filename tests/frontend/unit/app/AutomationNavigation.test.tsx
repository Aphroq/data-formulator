import React from 'react';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => ({
            'appBar.primaryNavigation': 'Primary navigation',
            'appBar.app': 'App',
            'appBar.automation': 'Automation',
            'appBar.about': 'About',
        }[key] ?? key),
    }),
}));

import { AppNavigation } from '../../../../src/app/AppNavigation';
import { LegacyRecipesRedirect } from '../../../../src/app/LegacyRecipesRedirect';


const LocationProbe = () => {
    const location = useLocation();
    return <div>{`${location.pathname}${location.search}`}</div>;
};


describe('AppNavigation', () => {
    it('shows Automation only when enabled and marks the current page', () => {
        const { rerender } = render(
            <MemoryRouter initialEntries={['/automation']}>
                <AppNavigation automationEnabled />
            </MemoryRouter>,
        );

        expect(screen.getByRole('navigation', { name: 'Primary navigation' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Automation' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'App' })).not.toHaveAttribute('aria-current');

        rerender(
            <MemoryRouter initialEntries={['/app']}>
                <AppNavigation automationEnabled={false} />
            </MemoryRouter>,
        );

        expect(screen.queryByRole('link', { name: 'Automation' })).not.toBeInTheDocument();
    });
});


describe('LegacyRecipesRedirect', () => {
    it('keeps the selected version query when redirecting to Automation', async () => {
        render(
            <MemoryRouter initialEntries={['/recipes?version=rv%2F1']}>
                <Routes>
                    <Route path="recipes" element={<LegacyRecipesRedirect />} />
                    <Route path="automation" element={<LocationProbe />} />
                </Routes>
            </MemoryRouter>,
        );

        expect(await screen.findByText('/automation?version=rv%2F1')).toBeInTheDocument();
    });
});
