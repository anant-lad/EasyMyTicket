
import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../../components/DashboardLayout';
import { useAuth } from '../../context/AuthContext';
import OrgAdminHome from '../../components/dashboard/OrgAdminHome';
import UserProfile from '../../components/UserProfile';

const OrgAdminDashboard: React.FC = () => {
    const { user } = useAuth();

    return (
        <DashboardLayout role="org_admin" title={`${user?.organization?.company_name || 'Organization'} Dashboard`}>
            <Routes>
                <Route path="dashboard" element={<OrgAdminHome />} />
                <Route path="users" element={<OrgAdminHome />} />
                <Route path="technicians" element={<OrgAdminHome />} />
                <Route path="profile" element={<UserProfile />} />
                <Route path="*" element={<Navigate to="/org/dashboard" replace />} />
            </Routes>
        </DashboardLayout>
    );
};

export default OrgAdminDashboard;
