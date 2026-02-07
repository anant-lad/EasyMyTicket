import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout';
import UserHome from '../components/dashboard/UserHome';
import CreateTicket from '../components/tickets/CreateTicket';
import TicketList from '../components/tickets/TicketList';
import TicketDetail from '../components/tickets/TicketDetail';
import UserProfile from '../components/UserProfile';

const UserDashboard: React.FC = () => {
  return (
    <DashboardLayout role="user">
      <Routes>
        <Route path="dashboard" element={<UserHome />} />
        <Route path="tickets" element={<TicketList />} />
        <Route path="tickets/:ticketNumber" element={<TicketDetail />} />
        <Route path="create-ticket" element={<CreateTicket />} />
        <Route path="profile" element={<UserProfile />} />
        <Route path="*" element={<Navigate to="/user/dashboard" replace />} />
      </Routes>
    </DashboardLayout>
  );
};

export default UserDashboard;
