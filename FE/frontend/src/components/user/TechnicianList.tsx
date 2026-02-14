import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { technicianService } from '../../services/technicians';
import { Technician } from '../../types';
import toast from 'react-hot-toast';

const TechnicianList: React.FC = () => {
    const { user } = useAuth();
    const [technicians, setTechnicians] = useState<Technician[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchTechnicians = async () => {
            if (!user?.companyid) return;

            try {
                const response = await technicianService.getTechnicians({ limit: 1000 });
                const allTechs = response.data || [];
                const orgTechs = allTechs.filter((t: any) => t.companyid === user.companyid);
                setTechnicians(orgTechs);
            } catch (error) {
                console.error('Failed to fetch technicians', error);
                toast.error('Could not load technician list');
            } finally {
                setLoading(false);
            }
        };

        fetchTechnicians();
    }, [user?.companyid]);

    if (loading) {
        return (
            <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-2xl font-bold text-gray-900">Technician Directory</h2>
                    <p className="text-sm text-gray-500 mt-1">
                        View available support staff for your organization.
                    </p>
                </div>
            </div>

            <div className="bg-white shadow-sm ring-1 ring-gray-900/5 sm:rounded-xl overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Skills</th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {technicians.length > 0 ? (
                            technicians.map((tech) => (
                                <tr key={tech.tech_id} className="hover:bg-gray-50 transition-colors">
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm font-medium text-gray-900">{tech.tech_name}</div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                        {tech.tech_mail}
                                    </td>
                                    <td className="px-6 py-4 text-sm text-gray-500 max-w-xs">
                                        {tech.skills ? (
                                            <div className="flex flex-wrap gap-1">
                                                {tech.skills.split(',').slice(0, 3).map((skill, i) => (
                                                    <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                                                        {skill.trim()}
                                                    </span>
                                                ))}
                                                {tech.skills.split(',').length > 3 && (
                                                    <span className="text-xs text-gray-400">+{tech.skills.split(',').length - 3} more</span>
                                                )}
                                            </div>
                                        ) : '-'}
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${tech.availability === 'available'
                                            ? 'bg-green-100 text-green-800 border-green-200'
                                            : 'bg-gray-100 text-gray-800 border-gray-200'
                                            }`}>
                                            {tech.availability === 'available' ? 'Available' : 'Offline'}
                                        </span>
                                    </td>
                                </tr>
                            ))
                        ) : (
                            <tr>
                                <td colSpan={4} className="px-6 py-12 text-center text-gray-500">
                                    No technicians found for your organization.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default TechnicianList;
