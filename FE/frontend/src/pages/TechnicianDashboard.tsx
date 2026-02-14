import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout';
import DashboardSkeleton from '../components/skeletons/DashboardSkeleton';
import TechnicianHome from '../components/dashboard/TechnicianHome';
import TicketList from '../components/tickets/TicketList';
import TicketDetail from '../components/tickets/TicketDetail';
import TechnicianManagement from '../components/technicians/TechnicianManagement';
import Analytics from '../components/analytics/Analytics';
import TechnicianAssistant from '../components/technicians/TechnicianAssistant';
import UserProfile from '../components/UserProfile';

const TechnicianDashboard: React.FC = () => {
  // Placeholder loading state
  const loading = false;

  if (loading) {
    return <DashboardSkeleton />;
  }

  return (
    <DashboardLayout role="technician">
      <Routes>
        <Route path="dashboard" element={<TechnicianHome />} />
        <Route path="tickets" element={<TicketList />} />
        <Route path="tickets/:ticketNumber" element={<TicketDetail />} />
        <Route path="my-tickets" element={<TicketList assignedOnly />} />
        {/* Technicians view might not be needed for regular technicians, but keeping if required */}
        <Route path="technicians" element={<TechnicianManagement />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="resolved" element={<TicketList forcedTab="history" />} />
        <Route path="assistant" element={<TechnicianAssistant />} />
        <Route path="profile" element={<UserProfile />} />
        <Route path="*" element={<Navigate to="/technician/dashboard" replace />} />
      </Routes>
    </DashboardLayout>
  );
};

export default TechnicianDashboard;
