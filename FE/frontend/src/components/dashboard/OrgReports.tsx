import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../ui/card";
import { Loader2, Download, Calendar } from "lucide-react";
import toast from 'react-hot-toast';

interface ReportData {
    status_distribution: { status: string; count: number }[];
    priority_distribution: { priority: string; count: number }[];
    category_distribution: { ticketcategory: string; count: number }[];
    top_technicians: { tech_name: string; resolved_count: number }[];
    recent_activity: any[];
}

const OrgReports: React.FC = () => {
    const { user } = useAuth();
    const [data, setData] = useState<ReportData | null>(null);
    const [loading, setLoading] = useState(true);
    const [dateRange, setDateRange] = useState('30days'); // '7days', '30days', '90days'

    useEffect(() => {
        const fetchReports = async () => {
            if (!user?.companyid) return;
            setLoading(true);
            try {
                // In a real implementation, we would pass dateRange as a param
                // const response = await api.get(`/organizations/${user.companyid}/reports`, { params: { range: dateRange } });
                // For now, reusing the analytics endpoint as a placeholder for data
                const response = await api.get(`/organizations/${user.companyid}/analytics`);
                if (response.data.success) {
                    setData(response.data.analytics);
                }
            } catch (err) {
                console.error(err);
                toast.error("Failed to load report data");
            } finally {
                setLoading(false);
            }
        };

        fetchReports();
    }, [user?.companyid, dateRange]);

    const handleDownloadCSV = () => {
        if (!data) return;

        // Simple CSV generation logic
        const header = ["Category", "Status", "Count"];
        const rows = data.status_distribution.map(item => ["Ticket Status", item.status, item.count]);
        data.priority_distribution.forEach(item => rows.push(["Priority", item.priority, item.count]));
        data.category_distribution.forEach(item => rows.push(["Category", item.ticketcategory, item.count]));
        data.top_technicians.forEach(item => rows.push(["Technician Performance", item.tech_name, item.resolved_count]));

        const csvContent = "data:text/csv;charset=utf-8,"
            + header.join(",") + "\n"
            + rows.map(e => e.join(",")).join("\n");

        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `org_report_${dateRange}_${new Date().toISOString().split('T')[0]}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    if (loading) return <div className="flex h-96 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-indigo-600" /></div>;
    if (!data) return <div>No data available</div>;

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight text-gray-900">Reports Center</h2>
                    <p className="text-gray-500 mt-1">Detailed breakdown of organization performance.</p>
                </div>
                <div className="flex gap-3">
                    <select
                        value={dateRange}
                        onChange={(e) => setDateRange(e.target.value)}
                        className="rounded-lg border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                    >
                        <option value="7days">Last 7 Days</option>
                        <option value="30days">Last 30 Days</option>
                        <option value="90days">Last 90 Days</option>
                    </select>
                    <button
                        onClick={handleDownloadCSV}
                        className="inline-flex items-center px-4 py-2 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700"
                    >
                        <Download className="-ml-1 mr-2 h-4 w-4" />
                        Export to CSV
                    </button>
                </div>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
                <Card>
                    <CardHeader>
                        <CardTitle>Technician Performance Report</CardTitle>
                        <CardDescription>Detailed resolve counts by technician</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="overflow-x-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                                <thead>
                                    <tr>
                                        <th className="px-6 py-3 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Technician</th>
                                        <th className="px-6 py-3 bg-gray-50 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Tickets Resolved</th>
                                    </tr>
                                </thead>
                                <tbody className="bg-white divide-y divide-gray-200">
                                    {data.top_technicians.map((tech, idx) => (
                                        <tr key={idx}>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{tech.tech_name}</td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">{tech.resolved_count}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Ticket Category Breakdown</CardTitle>
                        <CardDescription>Distribution of tickets across categories</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="space-y-4">
                            {data.category_distribution.map((cat, idx) => (
                                <div key={idx} className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
                                        <span className="text-sm font-medium text-gray-700">{cat.ticketcategory || 'Uncategorized'}</span>
                                    </div>
                                    <span className="text-sm text-gray-500">{cat.count} tickets</span>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Recent Ticket Activity Log</CardTitle>
                </CardHeader>
                <CardContent>
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead>
                            <tr>
                                <th className="px-6 py-3 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Ticket #</th>
                                <th className="px-6 py-3 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Title</th>
                                <th className="px-6 py-3 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                                <th className="px-6 py-3 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {data.recent_activity.map((ticket, idx) => (
                                <tr key={idx}>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-indigo-600">{ticket.ticketnumber}</td>
                                    <td className="px-6 py-4 text-sm text-gray-900 line-clamp-1 max-w-xs">{ticket.title}</td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                        {new Date(ticket.createdate).toLocaleDateString()}
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                                        <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                                            ${ticket.status === 'Closed' ? 'bg-green-100 text-green-800' :
                                                ticket.status === 'In Progress' ? 'bg-yellow-100 text-yellow-800' :
                                                    'bg-blue-100 text-blue-800'}`}>
                                            {ticket.status}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </CardContent>
            </Card>
        </div>
    );
};

export default OrgReports;
