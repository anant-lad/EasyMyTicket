
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { technicianService } from '../../services/technicians';
import api from '../../services/api';
import { User, Technician } from '../../types';
import toast from 'react-hot-toast';

const OrgAdminHome: React.FC = () => {
    const { user } = useAuth();
    const [activeTab, setActiveTab] = useState<'users' | 'technicians'>('users');
    const [users, setUsers] = useState<User[]>([]);
    const [technicians, setTechnicians] = useState<Technician[]>([]);
    const [loading, setLoading] = useState(true);
    const [showAddModal, setShowAddModal] = useState(false);

    // Form states
    const [newUser, setNewUser] = useState({
        user_id: '',
        user_name: '',
        user_mail: '',
        user_password: ''
    });

    const [newTech, setNewTech] = useState({
        tech_id: '',
        tech_name: '',
        tech_mail: '',
        tech_password: '',
        skills: ''
    });

    useEffect(() => {
        fetchData();
    }, [activeTab]);

    const fetchData = async () => {
        setLoading(true);
        try {
            if (activeTab === 'users') {
                const response = await api.get('/database/users', { params: { limit: 1000 } });
                const allUsers = response.data.data || [];
                const orgUsers = allUsers.filter((u: any) => u.companyid === user?.companyid);
                setUsers(orgUsers);
            } else {
                const response = await technicianService.getTechnicians({ limit: 1000 });
                const allTechs = response.data || [];
                const orgTechs = allTechs.filter((t: any) => t.companyid === user?.companyid);
                setTechnicians(orgTechs);
            }
        } catch (error) {
            toast.error('Failed to load data');
        } finally {
            setLoading(false);
        }
    };

    const handleAddUser = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const payload = [{
                ...newUser,
                companyid: user?.companyid
            }];

            await api.post('/database/users', payload);
            toast.success('User added successfully');
            setShowAddModal(false);
            setNewUser({ user_id: '', user_name: '', user_mail: '', user_password: '' });
            fetchData();
        } catch (error: any) {
            toast.error(error.response?.data?.detail || 'Failed to add user');
        }
    };

    const handleAddTech = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const payload = [{
                ...newTech,
                companyid: user?.companyid
            }];

            await technicianService.addTechnicians(payload);
            toast.success('Technician added successfully');
            setShowAddModal(false);
            setNewTech({ tech_id: '', tech_name: '', tech_mail: '', tech_password: '', skills: '' });
            fetchData();
        } catch (error: any) {
            toast.error(error.response?.data?.detail || 'Failed to add technician');
        }
    };

    return (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            {/* Tabs */}
            <div className="mb-8 border-b border-gray-200">
                <nav className="-mb-px flex space-x-8">
                    <button
                        onClick={() => setActiveTab('users')}
                        className={`whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm transition-colors ${activeTab === 'users'
                            ? 'border-indigo-500 text-indigo-600'
                            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            }`}
                    >
                        User Directory
                    </button>
                    <button
                        onClick={() => setActiveTab('technicians')}
                        className={`whitespace-nowrap pb-4 px-1 border-b-2 font-medium text-sm transition-colors ${activeTab === 'technicians'
                            ? 'border-indigo-500 text-indigo-600'
                            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            }`}
                    >
                        Technician Roster
                    </button>
                </nav>
            </div>

            {/* Actions */}
            <div className="mb-6 flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-bold text-gray-900">{activeTab === 'users' ? 'Registered Users' : 'Support Team'}</h2>
                    <p className="text-sm text-gray-500 mt-1">
                        {activeTab === 'users'
                            ? 'Manage access for employees creating tickets.'
                            : 'Manage technicians assigned to resolve tickets.'}
                    </p>
                </div>
                <button
                    onClick={() => setShowAddModal(true)}
                    className="inline-flex items-center px-4 py-2 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                >
                    <svg className="-ml-1 mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" />
                    </svg>
                    Add {activeTab === 'users' ? 'User' : 'Technician'}
                </button>
            </div>

            {/* Content */}
            {loading ? (
                <div className="flex justify-center py-12">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
                </div>
            ) : (
                <div className="bg-white shadow-sm ring-1 ring-gray-900/5 sm:rounded-xl overflow-hidden">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
                                {activeTab === 'technicians' && (
                                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Skills</th>
                                )}
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {activeTab === 'users' ? (
                                users.map(u => (
                                    <tr key={u.user_id} className="hover:bg-gray-50 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-mono">{u.user_id}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{u.user_name}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{u.user_mail}</td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 border border-green-200">
                                                Active
                                            </span>
                                        </td>
                                    </tr>
                                ))
                            ) : (
                                technicians.map(t => (
                                    <tr key={t.tech_id} className="hover:bg-gray-50 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-mono">{t.tech_id}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{t.tech_name}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{t.tech_mail}</td>
                                        <td className="px-6 py-4 text-sm text-gray-500 max-w-xs truncate">
                                            {t.skills ? (
                                                <div className="flex flex-wrap gap-1">
                                                    {t.skills.split(',').map((skill, i) => (
                                                        <span key={i} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-700">
                                                            {skill.trim()}
                                                        </span>
                                                    ))}
                                                </div>
                                            ) : '-'}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${t.available
                                                ? 'bg-green-100 text-green-800 border-green-200'
                                                : 'bg-yellow-100 text-yellow-800 border-yellow-200'
                                                }`}>
                                                {t.available ? 'Available' : 'Busy'}
                                            </span>
                                        </td>
                                    </tr>
                                ))
                            )}
                            {(activeTab === 'users' ? users.length === 0 : technicians.length === 0) && (
                                <tr>
                                    <td colSpan={activeTab === 'users' ? 4 : 5} className="px-6 py-12 text-center text-gray-500">
                                        No entries found
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Add Modal */}
            {showAddModal && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 animate-fadeIn">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="text-xl font-bold text-gray-900">
                                Add New {activeTab === 'users' ? 'User' : 'Technician'}
                            </h3>
                            <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-gray-600">✕</button>
                        </div>
                        <form onSubmit={activeTab === 'users' ? handleAddUser : handleAddTech} className="space-y-4">
                            {activeTab === 'users' ? (
                                <>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">User ID</label>
                                        <input type="text" required value={newUser.user_id} onChange={e => setNewUser({ ...newUser, user_id: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                                        <input type="text" required value={newUser.user_name} onChange={e => setNewUser({ ...newUser, user_name: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                                        <input type="email" required value={newUser.user_mail} onChange={e => setNewUser({ ...newUser, user_mail: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                                        <input type="password" required value={newUser.user_password} onChange={e => setNewUser({ ...newUser, user_password: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                </>
                            ) : (
                                <>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Tech ID</label>
                                        <input type="text" required value={newTech.tech_id} onChange={e => setNewTech({ ...newTech, tech_id: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                                        <input type="text" required value={newTech.tech_name} onChange={e => setNewTech({ ...newTech, tech_name: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                                        <input type="email" required value={newTech.tech_mail} onChange={e => setNewTech({ ...newTech, tech_mail: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                                        <input type="password" required value={newTech.tech_password} onChange={e => setNewTech({ ...newTech, tech_password: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Skills</label>
                                        <input type="text" value={newTech.skills} onChange={e => setNewTech({ ...newTech, skills: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500" placeholder="e.g. Printer, Laptop, Network" />
                                        <p className="text-xs text-gray-500 mt-1">Separate skills with commas</p>
                                    </div>
                                </>
                            )}

                            <div className="flex gap-3 mt-6">
                                <button type="button" onClick={() => setShowAddModal(false)} className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 font-medium">Cancel</button>
                                <button type="submit" className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium shadow-sm">Create</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default OrgAdminHome;
