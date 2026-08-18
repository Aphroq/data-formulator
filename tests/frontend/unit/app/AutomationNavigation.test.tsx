import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => ({
            'appBar.primaryNavigation': 'Primary navigation',
            'appBar.automation': 'Automation',
            'sidebar.openUpload': 'Add data',
            'sidebar.sessions': 'Saved workspaces',
            'sidebar.openDataConnectors': 'Data connectors',
            'sidebar.knowledge': 'Agent knowledge',
        }[key] ?? key),
    }),
}));

import { WorkspaceNavigationRail } from '../../../../src/views/WorkspaceNavigationRail';
import { LegacyRecipesRedirect } from '../../../../src/app/LegacyRecipesRedirect';


const LocationProbe = () => {
    const location = useLocation();
    return <div>{`${location.pathname}${location.search}`}</div>;
};


describe('WorkspaceNavigationRail', () => {
    it('places Automation beside the existing workspace destinations', () => {
        const onSelectTab = vi.fn();
        render(
            <MemoryRouter initialEntries={['/automation']}>
                <WorkspaceNavigationRail
                    automationActive
                    automationEnabled
                    onAddData={vi.fn()}
                    onSelectTab={onSelectTab}
                />
            </MemoryRouter>,
        );

        const navigation = screen.getByRole('navigation', { name: 'Primary navigation' });
        expect(navigation).toContainElement(screen.getByRole('button', { name: 'Saved workspaces' }));
        expect(navigation).toContainElement(screen.getByRole('button', { name: 'Data connectors' }));
        expect(navigation).toContainElement(screen.getByRole('button', { name: 'Agent knowledge' }));
        expect(screen.getByRole('link', { name: 'Automation' })).toHaveAttribute('aria-current', 'page');

        fireEvent.click(screen.getByRole('button', { name: 'Saved workspaces' }));
        expect(onSelectTab).toHaveBeenCalledWith('sessions');
    });

    it('hides only the new Automation entry when the feature is disabled', () => {
        render(
            <MemoryRouter initialEntries={['/app']}>
                <WorkspaceNavigationRail
                    automationEnabled={false}
                    onAddData={vi.fn()}
                    onSelectTab={vi.fn()}
                />
            </MemoryRouter>,
        );

        expect(screen.queryByRole('link', { name: 'Automation' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Saved workspaces' })).toBeInTheDocument();
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
