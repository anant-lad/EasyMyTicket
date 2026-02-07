import React, { useState, useEffect } from 'react';
import { organizationService } from '../../services/organizations';
import api from '../../services/api';
import { Organization } from '../../types';
import toast from 'react-hot-toast';

const SuperAdminHome: React.FC = () => {
    const [organizations, setOrganizations] = useState<Organization[]>([]);
    const [loading, setLoading] = useState(true);
    const [showAddModal, setShowAddModal] = useState(false);
    const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);

    // Form state
    const [newOrg, setNewOrg] = useState({
        company_name: '',
        company_email: '',
        contact_phone: '',
        address: '',
        admin_name: '',
        admin_email: '',
        admin_password: ''
    });

    useEffect(() => {
        fetchOrganizations();
    }, []);

    const fetchOrganizations = async () => {
        try {
            setLoading(true);
            const data = await organizationService.getOrganizations({ limit: 100 });
            setOrganizations(data.organizations || []);
        } catch (error) {
            toast.error('Failed to load organizations');
        } finally {
            setLoading(false);
        }
    };

    const handleUpdateOrg = async (companyId: string, data: any) => {
        try {
            await organizationService.updateOrganization(companyId, data);
            toast.success('Organization updated');
            fetchOrganizations();
            if (selectedOrg && selectedOrg.companyid === companyId) {
                setSelectedOrg({ ...selectedOrg, ...data });
            }
        } catch (error) {
            toast.error('Failed to update organization');
        }
    };

    const handleDeleteOrg = async (companyId: string) => {
        if (!window.confirm("Are you sure you want to delete this organization? This action cannot be undone.")) return;

        try {
            await organizationService.deleteOrganization(companyId);
            toast.success('Organization deleted');
            setSelectedOrg(null);
            fetchOrganizations();
        } catch (error) {
            toast.error('Failed to delete organization');
        }
    };

    const handleCreateOrg = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            // 1. Create Organization
            const orgResponse = await organizationService.createOrganization({
                company_name: newOrg.company_name,
                company_email: newOrg.company_email,
                contact_phone: newOrg.contact_phone,
                address: newOrg.address
            });

            if (orgResponse.success && orgResponse.companyid) {
                // 2. Create Initial Org Admin
                await api.post('/database/users', [{
                    user_id: newOrg.admin_email,
                    user_name: newOrg.admin_name,
                    user_mail: newOrg.admin_email,
                    user_password: newOrg.admin_password,
                    role: 'org_admin',
                    companyid: orgResponse.companyid
                }]);

                toast.success(`Organization "${newOrg.company_name}" and Admin created!`);
                setShowAddModal(false);
                setNewOrg({
                    company_name: '', company_email: '', contact_phone: '', address: '',
                    admin_name: '', admin_email: '', admin_password: ''
                });
                fetchOrganizations();
            }
        } catch (error: any) {
            console.error(error);
            toast.error(error.response?.data?.detail || 'Failed to create organization');
        }
    };

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="mb-8 flex justify-between items-center">
                <div>
                    <h2 className="text-3xl font-bold text-gray-900 tracking-tight">Organizations</h2>
                    <p className="text-gray-500 mt-2 flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                        Manage your SaaS tenants and subscriptions
                    </p>
                </div>
                <button
                    onClick={() => setShowAddModal(true)}
                    className="
                        bg-gray-900 text-white px-5 py-2.5 rounded-xl hover:bg-gray-800 
                        transition-all hover:shadow-lg hover:-translate-y-0.5 flex items-center font-medium
                    "
                >
                    <span className="mr-2 text-xl leading-none">+</span> Add Organization
                </button>
            </div>

            {loading ? (
                <div className="flex justify-center py-20">
                    <div className="animate-spin rounded-full h-12 w-12 border-4 border-gray-200 border-t-indigo-600"></div>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {organizations.map((org) => (
                        <div key={org.companyid} className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 hover:shadow-xl hover:border-indigo-100 transition-all duration-300 group relative overflow-hidden">
                            {/* Decorative background blob */}
                            <div className="absolute top-0 right-0 w-32 h-32 bg-gray-50 rounded-full -mr-16 -mt-16 group-hover:bg-indigo-50 transition-colors duration-500"></div>

                            <div className="relative z-10 flex justify-between items-start mb-6">
                                <div>
                                    <h3 className="text-xl font-bold text-gray-900 group-hover:text-indigo-600 transition-colors">{org.company_name}</h3>
                                    <div className="flex items-center gap-2 mt-1">
                                        <p className="text-xs font-mono text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">#{org.companyid}</p>
                                    </div>
                                </div>
                                <div className={`px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${org.status === 'disabled'
                                    ? 'bg-red-50 text-red-600 border border-red-100'
                                    : 'bg-green-50 text-green-600 border border-green-100'
                                    }`}>
                                    {org.status || 'Active'}
                                </div>
                            </div>

                            <div className="space-y-4 text-sm text-gray-600 mb-8">
                                <div className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 transition-colors">
                                    <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-gray-500">
                                        📧
                                    </div>
                                    <span className="truncate flex-1 font-medium">{org.company_email || 'N/A'}</span>
                                </div>
                                <div className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 transition-colors">
                                    <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-gray-500">
                                        📱
                                    </div>
                                    <span className="truncate flex-1 font-medium">{org.contact_phone || 'N/A'}</span>
                                </div>
                            </div>

                            <div className="pt-4 border-t border-gray-50 flex justify-between items-center">
                                <span className={`
                                    px-3 py-1 text-xs font-bold rounded-lg border uppercase tracking-wider
                                    ${org.subscription_plan === 'enterprise' ? 'bg-purple-50 text-purple-700 border-purple-100' :
                                        org.subscription_plan === 'pro' ? 'bg-blue-50 text-blue-700 border-blue-100' :
                                            'bg-gray-50 text-gray-600 border-gray-100'}
                                `}>
                                    {org.subscription_plan ? org.subscription_plan.toUpperCase() : 'FREE PLAN'}
                                </span>
                                <button
                                    onClick={() => setSelectedOrg(org)}
                                    className="text-gray-900 text-sm font-bold hover:text-indigo-600 flex items-center gap-1 transition-colors"
                                >
                                    Manage <span className="text-lg leading-none">→</span>
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Add Organization Modal */}
            {showAddModal && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 animate-fadeIn">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="text-xl font-bold text-gray-900">New Organization</h3>
                            <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-gray-600">✕</button>
                        </div>
                        <form onSubmit={handleCreateOrg} className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Company Name</label>
                                <input
                                    type="text"
                                    required
                                    value={newOrg.company_name}
                                    onChange={e => setNewOrg({ ...newOrg, company_name: e.target.value })}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                                <input
                                    type="email"
                                    required
                                    value={newOrg.company_email}
                                    onChange={e => setNewOrg({ ...newOrg, company_email: e.target.value })}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
                                <input
                                    type="text"
                                    value={newOrg.contact_phone}
                                    onChange={e => setNewOrg({ ...newOrg, contact_phone: e.target.value })}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Address</label>
                                <textarea
                                    value={newOrg.address}
                                    onChange={e => setNewOrg({ ...newOrg, address: e.target.value })}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                                    rows={2}
                                />
                            </div>

                            <div className="border-t border-gray-200 pt-4 mt-4 bg-gray-50 -mx-6 px-6 pb-2">
                                <h4 className="text-sm font-bold text-gray-900 mb-3 uppercase tracking-wider">Initial Admin</h4>
                                <div className="space-y-3">
                                    <input
                                        type="text"
                                        required
                                        value={newOrg.admin_name}
                                        onChange={e => setNewOrg({ ...newOrg, admin_name: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        placeholder="Admin Name"
                                    />
                                    <input
                                        type="email"
                                        required
                                        value={newOrg.admin_email}
                                        onChange={e => setNewOrg({ ...newOrg, admin_email: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        placeholder="Admin Email"
                                    />
                                    <input
                                        type="password"
                                        required
                                        value={newOrg.admin_password}
                                        onChange={e => setNewOrg({ ...newOrg, admin_password: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        placeholder="Password"
                                    />
                                </div>
                            </div>

                            <div className="flex gap-3 mt-6">
                                <button
                                    type="button"
                                    onClick={() => setShowAddModal(false)}
                                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 font-medium"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium shadow-md"
                                >
                                    Create Organization
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Manage Organization Modal */}
            {selectedOrg && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto animate-fadeIn">
                        <div className="flex justify-between items-start mb-6 border-b border-gray-100 pb-4">
                            <div>
                                <h3 className="text-2xl font-bold text-gray-900">Manage Organization</h3>
                                <p className="text-gray-500 flex items-center mt-1">
                                    <span className="font-mono bg-gray-100 px-2 py-0.5 rounded text-xs mr-2">{selectedOrg.companyid}</span>
                                    {selectedOrg.company_name}
                                </p>
                            </div>
                            <button
                                onClick={() => setSelectedOrg(null)}
                                className="text-gray-400 hover:text-gray-600 p-1 hover:bg-gray-100 rounded-full"
                            >
                                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                            </button>
                        </div>

                        <div className="space-y-8">
                            {/* SaaS Controls */}
                            <div className="bg-indigo-50 p-5 rounded-xl border border-indigo-100 grid grid-cols-2 gap-6">
                                <div>
                                    <label className="block text-xs font-bold text-indigo-900 uppercase tracking-wider mb-2">Account Status</label>
                                    <select
                                        value={selectedOrg.status || 'active'}
                                        onChange={(e) => handleUpdateOrg(selectedOrg.companyid, { status: e.target.value })}
                                        className="w-full px-3 py-2 border border-indigo-200 rounded-lg focus:ring-2 focus:ring-indigo-500 bg-white"
                                    >
                                        <option value="active">🟢 Active</option>
                                        <option value="disabled">🔴 Disabled</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-indigo-900 uppercase tracking-wider mb-2">Subscription Tier</label>
                                    <select
                                        value={selectedOrg.subscription_plan || 'free'}
                                        onChange={(e) => handleUpdateOrg(selectedOrg.companyid, { subscription_plan: e.target.value })}
                                        className="w-full px-3 py-2 border border-indigo-200 rounded-lg focus:ring-2 focus:ring-indigo-500 bg-white"
                                    >
                                        <option value="free">Free Tier</option>
                                        <option value="pro">Pro Plan ($29/mo)</option>
                                        <option value="enterprise">Enterprise ($99/mo)</option>
                                    </select>
                                </div>
                            </div>

                            {/* Edit Details Form */}
                            <div className="space-y-4">
                                <h4 className="text-lg font-bold text-gray-900">Organization Details</h4>
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Company Name</label>
                                        <input
                                            type="text"
                                            value={selectedOrg.company_name}
                                            onChange={(e) => setSelectedOrg({ ...selectedOrg, company_name: e.target.value })}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Contact Email</label>
                                        <input
                                            type="email"
                                            value={selectedOrg.company_email}
                                            onChange={(e) => setSelectedOrg({ ...selectedOrg, company_email: e.target.value })}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
                                        <input
                                            type="text"
                                            value={selectedOrg.contact_phone}
                                            onChange={(e) => setSelectedOrg({ ...selectedOrg, contact_phone: e.target.value })}
                                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Address</label>
                                    <textarea
                                        value={selectedOrg.address}
                                        onChange={(e) => setSelectedOrg({ ...selectedOrg, address: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                                        rows={2}
                                    />
                                </div>
                                <div className="flex justify-end pt-2">
                                    <button
                                        onClick={() => handleUpdateOrg(selectedOrg.companyid, {
                                            company_name: selectedOrg.company_name,
                                            company_email: selectedOrg.company_email,
                                            contact_phone: selectedOrg.contact_phone,
                                            address: selectedOrg.address
                                        })}
                                        className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium shadow-sm"
                                    >
                                        Save Changes
                                    </button>
                                </div>
                            </div>

                            {/* Danger Zone */}
                            <div className="border-t border-red-100 pt-6">
                                <h4 className="text-sm font-bold text-red-700 mb-3 uppercase tracking-wider">Danger Zone</h4>
                                <div className="flex justify-between items-center bg-red-50 p-4 rounded-lg border border-red-100">
                                    <div>
                                        <p className="text-sm font-bold text-red-900">Delete Organization</p>
                                        <p className="text-xs text-red-600 mt-1">Permanently remove this organization and all its data.</p>
                                    </div>
                                    <button
                                        onClick={() => handleDeleteOrg(selectedOrg.companyid)}
                                        className="px-4 py-2 bg-white border border-red-200 text-red-600 rounded-lg hover:bg-red-50 font-medium hover:border-red-300 transition-colors"
                                    >
                                        Delete Forever
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SuperAdminHome;
