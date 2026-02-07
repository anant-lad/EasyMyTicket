import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
    PieChart,
    Pie,
    Cell,
    LineChart,
    Line,
} from 'recharts';
import { ticketService } from '../../services/tickets';
import { technicianService } from '../../services/technicians';
import { useAuth } from '../../context/AuthContext';

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8'];

const Analytics: React.FC = () => {
    const { user } = useAuth();

    const { data: ticketsData, isLoading: ticketsLoading } = useQuery({
        queryKey: ['all-tickets-analytics'],
        queryFn: () => ticketService.getTickets(),
    });

    const { data: techniciansData, isLoading: techsLoading } = useQuery({
        queryKey: ['technicians-analytics'],
        queryFn: () => technicianService.getTechnicians({ limit: 100 }),
    });

    if (ticketsLoading || techsLoading) {
        return (
            <div className="flex justify-center items-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        );
    }

    const tickets = ticketsData?.tickets || [];
    const technicians = techniciansData?.data || [];

    // Data Processing

    // Status Distribution
    const statusCounts = tickets.reduce((acc: any, ticket: any) => {
        acc[ticket.status] = (acc[ticket.status] || 0) + 1;
        return acc;
    }, {});

    const statusData = Object.keys(statusCounts).map((status) => ({
        name: status.replace('_', ' ').toUpperCase(),
        value: statusCounts[status],
    }));

    // Priority Distribution
    const priorityCounts = tickets.reduce((acc: any, ticket: any) => {
        acc[ticket.priority] = (acc[ticket.priority] || 0) + 1;
        return acc;
    }, {});

    const priorityData = Object.keys(priorityCounts).map((priority) => ({
        name: priority.toUpperCase(),
        value: priorityCounts[priority],
    }));

    // Technician Performance (Resolved Tickets)
    const techPerformance = technicians
        .sort((a: any, b: any) => b.solved_tickets - a.solved_tickets)
        .slice(0, 10)
        .map((tech: any) => ({
            name: tech.tech_name,
            solved: tech.solved_tickets,
            workload: tech.current_workload,
        }));

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Analytics Dashboard</h1>
                    <p className="text-gray-500 mt-1">Overview of ticket metrics and team performance</p>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Status Breakdown */}
                <div className="bg-white p-6 rounded-lg shadow">
                    <h3 className="text-lg font-semibold text-gray-800 mb-4">Ticket Status Distribution</h3>
                    <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={statusData}
                                    cx="50%"
                                    cy="50%"
                                    labelLine={false}
                                    label={({ name, percent }: { name?: string | number; percent?: number }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}
                                    outerRadius={80}
                                    fill="#8884d8"
                                    dataKey="value"
                                >
                                    {statusData.map((entry: any, index: number) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Priority Breakdown */}
                <div className="bg-white p-6 rounded-lg shadow">
                    <h3 className="text-lg font-semibold text-gray-800 mb-4">Tickets by Priority</h3>
                    <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={priorityData}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" />
                                <YAxis />
                                <Tooltip />
                                <Legend />
                                <Bar dataKey="value" fill="#8884d8" name="Count" />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Technician Performance */}
                <div className="bg-white p-6 rounded-lg shadow lg:col-span-2">
                    <h3 className="text-lg font-semibold text-gray-800 mb-4">Top Technicians Performance</h3>
                    <div className="h-80">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={techPerformance}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" />
                                <YAxis />
                                <Tooltip />
                                <Legend />
                                <Bar dataKey="solved" fill="#82ca9d" name="Solved Tickets" />
                                <Bar dataKey="workload" fill="#8884d8" name="Current Workload" />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Analytics;
