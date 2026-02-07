import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { technicianService } from '../../services/technicians';
import toast from 'react-hot-toast';
import {
    UserGroupIcon,
    FunnelIcon,
    PlusIcon,
} from '@heroicons/react/24/outline';

const TechnicianManagement: React.FC = () => {
    const queryClient = useQueryClient();
    const [filters, setFilters] = useState({
        available: '',
        skills: '',
        min_solved: '',
    });
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [newTech, setNewTech] = useState({
        tech_id: '',
        tech_name: '',
        tech_mail: '',
        tech_password: '',
        skills: '',
        companyid: '0001',
    });

    const { data, isLoading } = useQuery({
        queryKey: ['technicians', filters],
        queryFn: () => {
            const params: any = { limit: 100 };
            if (filters.available === 'true') params.available = true;
            if (filters.available === 'false') params.available = false;
            if (filters.skills) params.skills = filters.skills;
            if (filters.min_solved) params.min_solved = parseInt(filters.min_solved);
            return technicianService.getTechnicians(params);
        },
    });

    const technicians = data?.data || [];

    const updateAvailabilityMutation = useMutation({
        mutationFn: ({ techId, status }: { techId: string; status: string }) =>
            technicianService.updateAvailability(techId, status),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['technicians'] });
            toast.success('Availability updated');
        },
    });

    const addTechnicianMutation = useMutation({
        mutationFn: (newTechData: any) => technicianService.addTechnicians([newTechData]),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['technicians'] });
            toast.success('Technician added successfully');
            setIsModalOpen(false);
            setNewTech({
                tech_id: '',
                tech_name: '',
                tech_mail: '',
                tech_password: '',
                skills: '',
                companyid: '0001',
            });
        },
        onError: (error: any) => {
            toast.error(error.message || 'Failed to add technician');
        },
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        addTechnicianMutation.mutate(newTech);
    };

    const availabilityOptions = [
        'available',
        'on_leave',
        'half_day',
        'wfh',
        'offline',
        'out_of_office',
        'away',
    ];

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Technician Management</h1>
                    <p className="text-gray-500 mt-1">Manage technician profiles, availability, and workload</p>
                </div>
                <button
                    onClick={() => setIsModalOpen(true)}
                    className="flex items-center px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                >
                    <PlusIcon className="w-5 h-5 mr-2" />
                    Add Technician
                </button>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
                {/* Filters */}
                <div className="flex flex-col md:flex-row gap-4 mb-6">
                    <div className="flex-1 relative">
                        <input
                            type="text"
                            placeholder="Search skills..."
                            value={filters.skills}
                            onChange={(e) => setFilters({ ...filters, skills: e.target.value })}
                            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                        />
                    </div>
                    <select
                        value={filters.available}
                        onChange={(e) => setFilters({ ...filters, available: e.target.value })}
                        className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary"
                    >
                        <option value="">All Status</option>
                        <option value="true">Available</option>
                        <option value="false">Unavailable</option>
                    </select>
                </div>

                {/* Table */}
                <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Technician
                                </th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Status
                                </th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Workload
                                </th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Skills
                                </th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Availability
                                </th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {isLoading ? (
                                <tr>
                                    <td colSpan={5} className="px-6 py-12 text-center">
                                        <div className="flex justify-center">
                                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                                        </div>
                                    </td>
                                </tr>
                            ) : technicians.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                                        No technicians found
                                    </td>
                                </tr>
                            ) : (
                                technicians.map((tech: any) => (
                                    <tr key={tech.tech_id} className="hover:bg-gray-50">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center">
                                                <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold">
                                                    {tech.tech_name.charAt(0)}
                                                </div>
                                                <div className="ml-4">
                                                    <div className="text-sm font-medium text-gray-900">{tech.tech_name}</div>
                                                    <div className="text-sm text-gray-500">{tech.tech_mail}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${tech.available ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                                                }`}>
                                                {tech.available ? 'Active' : 'Unavailable'}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="text-sm text-gray-900">{tech.current_workload} tickets</div>
                                            <div className="text-xs text-gray-500">{tech.solved_tickets} solved</div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex flex-wrap gap-1">
                                                {tech.skills?.split(',').slice(0, 3).map((skill: string, idx: number) => (
                                                    <span key={idx} className="px-2 py-0.5 bg-gray-100 text-gray-700 text-xs rounded">
                                                        {skill.trim()}
                                                    </span>
                                                ))}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <select
                                                value={tech.availability || 'available'}
                                                onChange={(e) => updateAvailabilityMutation.mutate({
                                                    techId: tech.tech_id,
                                                    status: e.target.value
                                                })}
                                                className="text-sm border-gray-300 rounded-md shadow-sm focus:border-primary focus:ring focus:ring-primary focus:ring-opacity-50"
                                            >
                                                {availabilityOptions.map((opt) => (
                                                    <option key={opt} value={opt}>
                                                        {opt.replace('_', ' ')}
                                                    </option>
                                                ))}
                                            </select>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Add Technician Modal */}
            {isModalOpen && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6">
                        <h2 className="text-xl font-bold mb-4">Add New Technician</h2>
                        <form onSubmit={handleSubmit} className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Tech ID</label>
                                <input
                                    type="text"
                                    required
                                    value={newTech.tech_id}
                                    onChange={(e) => setNewTech({ ...newTech, tech_id: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Name</label>
                                <input
                                    type="text"
                                    required
                                    value={newTech.tech_name}
                                    onChange={(e) => setNewTech({ ...newTech, tech_name: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Email</label>
                                <input
                                    type="email"
                                    required
                                    value={newTech.tech_mail}
                                    onChange={(e) => setNewTech({ ...newTech, tech_mail: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Password</label>
                                <input
                                    type="password"
                                    required
                                    value={newTech.tech_password}
                                    onChange={(e) => setNewTech({ ...newTech, tech_password: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700">Skills (comma separated)</label>
                                <input
                                    type="text"
                                    value={newTech.skills}
                                    onChange={(e) => setNewTech({ ...newTech, skills: e.target.value })}
                                    className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2"
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
                                    disabled={addTechnicianMutation.isPending}
                                    className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50"
                                >
                                    {addTechnicianMutation.isPending ? 'Adding...' : 'Add Technician'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default TechnicianManagement;
