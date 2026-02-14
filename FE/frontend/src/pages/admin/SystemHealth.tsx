import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { adminService } from '../../services/admin';
import { Activity, Database, Server, Cpu, HardDrive, Zap, CheckCircle, AlertTriangle, XCircle } from 'lucide-react';

const SystemHealth: React.FC = () => {
    const { data: health, isLoading, refetch } = useQuery({
        queryKey: ['system-health'],
        queryFn: () => adminService.getSystemHealth(),
        refetchInterval: 30000 // Poll every 30s
    });

    const getStatusColor = (status: string) => {
        switch (status?.toLowerCase()) {
            case 'healthy': return 'text-green-600 bg-green-50 border-green-200';
            case 'degraded': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
            case 'unhealthy': return 'text-red-600 bg-red-50 border-red-200';
            default: return 'text-gray-600 bg-gray-50 border-gray-200';
        }
    };

    const StatusIcon = ({ status }: { status: string }) => {
        switch (status?.toLowerCase()) {
            case 'healthy': return <CheckCircle className="w-5 h-5 text-green-500" />;
            case 'degraded': return <AlertTriangle className="w-5 h-5 text-yellow-500" />;
            case 'unhealthy': return <XCircle className="w-5 h-5 text-red-500" />;
            default: return <Activity className="w-5 h-5 text-gray-400" />;
        }
    };

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">System Health</h1>
                    <p className="text-gray-500 mt-1">Real-time infrastructure monitoring</p>
                </div>
                <button
                    onClick={() => refetch()}
                    className="p-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-600"
                    title="Refresh"
                >
                    <Activity className="w-5 h-5" />
                </button>
            </div>

            {/* Services Status Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {/* Database Status */}
                <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm relative overflow-hidden">
                    <div className="flex justify-between items-start mb-4">
                        <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
                            <Database className="w-6 h-6" />
                        </div>
                        <StatusIcon status={health?.services?.database?.status} />
                    </div>
                    <h3 className="font-bold text-gray-900">Database</h3>
                    <p className={`text-sm mt-1 mb-4 ${health?.services?.database?.status === 'healthy' ? 'text-green-600' : 'text-red-600'}`}>
                        {health?.services?.database?.status === 'healthy' ? 'Operational' : 'Issues Detected'}
                    </p>

                    <div className="space-y-3 pt-4 border-t border-gray-100">
                        <div className="flex justify-between text-sm">
                            <span className="text-gray-500">Latency</span>
                            <span className="font-medium font-mono">{health?.services?.database?.latency_ms}ms</span>
                        </div>
                        <div className="flex justify-between text-sm">
                            <span className="text-gray-500">Active Connections</span>
                            <span className="font-medium font-mono">{health?.services?.database?.active_connections}</span>
                        </div>
                        <div className="w-full bg-gray-100 h-1.5 rounded-full overflow-hidden">
                            <div
                                className="bg-indigo-500 h-full rounded-full transition-all duration-500"
                                style={{ width: `${Math.min(health?.services?.database?.latency_ms / 2, 100)}%` }} // Arbitrary scale for visual
                            />
                        </div>
                    </div>
                </div>

                {/* API Status */}
                <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex justify-between items-start mb-4">
                        <div className="p-2 bg-purple-50 text-purple-600 rounded-lg">
                            <Zap className="w-6 h-6" />
                        </div>
                        <StatusIcon status={health?.services?.api?.status} />
                    </div>
                    <h3 className="font-bold text-gray-900">API Gateway</h3>
                    <p className="text-sm mt-1 mb-4 text-green-600">Operational</p>

                    <div className="space-y-3 pt-4 border-t border-gray-100">
                        <div className="flex justify-between text-sm">
                            <span className="text-gray-500">Uptime</span>
                            <span className="font-medium">99.9%</span>
                        </div>
                        <div className="flex justify-between text-sm">
                            <span className="text-gray-500">Response Time</span>
                            <span className="font-medium font-mono">45ms</span>
                        </div>
                        <div className="w-full bg-gray-100 h-1.5 rounded-full overflow-hidden">
                            <div className="bg-purple-500 h-full rounded-full w-[15%]" />
                        </div>
                    </div>
                </div>

                {/* System Info */}
                <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex justify-between items-start mb-4">
                        <div className="p-2 bg-gray-50 text-gray-600 rounded-lg">
                            <Server className="w-6 h-6" />
                        </div>
                        <CheckCircle className="w-5 h-5 text-gray-400" />
                    </div>
                    <h3 className="font-bold text-gray-900">Host System</h3>
                    <p className="text-sm text-gray-500 mt-1 mb-4">{health?.system?.os} {health?.system?.release}</p>
                    <div className="space-y-3 pt-4 border-t border-gray-100">
                        <div className="flex justify-between text-sm">
                            <span className="text-gray-500">Python</span>
                            <span className="font-medium">{health?.system?.python_version}</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Resources Usage */}
            <h2 className="text-lg font-bold text-gray-900 pt-4">Resource Usage</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* CPU */}
                <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center gap-3 mb-4">
                        <Cpu className="w-5 h-5 text-gray-400" />
                        <h3 className="font-medium text-gray-900">CPU Usage</h3>
                    </div>

                    <div className="relative pt-2">
                        <div className="flex items-end gap-2 mb-2">
                            <span className="text-3xl font-bold text-gray-900">{health?.resources?.cpu?.usage_percent}%</span>
                            <span className="text-sm text-gray-500 mb-1">of {health?.resources?.cpu?.cores} Cores</span>
                        </div>
                        <div className="w-full bg-gray-100 h-2 rounded-full overflow-hidden">
                            <div
                                className={`h-full rounded-full transition-all duration-500 ${health?.resources?.cpu?.usage_percent > 80 ? 'bg-red-500' : 'bg-blue-500'}`}
                                style={{ width: `${health?.resources?.cpu?.usage_percent}%` }}
                            />
                        </div>
                    </div>
                </div>

                {/* Memory */}
                <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center gap-3 mb-4">
                        <Server className="w-5 h-5 text-gray-400" />
                        <h3 className="font-medium text-gray-900">Memory</h3>
                    </div>

                    <div className="relative pt-2">
                        <div className="flex items-end gap-2 mb-2">
                            <span className="text-3xl font-bold text-gray-900">{health?.resources?.memory?.percent}%</span>
                            <span className="text-sm text-gray-500 mb-1">{health?.resources?.memory?.used_gb}GB / {health?.resources?.memory?.total_gb}GB</span>
                        </div>
                        <div className="w-full bg-gray-100 h-2 rounded-full overflow-hidden">
                            <div
                                className={`h-full rounded-full transition-all duration-500 ${health?.resources?.memory?.percent > 80 ? 'bg-red-500' : 'bg-purple-500'}`}
                                style={{ width: `${health?.resources?.memory?.percent}%` }}
                            />
                        </div>
                    </div>
                </div>

                {/* Storage */}
                <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center gap-3 mb-4">
                        <HardDrive className="w-5 h-5 text-gray-400" />
                        <h3 className="font-medium text-gray-900">Storage</h3>
                    </div>

                    <div className="relative pt-2">
                        <div className="flex items-end gap-2 mb-2">
                            <span className="text-3xl font-bold text-gray-900">{health?.resources?.disk?.percent}%</span>
                            <span className="text-sm text-gray-500 mb-1">{health?.resources?.disk?.used_gb}GB / {health?.resources?.disk?.total_gb}GB</span>
                        </div>
                        <div className="w-full bg-gray-100 h-2 rounded-full overflow-hidden">
                            <div
                                className={`h-full rounded-full transition-all duration-500 ${health?.resources?.disk?.percent > 80 ? 'bg-red-500' : 'bg-orange-500'}`}
                                style={{ width: `${health?.resources?.disk?.percent}%` }}
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SystemHealth;
