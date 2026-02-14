
import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../../components/DashboardLayout';
import { useAuth } from '../../context/AuthContext';
import OrgAnalytics from '../../components/dashboard/OrgAnalytics';
import UserManagement from '../../components/dashboard/UserManagement';
import TechnicianManagement from '../../components/technicians/TechnicianManagement';
import OrgReports from '../../components/dashboard/OrgReports';
import OrgSettings from '../../components/dashboard/OrgSettings';
import UserProfile from '../../components/UserProfile';

const OrgAdminDashboard: React.FC = () => {
    const { user } = useAuth();

    return (
        <DashboardLayout role="org_admin" title={`${user?.organization?.company_name || 'Organization'} Dashboard`}>
            <Routes>
                <Route path="dashboard" element={<OrgAnalytics />} />
                <Route path="users" element={<UserManagement />} />
                <Route path="technicians" element={<TechnicianManagement />} />
                <Route path="reports" element={<OrgReports />} />
                <Route path="settings" element={<OrgSettings />} />
                <Route path="profile" element={<UserProfile />} />
                <Route path="*" element={<Navigate to="/org/dashboard" replace />} />
            </Routes>
        </DashboardLayout>
    );
};

export default OrgAdminDashboard;
