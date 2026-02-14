import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ticketService } from '../../services/tickets';
import { technicianService } from '../../services/technicians';
import { useAuth } from '../../context/AuthContext';
import toast from 'react-hot-toast';
import {
  ArrowLeftIcon,
  ClockIcon,
  UserIcon,
  DocumentTextIcon,
  PaperClipIcon,
  CheckCircleIcon
} from '@heroicons/react/24/outline';
import FeedbackPanel from '../feedback/FeedbackPanel';

const TicketDetail: React.FC = () => {
  const { ticketNumber } = useParams<{ ticketNumber: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('overview');

  const { data: ticketData, isLoading } = useQuery({
    queryKey: ['ticket', ticketNumber],
    queryFn: () => ticketService.getTicket(ticketNumber || ''),
    enabled: !!ticketNumber,
  });

  const { data: resolutionData } = useQuery({
    queryKey: ['ticket-resolution', ticketNumber],
    queryFn: () => ticketService.getTicketResolution(ticketNumber || ''),
    enabled: !!ticketNumber && (user?.role === 'technician' || user?.role === 'super_admin' || user?.role === 'org_admin'),
  });

  const { data: historyData } = useQuery({
    queryKey: ['ticket-history', ticketNumber],
    queryFn: () => technicianService.getAssignmentHistory(ticketNumber || ''),
    enabled: !!ticketNumber && activeTab === 'history',
  });

  const ticket = ticketData?.ticket_with_labels || ticketData?.ticket;
  const resolution = resolutionData?.resolution;
  const history = historyData?.history || [];

  const [selectedStatus, setSelectedStatus] = useState(ticket?.status || '');
  const [showReopenModal, setShowReopenModal] = useState(false);
  const [reopenReason, setReopenReason] = useState('');
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState('');

  // Sync local state when data loads
  React.useEffect(() => {
    if (ticket?.status) {
      setSelectedStatus(ticket.status);
    }
  }, [ticket?.status]);

  const updateStatusMutation = useMutation({
    mutationFn: ({ status, techId }: { status: string; techId?: string }) =>
      ticketService.updateStatus(ticketNumber || '', status, techId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketNumber] });
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Ticket status updated');
    },
  });

  const resolveMutation = useMutation({
    mutationFn: () => ticketService.resolveTicket(ticketNumber || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketNumber] });
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Ticket resolved successfully');
    },
  });

  const reopenMutation = useMutation({
    mutationFn: () => ticketService.reopenTicket(ticketNumber || '', reopenReason, user?.user_id || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketNumber] });
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Ticket reopened successfully');
      setShowReopenModal(false);
      setReopenReason('');
    },
    onError: (error: any) => {
      toast.error(error.message || 'Failed to reopen ticket');
    }
  });

  const acceptReopenMutation = useMutation({
    mutationFn: () => ticketService.acceptReopen(ticketNumber || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketNumber] });
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Reopen request accepted');
    }
  });

  const rejectReopenMutation = useMutation({
    mutationFn: (reason: string) => ticketService.rejectReopen(ticketNumber || '', reason, user?.user_id || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticket', ticketNumber] });
      queryClient.invalidateQueries({ queryKey: ['all-tickets'] });
      toast.success('Reopen request rejected');
      setShowRejectModal(false);
    }
  });

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'High': return 'bg-red-100 text-red-800 border-red-200';
      case 'Medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'Low': return 'bg-green-100 text-green-800 border-green-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'Open': case 'TO DO': return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'In Progress': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      case 'Reopened': return 'bg-amber-100 text-amber-800 border-amber-200';
      case 'Closed': return 'bg-gray-100 text-gray-800 border-gray-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!ticket) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Ticket not found</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center text-gray-600 hover:text-gray-900 mb-4"
      >
        <ArrowLeftIcon className="w-5 h-5 mr-2" />
        Back
      </button>

      <div className="bg-white rounded-lg shadow-lg p-6">
        <div className="flex justify-between items-start mb-6">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">{ticket.title}</h1>
            <p className="text-gray-600">#{ticket.ticketnumber}</p>
          </div>
          <div className="flex gap-3">
            <span className={`px-4 py-2 rounded-lg border font-medium ${getPriorityColor(ticket.priority)}`}>
              {ticket.priority}
            </span>
            <span className={`px-4 py-2 rounded-lg border font-medium ${getStatusColor(ticket.status)}`}>
              {ticket.status}
            </span>
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200 mb-6">
          <nav className="flex space-x-8">
            {(user?.role === 'technician' || user?.role === 'super_admin' || user?.role === 'org_admin'
              ? ['overview', 'resolution', 'attachments', 'history']
              : ['overview', 'attachments', 'history']
            ).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`py-4 px-1 border-b-2 font-medium text-sm capitalize ${activeTab === tab
                  ? 'border-primary text-primary'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
              >
                {tab}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="mt-6">
          {activeTab === 'overview' && (
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">Description</h3>
                <p className="text-gray-700">{ticket.description}</p>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div>
                  <h4 className="text-sm font-medium text-gray-500 mb-2">Created</h4>
                  <p className="text-gray-900">{new Date(ticket.createdate).toLocaleString()}</p>
                </div>
                {ticket.duedatetime && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-500 mb-2">Due Date</h4>
                    <p className="text-gray-900">{new Date(ticket.duedatetime).toLocaleString()}</p>
                  </div>
                )}
                <div>
                  <h4 className="text-sm font-medium text-gray-500 mb-2">Issue Type</h4>
                  <p className="text-gray-900">{ticket.issuetype_label || ticket.issuetype || 'N/A'}</p>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-gray-500 mb-2">Category</h4>
                  <p className="text-gray-900">{ticket.ticketcategory_label || ticket.ticketcategory || 'N/A'}</p>
                </div>
              </div>

              <div className="border-t pt-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Actions</h3>

                {user?.role === 'technician' ? (
                  ticket.status === 'Reopened' ? (
                    <div className="bg-amber-50 p-4 rounded-lg border border-amber-200">
                      <h4 className="font-bold text-amber-900 mb-2">Reopen Request Pending Approval</h4>
                      <p className="text-amber-800 mb-4 text-sm">Reason: {ticket.resolution ? ticket.resolution.split('Reason: ')[1] : 'No reason provided'}</p>
                      <div className="flex gap-3">
                        <button
                          onClick={() => acceptReopenMutation.mutate()}
                          className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium shadow-sm flex items-center"
                        >
                          <CheckCircleIcon className="w-5 h-5 mr-1" /> Accept Reopen
                        </button>
                        <button
                          onClick={() => setShowRejectModal(true)}
                          className="px-4 py-2 bg-white text-red-600 border border-red-200 rounded-lg hover:bg-red-50 font-medium shadow-sm"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-3 items-center">
                      <select
                        value={selectedStatus}
                        onChange={(e) => {
                          const newStatus = e.target.value;
                          setSelectedStatus(newStatus);
                          // Only auto-save if NOT Closed. If Closed, wait for button click.
                          if (newStatus !== 'Closed') {
                            updateStatusMutation.mutate({
                              status: newStatus,
                              techId: user?.user_id
                            });
                          }
                        }}
                        className="px-4 py-2 border border-gray-300 rounded-lg min-w-[200px]"
                      >
                        <option value="TO DO">TO DO</option>
                        <option value="In Progress">In Progress</option>
                        <option value="Resolution Planned">Resolution Planned</option>
                        <option value="Closed">Closed</option>
                      </select>

                      <button
                        onClick={() => resolveMutation.mutate()}
                        disabled={selectedStatus !== 'Closed'}
                        className={`
                          flex items-center px-4 py-2 rounded-lg transition-all font-medium
                          ${selectedStatus === 'Closed'
                            ? 'bg-green-600 text-white hover:bg-green-700 shadow-sm cursor-pointer'
                            : 'bg-gray-100 text-gray-400 cursor-not-allowed border border-gray-200'}
                        `}
                        title={selectedStatus !== 'Closed' ? "Select 'Closed' stats to resolve" : "Confirm Resolution"}
                      >
                        <CheckCircleIcon className="w-5 h-5 mr-2" />
                        Resolve Ticket
                      </button>
                      {selectedStatus === 'Closed' && ticket.status !== 'Closed' && (
                        <span className="text-xs text-amber-600 font-medium animate-pulse">
                          Click Resolve to confirm closure
                        </span>
                      )}
                    </div>
                  )
                ) : (
                  <div>
                    {ticket.status === 'Closed' ? (
                      <div className="flex items-center justify-between bg-gray-50 p-4 rounded-lg border border-gray-200">
                        <div>
                          <p className="font-medium text-gray-900">This ticket is closed.</p>
                          <p className="text-sm text-gray-500">If you are not satisfied with the resolution, you can reopen it.</p>
                        </div>
                        <button
                          onClick={() => setShowReopenModal(true)}
                          className="px-4 py-2 bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 font-medium rounded-lg shadow-sm transition-colors"
                        >
                          Reopen Ticket
                        </button>
                      </div>
                    ) : ticket.status === 'Reopened' ? (
                      <div className="bg-amber-50 p-4 rounded-lg border border-amber-200">
                        <div className="flex items-center gap-3">
                          <ClockIcon className="w-6 h-6 text-amber-600" />
                          <div>
                            <p className="font-bold text-amber-900">Reopen Request Pending</p>
                            <p className="text-sm text-amber-700">A technician will review your request shortly.</p>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <p className="text-gray-500 italic">No actions available. Waiting for technician response.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'resolution' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Resolution Steps</h3>
              {resolution ? (
                <div className="prose max-w-none">
                  <pre className="whitespace-pre-wrap text-gray-700 bg-gray-50 p-4 rounded-lg">
                    {resolution}
                  </pre>
                </div>
              ) : (
                <p className="text-gray-500">No resolution steps available yet.</p>
              )}
            </div>
          )}

          {activeTab === 'attachments' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Attachments</h3>
              {ticket.attachments && ticket.attachments.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {ticket.attachments.map((file: any, index: number) => (
                    <div key={index} className="flex items-center p-4 border border-gray-200 rounded-lg">
                      <DocumentTextIcon className="w-8 h-8 text-gray-400 mr-3" />
                      <div>
                        <p className="font-medium text-gray-900">{file.filename || `Attachment ${index + 1}`}</p>
                        <p className="text-sm text-gray-500">{file.size || 'Unknown size'}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-500 flex items-center">
                  <PaperClipIcon className="w-5 h-5 mr-2" />
                  No attachments available.
                </p>
              )}
            </div>
          )}

          {activeTab === 'history' && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Ticket History</h3>
              {history && history.length > 0 ? (
                <div className="flow-root">
                  <ul className="-mb-8">
                    {history.map((event: any, eventIdx: number) => (
                      <li key={eventIdx}>
                        <div className="relative pb-8">
                          {eventIdx !== history.length - 1 ? (
                            <span className="absolute top-4 left-4 -ml-px h-full w-0.5 bg-gray-200" aria-hidden="true" />
                          ) : null}
                          <div className="relative flex space-x-3">
                            <div className="h-8 w-8 rounded-full bg-gray-100 flex items-center justify-center ring-8 ring-white">
                              <UserIcon className="h-5 w-5 text-gray-500" />
                            </div>
                            <div className="min-w-0 flex-1 pt-1.5 flex justify-between space-x-4">
                              <div>
                                <p className="text-sm text-gray-500">
                                  Assigned to <span className="font-medium text-gray-900">{event.tech_id}</span>
                                </p>
                              </div>
                              <div className="text-right text-sm whitespace-nowrap text-gray-500">
                                <time dateTime={event.assigned_at}>{new Date(event.assigned_at).toLocaleString()}</time>
                              </div>
                            </div>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-gray-500">No history available.</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Feedback Panel - Technician Only */}
      {user?.role === 'technician' && (
        <FeedbackPanel
          ticketNumber={ticket.ticketnumber}
          isTechnician={true}
        />
      )}

      {/* Reopen Modal */}
      {showReopenModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 animate-scale-up">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Reopen Ticket</h3>
            <p className="text-gray-500 mb-4 text-sm">
              Please explain why you are reopening this ticket. This information will help the technician address your concerns.
            </p>

            <textarea
              className="w-full border border-gray-300 rounded-lg p-3 min-h-[100px] focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
              placeholder="Reason for reopening..."
              value={reopenReason}
              onChange={(e) => setReopenReason(e.target.value)}
              autoFocus
            />

            <div className="flex gap-3 justify-end mt-6">
              <button
                onClick={() => {
                  setShowReopenModal(false);
                  setReopenReason('');
                }}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => reopenMutation.mutate()}
                disabled={!reopenReason.trim() || reopenMutation.isPending}
                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {reopenMutation.isPending ? 'Reopening...' : 'Confirm Reopen'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reject Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 animate-scale-up">
            <h3 className="text-lg font-bold text-gray-900 mb-2">Reject Reopen Request</h3>
            <p className="text-gray-500 mb-4 text-sm">
              Please provide a reason for rejecting this reopen request. The ticket will remain Closed.
            </p>

            <textarea
              className="w-full border border-gray-300 rounded-lg p-3 min-h-[100px] focus:ring-2 focus:ring-red-200 focus:border-red-500 outline-none"
              placeholder="Reason for rejection..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              autoFocus
            />

            <div className="flex gap-3 justify-end mt-6">
              <button
                onClick={() => {
                  setShowRejectModal(false);
                  setRejectReason('');
                }}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => rejectReopenMutation.mutate(rejectReason)}
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

export default TicketDetail;
