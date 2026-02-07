import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../../components/DashboardLayout';
import SuperAdminHome from '../../components/dashboard/SuperAdminHome';
import UserProfile from '../../components/UserProfile';

const SuperAdminDashboard: React.FC = () => {
    return (
        <DashboardLayout role="super_admin" title="Platform Overview">
            <Routes>
                <Route path="dashboard" element={<SuperAdminHome />} />
                <Route path="profile" element={<UserProfile />} />
                <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
            </Routes>
        </DashboardLayout>
    );
};

export default SuperAdminDashboard;
