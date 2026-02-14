import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../../components/DashboardLayout';

import UserProfile from '../../components/UserProfile';

import Organizations from './Organizations';
import SystemHealth from './SystemHealth';
import AuditLogs from './AuditLogs';
import GlobalSettings from './GlobalSettings';
import SuperAdminHome from '../../components/dashboard/SuperAdminHome';
import { useAuth } from '../../context/AuthContext';

const SuperAdminDashboard: React.FC = () => {
    const { user } = useAuth();

    return (
        <DashboardLayout role="super_admin" title="Platform Overview">
            <Routes>
                <Route path="/" element={<Navigate to="dashboard" replace />} />
                <Route path="dashboard" element={<SuperAdminHome />} />
                <Route path="organizations" element={<Organizations />} />
                <Route path="health" element={<SystemHealth />} />
                <Route path="logs" element={<AuditLogs />} />
                <Route path="settings" element={<GlobalSettings />} />
                <Route path="profile" element={<UserProfile />} />
                <Route path="*" element={<Navigate to="dashboard" replace />} />
            </Routes>
        </DashboardLayout>
    );
};

export default SuperAdminDashboard;
