import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizationService } from '../../services/organizations';
import toast from 'react-hot-toast';
import {
    BuildingOfficeIcon,
    PlusIcon,
} from '@heroicons/react/24/outline';
import { Organization } from '../../types';

const OrganizationManagement: React.FC = () => {
    const queryClient = useQueryClient();
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [newOrg, setNewOrg] = useState({
        companyid: '',
        company_name: '',
        company_email: '',
        contact_phone: '',
        address: '',
    });

    const { data, isLoading } = useQuery({
        queryKey: ['organizations'],
        queryFn: () => organizationService.getOrganizations({ limit: 100 }),
    });

    const organizations = data?.organizations || [];

    const createOrgMutation = useMutation({
        mutationFn: (orgData: any) => organizationService.createOrganization(orgData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['organizations'] });
            toast.success('Organization created successfully');
            setIsModalOpen(false);
            setNewOrg({
                companyid: '',
                company_name: '',
                company_email: '',
                contact_phone: '',
                address: '',
            });
        },
        onError: (error: any) => {
            toast.error(error.message || 'Failed to create organization');
        },
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        createOrgMutation.mutate(newOrg);
    };

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Organization Management</h1>
                    <p className="text-gray-500 mt-1">Manage client organizations and details</p>
                </div>
                <button
                    onClick={() => setIsModalOpen(true)}
                    className="flex items-center px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                >
                    <PlusIcon className="w-5 h-5 mr-2" />
                    Add Organization
                </button>
            </div>

            <div className="bg-white rounded-lg shadow overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Organization
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                ID
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Contact
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Address
                            </th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {isLoading ? (
                            <tr>
                                <td colSpan={4} className="px-6 py-12 text-center">
                                    <div className="flex justify-center">
                                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                                    </div>
                                </td>
                            </tr>
                        ) : organizations.length === 0 ? (
                            <tr>
                                <td colSpan={4} className="px-6 py-12 text-center text-gray-500">
                                    No organizations found
                                </td>
                            </tr>
                        ) : (
                            organizations.map((org: Organization) => (
                                <tr key={org.id} className="hover:bg-gray-50">
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="flex items-center">
                                            <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                                                <BuildingOfficeIcon className="w-6 h-6" />
                                            </div>
                                            <div className="ml-4">
                                                <div className="text-sm font-medium text-gray-900">{org.company_name}</div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                        {org.companyid}
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm text-gray-900">{org.company_email}</div>
                                        <div className="text-sm text-gray-500">{org.contact_phone}</div>
                                    </td>
                                    <td className="px-6 py-4 text-sm text-gray-500 truncate max-w-xs">
                                        {org.address || '-'}
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {isModalOpen && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
                        <h2 className="text-xl font-bold mb-4">Add New Organization</h2>
                        <form onSubmit={handleSubmit} className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Company ID</label>
                                <input
                                    type="text"
                                    required
                                    value={newOrg.companyid}
                                    onChange={(e) => setNewOrg({ ...newOrg, companyid: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                    placeholder="e.g., ORG001"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Company Name</label>
                                <input
                                    type="text"
                                    required
                                    value={newOrg.company_name}
                                    onChange={(e) => setNewOrg({ ...newOrg, company_name: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Email</label>
                                <input
                                    type="email"
                                    value={newOrg.company_email}
                                    onChange={(e) => setNewOrg({ ...newOrg, company_email: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Phone</label>
                                <input
                                    type="text"
                                    value={newOrg.contact_phone}
                                    onChange={(e) => setNewOrg({ ...newOrg, contact_phone: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Address</label>
                                <textarea
                                    value={newOrg.address}
                                    onChange={(e) => setNewOrg({ ...newOrg, address: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                    rows={3}
                                />
                            </div>
                            <div className="flex justify-end gap-3 mt-6">
                                <button
                                    type="button"
                                    onClick={() => setIsModalOpen(false)}
                                    className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={createOrgMutation.isPending}
                                    className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50"
                                >
                                    {createOrgMutation.isPending ? 'Creating...' : 'Create Organization'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default OrganizationManagement;
