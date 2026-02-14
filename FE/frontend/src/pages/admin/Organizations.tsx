import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminService } from '../../services/admin';
import { Plus, Search, MoreVertical, Building2, Users, Receipt, AlertCircle, CheckCircle2, UserPlus, Database } from 'lucide-react';
import { toast } from 'react-hot-toast';

const Organizations: React.FC = () => {
    const queryClient = useQueryClient();
    const [searchTerm, setSearchTerm] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [selectedOrg, setSelectedOrg] = useState<any>(null);

    const { data: orgsData, isLoading } = useQuery({
        queryKey: ['organizations'],
        queryFn: () => adminService.getOrganizations({ limit: 100 })
    });

    const createOrgMutation = useMutation({
        mutationFn: (data: any) => adminService.createOrganization(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['organizations'] });
            setShowCreateModal(false);
            toast.success('Organization created successfully');
        },
        onError: (error: any) => {
            toast.error(error.message || 'Failed to create organization');
        }
    });

    const organizations = orgsData?.organizations || [];
    const filteredOrgs = organizations.filter((org: any) =>
        org.company_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        org.companyid.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Organizations</h1>
                    <p className="text-gray-500 mt-1">Manage your SaaS tenants and subscriptions</p>
                </div>
                <button
                    onClick={() => setShowCreateModal(true)}
                    className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors shadow-sm shadow-indigo-200"
                >
                    <Plus className="w-4 h-4" />
                    Add Organization
                </button>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center justify-between">
                        <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
                            <Building2 className="w-5 h-5" />
                        </div>
                        <span className="text-xs font-medium text-green-600 bg-green-50 px-2 py-0.5 rounded-full">+12%</span>
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-3">{orgsData?.total || 0}</p>
                    <p className="text-xs text-gray-500 mt-1">Total Organizations</p>
                </div>
                <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center justify-between">
                        <div className="p-2 bg-green-50 text-green-600 rounded-lg">
                            <CheckCircle2 className="w-5 h-5" />
                        </div>
                        <span className="text-xs font-medium text-gray-500">Active</span>
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-3">{organizations.filter((o: any) => o.status === 'Active').length}</p>
                    <p className="text-xs text-gray-500 mt-1">Active Accounts</p>
                </div>
                <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center justify-between">
                        <div className="p-2 bg-blue-50 text-blue-600 rounded-lg">
                            <Users className="w-5 h-5" />
                        </div>
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-3">--</p>
                    <p className="text-xs text-gray-500 mt-1">Total Users</p>
                </div>
                <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm">
                    <div className="flex items-center justify-between">
                        <div className="p-2 bg-purple-50 text-purple-600 rounded-lg">
                            <Receipt className="w-5 h-5" />
                        </div>
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-3">Free</p>
                    <p className="text-xs text-gray-500 mt-1">Most Common Plan</p>
                </div>
            </div>

            {/* Search and Filter */}
            <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm flex gap-4">
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-5 h-5" />
                    <input
                        type="text"
                        placeholder="Search organizations..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
                    />
                </div>
            </div>

            {/* Organizations Grid */}
            {isLoading ? (
                <div className="text-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mx-auto"></div>
                    <p className="text-gray-500 mt-4">Loading organizations...</p>
                </div>
            ) : filteredOrgs.length === 0 ? (
                <div className="text-center py-12 bg-white rounded-xl border border-gray-200 border-dashed">
                    <Building2 className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                    <h3 className="text-lg font-medium text-gray-900">No organizations found</h3>
                    <p className="text-gray-500 mt-1">Get started by creating a new organization.</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                    {filteredOrgs.map((org: any) => (
                        <div key={org.companyid} className="bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow p-6 group">
                            <div className="flex justify-between items-start mb-4">
                                <div className="flex items-center gap-3">
                                    <div className="w-12 h-12 rounded-lg bg-gray-100 flex items-center justify-center text-lg font-bold text-gray-600">
                                        {org.company_name.substring(0, 2).toUpperCase()}
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-gray-900 group-hover:text-indigo-600 transition-colors">{org.company_name}</h3>
                                        <span className="text-xs font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">#{org.companyid}</span>
                                    </div>
                                </div>
                                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${org.status === 'Active'
                                        ? 'bg-green-50 text-green-700 border-green-200'
                                        : 'bg-gray-100 text-gray-600 border-gray-200'
                                    }`}>
                                    {org.status || 'Active'}
                                </span>
                            </div>

                            <div className="space-y-3 mb-6">
                                <div className="flex items-center text-sm text-gray-600">
                                    <span className="w-6"><UserPlus className="w-4 h-4 text-gray-400" /></span>
                                    <span className="truncate">{org.admin_email || 'No admin email'}</span>
                                </div>
                                <div className="flex items-center text-sm text-gray-600">
                                    <span className="w-6"><Receipt className="w-4 h-4 text-gray-400" /></span>
                                    <span>{org.plan || 'Free'} Plan</span>
                                </div>
                                <div className="flex items-center text-sm text-gray-600">
                                    <span className="w-6"><Database className="w-4 h-4 text-gray-400" /></span>
                                    <span>Created {new Date(org.created_at).toLocaleDateString()}</span>
                                </div>
                            </div>

                            <div className="pt-4 border-t border-gray-100 flex justify-end gap-2">
                                <button className="text-sm font-medium text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors">
                                    Manage
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Create Modal */}
            {showCreateModal && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                    <div className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-gray-50/50">
                            <h3 className="text-lg font-bold text-gray-900">Add Organization</h3>
                            <button
                                onClick={() => setShowCreateModal(false)}
                                className="text-gray-400 hover:text-gray-600 hover:bg-gray-100 p-1 rounded-lg transition-colors"
                            >
                                <Plus className="w-5 h-5 rotate-45" />
                            </button>
                        </div>

                        <form onSubmit={(e) => {
                            e.preventDefault();
                            const formData = new FormData(e.currentTarget);
                            createOrgMutation.mutate({
                                company_name: formData.get('company_name'),
                                company_email: formData.get('company_email'),
                                contact_phone: formData.get('contact_phone'),
                                address: formData.get('address')
                            });
                        }} className="p-6 space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Company Name</label>
                                <input
                                    name="company_name"
                                    required
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                                    placeholder="e.g. Acme Corp"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Admin Email</label>
                                <input
                                    name="company_email"
                                    type="email"
                                    required
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                                    placeholder="admin@company.com"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Phone (Optional)</label>
                                <input
                                    name="contact_phone"
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                                    placeholder="+1 (555) 000-0000"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Address (Optional)</label>
                                <textarea
                                    name="address"
                                    rows={2}
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                                    placeholder="123 Business Rd..."
                                />
                            </div>

                            <div className="pt-4 flex gap-3">
                                <button
                                    type="button"
                                    onClick={() => setShowCreateModal(false)}
                                    className="flex-1 px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg font-medium transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={createOrgMutation.isPending}
                                    className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center"
                                >
                                    {createOrgMutation.isPending ? (
                                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    ) : 'Create Organization'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Organizations;
