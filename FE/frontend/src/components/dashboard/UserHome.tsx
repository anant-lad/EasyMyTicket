
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ticketService } from '../../services/tickets';
import { useAuth } from '../../context/AuthContext';
import { TicketIcon, ClockIcon, PlusCircleIcon } from '@heroicons/react/24/outline';
import TicketBoard from '../tickets/TicketBoard';

const UserHome: React.FC = () => {
  const { user } = useAuth();

  const { data: ticketsData } = useQuery({
    queryKey: ['user-tickets', user?.user_id],
    queryFn: () => ticketService.getTickets({ user_id: user?.user_id, limit: 100 }),
    enabled: !!user,
  });

  const tickets = ticketsData?.tickets || [];
  const totalTickets = ticketsData?.total || 0;
  const openTicketsCount = tickets.filter((t: any) => t.status !== 'Closed').length;

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Header Section */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Welcome back, {user?.user_name}</p>
        </div>
        <Link
          to="/user/create-ticket"
          className="
                    group flex items-center gap-2 bg-gradient-to-r from-indigo-600 to-purple-600 
                    text-white px-5 py-2.5 rounded-xl shadow-lg shadow-indigo-500/30 
                    hover:shadow-indigo-500/50 hover:scale-[1.02] transition-all duration-300 font-medium
                "
        >
          <PlusCircleIcon className="w-5 h-5 group-hover:rotate-90 transition-transform duration-500" />
          Create Ticket
        </Link>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 relative overflow-hidden group hover:shadow-lg transition-all duration-300">
          <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-50 rounded-full -mr-16 -mt-16 transition-transform group-hover:scale-150 duration-700 ease-out"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-4">
              <div className="p-3 bg-indigo-50 rounded-xl text-indigo-600 group-hover:bg-indigo-600 group-hover:text-white transition-colors duration-300">
                <TicketIcon className="w-6 h-6" />
              </div>
              <span className="text-xs font-medium text-green-600 bg-green-50 px-2 py-1 rounded-full">+2 this week</span>
            </div>
            <p className="text-3xl font-bold text-gray-900 mb-1">{totalTickets}</p>
            <p className="text-sm font-medium text-gray-500">Total Tickets</p>
          </div>
        </div>

        <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 relative overflow-hidden group hover:shadow-lg transition-all duration-300">
          <div className="absolute top-0 right-0 w-32 h-32 bg-amber-50 rounded-full -mr-16 -mt-16 transition-transform group-hover:scale-150 duration-700 ease-out"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-4">
              <div className="p-3 bg-amber-50 rounded-xl text-amber-600 group-hover:bg-amber-500 group-hover:text-white transition-colors duration-300">
                <ClockIcon className="w-6 h-6" />
              </div>
              <span className="text-xs font-medium text-amber-600 bg-amber-50 px-2 py-1 rounded-full">Action Required</span>
            </div>
            <p className="text-3xl font-bold text-gray-900 mb-1">{openTicketsCount}</p>
            <p className="text-sm font-medium text-gray-500">Open Tickets</p>
          </div>
        </div>


      </div>

      {/* Ticket List View (Premium Design) */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
          <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            <span className="w-1.5 h-6 bg-indigo-600 rounded-full"></span>
            Recent Activity
          </h2>
          <Link to="/user/tickets" className="text-indigo-600 hover:text-indigo-800 text-sm font-medium flex items-center gap-1 group">
            View All Tickets
            <span className="group-hover:translate-x-1 transition-transform">→</span>
          </Link>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50/50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-100">
                <th className="px-6 py-4">Ticket Details</th>
                <th className="px-6 py-4">Status</th>
                <th className="px-6 py-4">Priority</th>
                <th className="px-6 py-4">Due Date</th>
                <th className="px-6 py-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tickets.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-gray-400">
                    <div className="flex flex-col items-center justify-center">
                      <TicketIcon className="w-12 h-12 text-gray-200 mb-3" />
                      <p>No tickets found. Create one to get started!</p>
                    </div>
                  </td>
                </tr>
              ) : (
                tickets.slice(0, 10).map((ticket: any) => (
                  <tr
                    key={ticket.ticketnumber}
                    className="group hover:bg-gray-50/80 transition-colors duration-200"
                  >
                    <td className="px-6 py-4">
                      <div className="flex flex-col">
                        <span className="text-sm font-bold text-gray-900 group-hover:text-indigo-600 transition-colors mb-0.5">
                          {ticket.title}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                            {ticket.ticketnumber}
                          </span>
                          {ticket.assigned_tech_id && (
                            <span className="text-xs text-gray-400 flex items-center gap-1">
                              <span>•</span> Assigned to {ticket.assigned_tech_name || ticket.assigned_tech_id}
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {/* Status Pill */}
                      <div className="flex items-center">
                        <span className={`
                                inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border
                                ${(ticket.status === 'Open' || ticket.status === 'New' || ticket.status === 'TO DO') ? 'bg-blue-50 text-blue-700 border-blue-100' :
                            ticket.status === 'In Progress' ? 'bg-purple-50 text-purple-700 border-purple-100' :
                              ticket.status === 'Resolution Planned' ? 'bg-amber-50 text-amber-700 border-amber-100' :
                                (ticket.status === 'Resolved' || ticket.status === 'Closed') ? 'bg-green-50 text-green-700 border-green-100' :
                                  'bg-gray-100 text-gray-600 border-gray-200'}
                            `}>
                          <span className={`w-1.5 h-1.5 rounded-full mr-1.5 
                                    ${(ticket.status === 'Open' || ticket.status === 'New' || ticket.status === 'TO DO') ? 'bg-blue-500' :
                              ticket.status === 'In Progress' ? 'bg-purple-500' :
                                ticket.status === 'Resolution Planned' ? 'bg-amber-500' :
                                  (ticket.status === 'Resolved' || ticket.status === 'Closed') ? 'bg-green-500' :
                                    'bg-gray-400'}
                                `}></span>
                          {ticket.status}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`
                            text-xs font-bold uppercase tracking-wider
                            ${(ticket.priority === 'High' || ticket.priority === '1' || ticket.priority === '4') ? 'text-red-600' :
                          (ticket.priority === 'Medium' || ticket.priority === '2') ? 'text-amber-600' :
                            'text-green-600'}
                        `}>
                        {['High', '1'].includes(String(ticket.priority)) ? 'High' :
                          ['Medium', '2'].includes(String(ticket.priority)) ? 'Medium' :
                            ['Low', '3'].includes(String(ticket.priority)) ? 'Low' :
                              ['Critical', '4'].includes(String(ticket.priority)) ? 'Critical' :
                                ticket.priority}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {ticket.duedatetime ? (
                        <div className="flex items-center text-xs text-gray-500">
                          <ClockIcon className={`w-4 h-4 mr-1.5 ${new Date(ticket.duedatetime) < new Date() ? 'text-red-500' : 'text-gray-400'}`} />
                          <span className={new Date(ticket.duedatetime) < new Date() ? 'text-red-600 font-medium' : ''}>
                            {new Date(ticket.duedatetime).toLocaleDateString()}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400 italic">No due date</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      <Link
                        to={`/user/tickets/${ticket.ticketnumber}`}
                        className="
                                inline-flex items-center justify-center px-4 py-1.5 border border-transparent 
                                text-xs font-medium rounded-lg text-indigo-600 bg-indigo-50 
                                hover:bg-indigo-100 transition-colors
                            "
                      >
                        View Details
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default UserHome;
