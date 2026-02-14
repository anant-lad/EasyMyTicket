
import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { format } from 'date-fns';
import {
    ClockIcon,
    ExclamationTriangleIcon,
    CalendarDaysIcon,
    CalendarIcon,
    CheckCircleIcon,
    SparklesIcon,
    PlayCircleIcon,
    PauseCircleIcon,
    StopCircleIcon
} from '@heroicons/react/24/outline';

interface TicketBoardProps {
    tickets: any[];
    role: 'user' | 'technician';
    viewMode?: 'deadline' | 'status';
}

const TicketBoard: React.FC<TicketBoardProps> = ({ tickets, role, viewMode = 'deadline' }) => {
    const now = new Date();

    const columns = useMemo(() => {
        if (viewMode === 'deadline') {
            const overdue = tickets.filter(t => {
                if (!t.duedatetime || t.status === 'Closed') return false;
                return new Date(t.duedatetime) < now;
            });

            const dueSoon = tickets.filter(t => {
                if (!t.duedatetime || t.status === 'Closed') return false;
                const dueDate = new Date(t.duedatetime);
                const diffHours = (dueDate.getTime() - now.getTime()) / (1000 * 60 * 60);
                return dueDate >= now && diffHours <= 24;
            });

            const upcoming = tickets.filter(t => {
                if (t.status === 'Closed') return false;
                if (!t.duedatetime) return true;
                const dueDate = new Date(t.duedatetime);
                const diffHours = (dueDate.getTime() - now.getTime()) / (1000 * 60 * 60);
                return diffHours > 24;
            });

            return [
                { id: 'overdue', title: 'Overdue', icon: ExclamationTriangleIcon, color: 'red', tickets: overdue },
                { id: 'due-soon', title: 'Due in 24 Hours', icon: CalendarDaysIcon, color: 'amber', tickets: dueSoon },
                { id: 'upcoming', title: 'Upcoming & Others', icon: CalendarIcon, color: 'blue', tickets: upcoming },
            ];
        } else {
            // Status View for Technicians
            const newTickets = tickets.filter(t => t.status === 'New' || t.status === 'Open');
            const toDoTickets = tickets.filter(t => t.status === 'TO DO');
            const inProgress = tickets.filter(t => t.status === 'In Progress');
            const resolutionPlanned = tickets.filter(t => t.status === 'Resolution Planned' || t.status === 'On Hold' || t.status === 'Pending');

            return [
                { id: 'new', title: 'New Requests', icon: SparklesIcon, color: 'blue', tickets: newTickets },
                { id: 'todo', title: 'To Do', icon: PlayCircleIcon, color: 'indigo', tickets: toDoTickets },
                { id: 'in-progress', title: 'In Progress', icon: CheckCircleIcon, color: 'purple', tickets: inProgress },
                { id: 'resolution-planned', title: 'Resolution Planned', icon: ClockIcon, color: 'emerald', tickets: resolutionPlanned },
            ];
        }
    }, [tickets, viewMode, now]);

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 h-[calc(100vh-340px)] min-h-[500px]">
            {columns.map(col => (
                <div key={col.id} className={`
                    rounded-2xl p-4 flex flex-col h-full border border-white/40 shadow-xl backdrop-blur-xl relative overflow-hidden group
                    ${col.color === 'red' ? 'bg-gradient-to-b from-red-50/80 to-red-100/30 border-red-200/50' : ''}
                    ${col.color === 'amber' ? 'bg-gradient-to-b from-amber-50/80 to-amber-100/30 border-amber-200/50' : ''}
                    ${col.color === 'blue' ? 'bg-gradient-to-b from-blue-50/80 to-blue-100/30 border-blue-200/50' : ''}
                    ${col.color === 'indigo' ? 'bg-gradient-to-b from-indigo-50/80 to-indigo-100/30 border-indigo-200/50' : ''}
                    ${col.color === 'purple' ? 'bg-gradient-to-b from-purple-50/80 to-purple-100/30 border-purple-200/50' : ''}
                    ${col.color === 'gray' ? 'bg-gradient-to-b from-gray-50/80 to-gray-100/30 border-gray-200/50' : ''}
                `}>
                    {/* Header */}
                    <div className="flex items-center justify-between mb-4 relative z-10">
                        <h3 className={`font-bold text-base flex items-center
                            ${col.color === 'red' ? 'text-red-700' : ''}
                            ${col.color === 'amber' ? 'text-amber-700' : ''}
                            ${col.color === 'blue' ? 'text-blue-700' : ''}
                            ${col.color === 'indigo' ? 'text-indigo-700' : ''}
                            ${col.color === 'purple' ? 'text-purple-700' : ''}
                            ${col.color === 'gray' ? 'text-gray-700' : ''}
                        `}>
                            <col.icon className="w-5 h-5 mr-2 opacity-80" />
                            {col.title}
                        </h3>
                        <span className={`
                            text-xs font-bold px-2.5 py-1 rounded-full shadow-sm backdrop-blur-md
                            ${col.color === 'red' ? 'bg-red-100/80 text-red-800' : ''}
                            ${col.color === 'amber' ? 'bg-amber-100/80 text-amber-800' : ''}
                            ${col.color === 'blue' ? 'bg-blue-100/80 text-blue-800' : ''}
                            ${col.color === 'indigo' ? 'bg-indigo-100/80 text-indigo-800' : ''}
                            ${col.color === 'purple' ? 'bg-purple-100/80 text-purple-800' : ''}
                            ${col.color === 'gray' ? 'bg-gray-100/80 text-gray-800' : ''}
                        `}>
                            {col.tickets.length}
                        </span>
                    </div>

                    {/* Cards Container */}
                    <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar space-y-3 relative z-10">
                        {col.tickets.length > 0 ? (
                            col.tickets.map((ticket: any) => (
                                <Link
                                    key={ticket.ticketnumber}
                                    to={`/${role}/tickets/${ticket.ticketnumber}`}
                                    className="
                                        block bg-white/70 backdrop-blur-sm p-4 rounded-xl border border-white/50 shadow-sm 
                                        hover:shadow-lg hover:-translate-y-1 hover:bg-white/90 transition-all duration-300
                                        group/card
                                    "
                                >
                                    <div className="flex justify-between items-start mb-2">
                                        <span className="text-[10px] font-mono font-medium text-gray-500 bg-gray-100/50 px-1.5 py-0.5 rounded tracking-wider">
                                            {ticket.ticketnumber}
                                        </span>
                                        {/* Assigned Technician Avatar */}
                                        {ticket.assigned_tech_id && (
                                            <div className="flex items-center gap-1.5" title={`Assigned to ${ticket.assigned_tech_name || ticket.assigned_tech_id}`}>
                                                {/* Only show label on hover to keep it clean */}
                                                <span className="text-[10px] text-gray-500 font-medium opacity-0 group-hover/card:opacity-100 transition-opacity whitespace-nowrap hidden sm:inline-block">
                                                    {ticket.assigned_tech_name || ticket.assigned_tech_id}
                                                </span>
                                                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-[10px] font-bold text-white shadow-md shadow-indigo-500/20 ring-2 ring-white">
                                                    {(ticket.assigned_tech_name || ticket.assigned_tech_id).substring(0, 2).toUpperCase()}
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    <h4 className="font-semibold text-gray-900 mb-1.5 line-clamp-2 leading-snug group-hover/card:text-indigo-600 transition-colors">
                                        {ticket.title}
                                    </h4>

                                    <div className="flex justify-between items-end mt-3">
                                        <div className="flex flex-col gap-1">
                                            {/* Priority Badge */}
                                            <span className={`
                                                inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider w-fit
                                                ${ticket.priority === 'High' ? 'bg-red-50 text-red-600 border border-red-100' :
                                                    ticket.priority === 'Medium' ? 'bg-amber-50 text-amber-600 border border-amber-100' :
                                                        'bg-green-50 text-green-600 border border-green-100'}
                                            `}>
                                                {ticket.priority}
                                            </span>

                                            {/* Date / Status */}
                                            <span className={`text-xs flex items-center mt-1 
                                                ${ticket.duedatetime && new Date(ticket.duedatetime) < new Date() ? 'text-red-500 font-medium' : 'text-gray-400'}
                                            `}>
                                                <ClockIcon className="w-3.5 h-3.5 mr-1" />
                                                {ticket.duedatetime ? format(new Date(ticket.duedatetime), 'MMM d, HH:mm') : 'No due date'}
                                            </span>
                                        </div>
                                    </div>
                                </Link>
                            ))
                        ) : (
                            <div className="text-center py-12 flex flex-col items-center justify-center text-gray-400/60 border-2 border-dashed border-white/30 rounded-xl">
                                <col.icon className="w-8 h-8 mb-2 opacity-30" />
                                <span className="text-sm font-medium">Empty</span>
                            </div>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
};

export default TicketBoard;
