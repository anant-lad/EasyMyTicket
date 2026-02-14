import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout';
import DashboardSkeleton from '../components/skeletons/DashboardSkeleton';
import UserHome from '../components/dashboard/UserHome';
import CreateTicket from '../components/tickets/CreateTicket';
import TicketList from '../components/tickets/TicketList';
import TicketDetail from '../components/tickets/TicketDetail';
import UserProfile from '../components/UserProfile';
import TechnicianList from '../components/user/TechnicianList';

const UserDashboard: React.FC = () => {
  // Assuming 'loading' state would be managed here, for example, with useState and useEffect
  // For the purpose of this edit, we'll simulate the conditional rendering as requested.
  // In a real application, 'loading' would come from a state management solution or a hook.
  const loading = false; // Placeholder: set to true to see the skeleton

  if (loading) {
    return <DashboardSkeleton />;
  }

  return (
    <DashboardLayout role="user">
      <Routes>
        <Route path="dashboard" element={<UserHome />} />
        <Route path="tickets" element={<TicketList />} />
        <Route path="tickets/:ticketNumber" element={<TicketDetail />} />
        <Route path="technicians" element={<TechnicianList />} />
        <Route path="create-ticket" element={<CreateTicket />} />
        <Route path="profile" element={<UserProfile />} />
        <Route path="*" element={<Navigate to="/user/dashboard" replace />} />
      </Routes>
    </DashboardLayout>
  );
};

export default UserDashboard;
