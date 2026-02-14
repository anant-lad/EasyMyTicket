
import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ticketService } from '../../services/tickets';
import { useAuth } from '../../context/AuthContext';
import { MagnifyingGlassIcon, ArchiveBoxIcon, TicketIcon } from '@heroicons/react/24/outline';

interface TicketListProps {
  assignedOnly?: boolean;
  forcedTab?: 'active' | 'history';
}

const TicketList: React.FC<TicketListProps> = ({ assignedOnly = false, forcedTab }) => {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<'active' | 'history'>(forcedTab || 'active');

  // Sync state if forcedTab prop changes (e.g. navigation between My Tickets and Resolved Tickets)
  React.useEffect(() => {
    if (forcedTab) {
      setActiveTab(forcedTab);
    }
  }, [forcedTab]);

  const [filters, setFilters] = useState({
    priority: '',
    issuetype: '',
    search: '',
  });

  const [page, setPage] = useState(0);
  const LIMIT = 10;

  const { data, isLoading } = useQuery({
    queryKey: ['tickets', filters, activeTab, assignedOnly, user?.user_id, page],
    queryFn: () => {
      const params: any = {
        limit: LIMIT,
        offset: page * LIMIT,
      };

      if (activeTab === 'active') {
        // Depending on API support, ideally we pass status_ne=Closed
        // For now, we will fetch generic list and rely on client filtering for accurate display 
        // if backend params are limited, BUT we should try to pass status if we can.
        // Since existing code allowed filtering by status, we won't force a status param here 
        // unless user specifically selects one in a filter (not implemented in this simplified view).
        // We'll rely on client side filter mainly, but can optimize later.
      } else {
        // If history, we specifically look for closed/resolved if possible, 
        // or just fetch all and filter.
        // Let's assume fetching all is okay for now given pagination.
      }

      if (filters.priority) params.priority = filters.priority;
      if (filters.issuetype) params.issuetype = filters.issuetype;

      // Multi-tenancy
      if (user?.companyid) params.companyid = user.companyid;
      if (assignedOnly && user) params.assigned_tech_id = user.user_id;

      return ticketService.getTickets(params);
    },
  });

  const tickets = data?.tickets || [];

  const displayedTickets = tickets.filter((ticket: any) => {
    // Search Filter
    if (filters.search) {
      const searchLower = filters.search.toLowerCase();
      const matchesSearch = (
        ticket.title?.toLowerCase().includes(searchLower) ||
        ticket.ticketnumber?.toLowerCase().includes(searchLower) ||
        ticket.description?.toLowerCase().includes(searchLower)
      );
      if (!matchesSearch) return false;
    }

    // Tab Filter
    if (activeTab === 'active') {
      return ticket.status !== 'Closed' && ticket.status !== 'Resolved';
    } else {
      return ticket.status === 'Closed' || ticket.status === 'Resolved';
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
      case 'In Progress': return 'bg-purple-100 text-purple-800 border-purple-200';
      case 'Resolved': return 'bg-green-100 text-green-800 border-green-200';
      case 'Closed': return 'bg-gray-100 text-gray-800 border-gray-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500">

      {/* Tabs */}
      {!forcedTab && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-1 flex space-x-1 w-fit">
          <button
            onClick={() => { setActiveTab('active'); setPage(0); }}
            className={`
                px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2
                ${activeTab === 'active'
                ? 'bg-indigo-50 text-indigo-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'}
            `}
          >
            <TicketIcon className="w-4 h-4" />
            Active Tickets
          </button>
          <button
            onClick={() => { setActiveTab('history'); setPage(0); }}
            className={`
                px-4 py-2 text-sm font-medium rounded-lg transition-all flex items-center gap-2
                ${activeTab === 'history'
                ? 'bg-indigo-50 text-indigo-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'}
            `}
          >
            <ArchiveBoxIcon className="w-4 h-4" />
            History
          </button>
        </div>
      )}

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        {/* Filters */}
        <div className="p-6 border-b border-gray-100 bg-gray-50/50 flex flex-col md:flex-row gap-4">
          <div className="flex-1 relative group">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
            <input
              type="text"
              placeholder="Search by ID, title, or content..."
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
              className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all outline-none"
            />
          </div>
          <div className="flex gap-4">
            <select
              value={filters.priority}
              onChange={(e) => setFilters({ ...filters, priority: e.target.value })}
              className="px-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none cursor-pointer"
            >
              <option value="">All Priorities</option>
              <option value="High">High</option>
              <option value="Medium">Medium</option>
              <option value="Low">Low</option>
              <option value="Critical">Critical</option>
            </select>
            <select
              value={filters.issuetype}
              onChange={(e) => setFilters({ ...filters, issuetype: e.target.value })}
              className="px-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none cursor-pointer"
            >
              <option value="">All Types</option>
              <option value="Incident">Incident</option>
              <option value="Service Request">Service Request</option>
              <option value="Access Request">Access Request</option>
            </select>
          </div>
        </div>

        {/* Loading State */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <div className="w-10 h-10 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-4"></div>
            <p>Loading tickets...</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {displayedTickets.length === 0 ? (
              <div className="py-20 text-center text-gray-500 flex flex-col items-center">
                <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                  <ArchiveBoxIcon className="w-8 h-8 text-gray-300" />
                </div>
                <h3 className="text-lg font-medium text-gray-900">No tickets found</h3>
                <p className="text-sm text-gray-400 mt-1">Try adjusting your filters or search query.</p>
              </div>
            ) : (
              displayedTickets.map((ticket: any) => (
                <Link
                  key={ticket.ticketnumber}
                  to={user?.role === 'user'
                    ? `/user/tickets/${ticket.ticketnumber}`
                    : `/technician/tickets/${ticket.ticketnumber}`
                  }
                  className="block group hover:bg-gray-50/80 transition-all duration-200"
                >
                  <div className="p-6 flex items-start gap-4">
                    {/* Priority Stripe */}
                    <div className={`w-1 self-stretch rounded-full ${ticket.priority === 'High' ? 'bg-red-500' :
                      ticket.priority === 'Medium' ? 'bg-amber-500' :
                        'bg-green-500'
                      }`}></div>

                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between items-start mb-1">
                        <h3 className="text-base font-bold text-gray-900 truncate pr-4 group-hover:text-indigo-600 transition-colors">
                          {ticket.title}
                        </h3>
                        <span className={`shrink-0 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold border ${getStatusColor(ticket.status)}`}>
                          {ticket.status}
                        </span>
                      </div>

                      <p className="text-sm text-gray-600 line-clamp-2 mb-3 leading-relaxed">
                        {ticket.description}
                      </p>

                      <div className="flex items-center gap-4 text-xs text-gray-500 font-medium pt-2 border-t border-dashed border-gray-100 mt-2">
                        <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
                          #{ticket.ticketnumber}
                        </span>
                        <span>
                          Created {new Date(ticket.createdate).toLocaleDateString()}
                        </span>
                        {ticket.assigned_tech_id && (
                          <span className="flex items-center text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full">
                            <span className="mr-1">👤</span>
                            {ticket.assigned_tech_name || ticket.assigned_tech_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </Link>
              ))
            )}
          </div>
        )}

        {/* Pagination (Simple Implementation) */}
        {!isLoading && tickets.length > 0 && (
          <div className="p-4 border-t border-gray-100 flex justify-between items-center bg-gray-50/30">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm"
            >
              Previous
            </button>
            <span className="text-xs text-gray-500 font-medium uppercase tracking-wider">
              Page {page + 1}
            </span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={!data?.has_more} // Assuming API returns this
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default TicketList;
