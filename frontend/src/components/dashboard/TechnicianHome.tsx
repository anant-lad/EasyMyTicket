
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ticketService } from '../../services/tickets';
import { technicianService } from '../../services/technicians';
import { useAuth } from '../../context/AuthContext';
import {
  TicketIcon,
  UserGroupIcon,
  ChartBarIcon,
  SparklesIcon,
  ClockIcon,
  CheckCircleIcon,
  AdjustmentsHorizontalIcon
} from '@heroicons/react/24/outline';
import TicketBoard from '../tickets/TicketBoard';

const TechnicianHome: React.FC = () => {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [viewMode, setViewMode] = useState<'status' | 'deadline'>('status');

  const { data: ticketsData } = useQuery({
    queryKey: ['all-tickets'],
    queryFn: () => ticketService.getTickets({ limit: 50 }),
  });

  const { data: techData } = useQuery({
    queryKey: ['technicians'],
    queryFn: () => technicianService.getTechnicians({ limit: 100 }),
  });

  const tickets = ticketsData?.tickets || [];
  const openTickets = tickets.filter((t: any) => t.status !== 'Closed').length;
  const myTickets = tickets.filter((t: any) => t.assigned_tech_id === user?.user_id).length;
  const technicians = techData?.data || [];

  const reopenedTickets = tickets.filter((t: any) => t.status === 'Reopened');

  const acceptReopenMutation = useMutation({
    mutationFn: (ticketNumber: string) => ticketService.acceptReopen(ticketNumber),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Ticket moved to active queue');
    }
  });

  const rejectReopenMutation = useMutation({
    mutationFn: ({ ticketNumber, reason }: { ticketNumber: string, reason: string }) =>
      ticketService.rejectReopen(ticketNumber, reason, user?.user_id || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Ticket closed');
      setRejectModal({ open: false, ticketNumber: '' });
      setRejectReason('');
    }
  });

  const [rejectModal, setRejectModal] = useState({ open: false, ticketNumber: '' });
  const [rejectReason, setRejectReason] = useState('');

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Technician Command Center</h1>
        <div className="flex items-center gap-4 mt-1">
          <p className="text-gray-500">Manage tickets and system performance</p>
          <div className="h-4 w-px bg-gray-200"></div>
          <label className="inline-flex items-center cursor-pointer">
            <input type="checkbox" value="" className="sr-only peer" defaultChecked />
            <div className="relative w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-green-300 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600"></div>
            <span className="ms-3 text-sm font-medium text-gray-700">Available</span>
          </label>
        </div>
      </div>

      {reopenedTickets.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-6 relative overflow-hidden">
          <div className="absolute top-0 right-0 p-4 opacity-10">
            <TicketIcon className="w-32 h-32 text-amber-500" />
          </div>
          <div className="relative z-10">
            <div className="flex items-center gap-2 mb-4">
              <span className="flex h-3 w-3 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-amber-500"></span>
              </span>
              <h2 className="text-lg font-bold text-amber-900">Reopen Requests Pending Approval</h2>
              <span className="bg-amber-100 text-amber-800 text-xs font-medium px-2.5 py-0.5 rounded-full border border-amber-200">
                {reopenedTickets.length} Requests
              </span>
            </div>

            <div className="grid grid-cols-1 gap-4">
              {reopenedTickets.map((ticket: any) => (
                <div key={ticket.ticketnumber} className="bg-white rounded-xl p-4 shadow-sm border border-amber-100 flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-xs text-gray-500">{ticket.ticketnumber}</span>
                      <span className="text-xs font-medium text-gray-500">• {new Date(ticket.createdate).toLocaleDateString()}</span>
                    </div>
                    <h3 className="text-base font-semibold text-gray-900 mb-1">{ticket.title}</h3>
                    <p className="text-sm text-gray-600 line-clamp-1">{ticket.description}</p>
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">User: {ticket.user_id}</span>
                      {ticket.assigned_tech_id && <span className="text-xs bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded">Prev. Assigned: {ticket.assigned_tech_id}</span>}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 min-w-max">
                    <button
                      onClick={() => acceptReopenMutation.mutate(ticket.ticketnumber)}
                      className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors shadow-sm flex items-center gap-1"
                    >
                      <CheckCircleIcon className="w-4 h-4" /> Accept
                    </button>
                    <button
                      onClick={() => setRejectModal({ open: true, ticketNumber: ticket.ticketnumber })}
                      className="px-4 py-2 bg-white text-red-600 border border-red-200 text-sm font-medium rounded-lg hover:bg-red-50 transition-colors"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-all duration-300 group">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2.5 bg-indigo-50 text-indigo-600 rounded-xl group-hover:bg-indigo-600 group-hover:text-white transition-colors">
              <TicketIcon className="w-6 h-6" />
            </div>
            <span className="text-xs font-semibold text-gray-400">Total</span>
          </div>
          <p className="text-3xl font-bold text-gray-900">{tickets.length}</p>
          <p className="text-xs text-gray-400 mt-1">Tickets in system</p>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-all duration-300 group">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2.5 bg-amber-50 text-amber-600 rounded-xl group-hover:bg-amber-500 group-hover:text-white transition-colors">
              <ClockIcon className="w-6 h-6" />
            </div>
            <span className="text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">Action Req</span>
          </div>
          <p className="text-3xl font-bold text-gray-900">{openTickets}</p>
          <p className="text-xs text-gray-400 mt-1">Open Tickets</p>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-all duration-300 group">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2.5 bg-cyan-50 text-cyan-600 rounded-xl group-hover:bg-cyan-600 group-hover:text-white transition-colors">
              <CheckCircleIcon className="w-6 h-6" />
            </div>
            <span className="text-xs font-semibold text-gray-400">Assigned</span>
          </div>
          <p className="text-3xl font-bold text-gray-900">{myTickets}</p>
          <p className="text-xs text-gray-400 mt-1">My Active Tickets</p>
        </div>

        <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-all duration-300 group">
          <div className="flex items-center justify-between mb-3">
            <div className="p-2.5 bg-emerald-50 text-emerald-600 rounded-xl group-hover:bg-emerald-600 group-hover:text-white transition-colors">
              <UserGroupIcon className="w-6 h-6" />
            </div>
            <span className="text-xs font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">Online</span>
          </div>
          <p className="text-3xl font-bold text-gray-900">{technicians.length}</p>
          <p className="text-xs text-gray-400 mt-1">Active Technicians</p>
        </div>
      </div>

      {/* Feature Links */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Link to="/technician/assistant" className="group relative overflow-hidden bg-gradient-to-r from-violet-600 to-indigo-600 rounded-2xl p-1 shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/40 transition-all duration-300">
          <div className="absolute inset-0 bg-white/10 group-hover:bg-white/0 transition-colors"></div>
          <div className="bg-white/5 backdrop-blur-sm h-full w-full rounded-xl p-6 flex items-center justify-between border border-white/10">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <SparklesIcon className="w-5 h-5 text-yellow-300 animate-pulse" />
                <span className="text-xs font-bold text-indigo-100 uppercase tracking-widest">DeepMind Reasoning</span>
              </div>
              <h3 className="text-2xl font-bold text-white">Lumi - AI</h3>
              <p className="text-indigo-100 mt-2 max-w-sm">Get instant solution suggestions, ticket summaries, and automated routing.</p>
            </div>
            <div className="bg-white/20 p-3 rounded-full backdrop-blur-md group-hover:scale-110 transition-transform">
              <SparklesIcon className="w-8 h-8 text-white" />
            </div>
          </div>
        </Link>

        <Link to="/technician/analytics" className="group bg-white rounded-2xl p-6 shadow-sm border border-gray-100 hover:border-indigo-100 hover:shadow-md transition-all">
          <div className="flex items-center justify-between h-full">
            <div>
              <h3 className="text-xl font-bold text-gray-900 group-hover:text-indigo-600 transition-colors">Performance Analytics</h3>
              <p className="text-gray-500 mt-2">View team efficiency, resolution times, and workload distribution.</p>
            </div>
            <div className="bg-gray-50 p-4 rounded-full group-hover:bg-indigo-50 transition-colors">
              <ChartBarIcon className="w-8 h-8 text-gray-400 group-hover:text-indigo-600" />
            </div>
          </div>
        </Link>
      </div>

      {/* Board View */}
      <div>
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <span className="w-1.5 h-6 bg-purple-600 rounded-full"></span>
              Ticket Board
            </h2>
            <div className="flex bg-gray-100 p-1 rounded-lg">
              <button
                onClick={() => setViewMode('status')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${viewMode === 'status' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-900'}`}
              >
                By Status
              </button>
              <button
                onClick={() => setViewMode('deadline')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${viewMode === 'deadline' ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-900'}`}
              >
                By Deadline
              </button>
            </div>
          </div>
          <Link to="/technician/tickets" className="text-indigo-600 hover:text-indigo-800 text-sm font-medium flex items-center gap-1">
            <AdjustmentsHorizontalIcon className="w-4 h-4" />
            Filter List
          </Link>
        </div>

        <TicketBoard tickets={tickets.filter((t: any) => t.status !== 'Reopened')} role="technician" viewMode={viewMode} />
      </div>

      {/* Reject Modal */}
      {rejectModal.open && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 animate-scale-up">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Reject Reopen Request</h3>
            <p className="text-gray-500 mb-4 text-sm">
              Are you sure you want to reject this reopen request? The ticket will be marked as Closed.
            </p>

            <textarea
              className="w-full border border-gray-300 rounded-lg p-3 min-h-[100px] focus:ring-2 focus:ring-red-200 focus:border-red-500 outline-none mb-4"
              placeholder="Reason for rejection..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              autoFocus
            />

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => {
                  setRejectModal({ open: false, ticketNumber: '' });
                  setRejectReason('');
                }}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => rejectReopenMutation.mutate({ ticketNumber: rejectModal.ticketNumber, reason: rejectReason })}
                disabled={!rejectReason.trim() || rejectReopenMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
              >
                {rejectReopenMutation.isPending ? 'Rejecting...' : 'Confirm Reject'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TechnicianHome;
