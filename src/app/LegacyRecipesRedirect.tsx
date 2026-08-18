// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { FC } from 'react';
import { Navigate, useLocation } from 'react-router-dom';


export const LegacyRecipesRedirect: FC = () => {
    const location = useLocation();
    return <Navigate replace to={`/automation${location.search}${location.hash}`} />;
};
