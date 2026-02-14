import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import { User } from '../../types';
import toast from 'react-hot-toast';
import { Plus, Trash2, Edit2, Search, X } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog'; // Assuming UI components exist or using generic modal

const UserManagement: React.FC = () => {
    const { user } = useAuth();
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [showAddModal, setShowAddModal] = useState(false);
    const [deleteId, setDeleteId] = useState<string | null>(null);

    const [newUser, setNewUser] = useState({
        user_id: '',
        user_name: '',
        user_mail: '',
        user_password: ''
    });

    useEffect(() => {
        fetchUsers();
    }, [user?.companyid]);

    const fetchUsers = async () => {
        setLoading(true);
        try {
            // Fetch all users and filter client-side for now
            const response = await api.get('/database/users', { params: { limit: 1000 } });
            const allUsers = response.data.data || [];
            if (user?.companyid) {
                const orgUsers = allUsers.filter((u: any) => u.companyid === user.companyid);
                setUsers(orgUsers);
            }
        } catch (error) {
            toast.error('Failed to load users');
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
            fetchUsers();
        } catch (error: any) {
            toast.error(error.response?.data?.detail || 'Failed to add user');
        }
    };

    const handleDeleteUser = async () => {
        if (!deleteId || !user?.companyid) return;
        try {
            await api.delete(`/database/users/${deleteId}`, { params: { companyid: user.companyid } });
            toast.success('User deleted successfully');
            setDeleteId(null);
            fetchUsers();
        } catch (error: any) {
            toast.error(error.response?.data?.detail || 'Failed to delete user');
        }
    };

    const filteredUsers = users.filter(u =>
        u.user_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        u.user_mail.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="space-y-6">
            <div className="sm:flex sm:items-center sm:justify-between">
                <div>
                    <h2 className="text-2xl font-bold text-gray-900">User Directory</h2>
                    <p className="mt-1 text-sm text-gray-500">Manage detailed user access and profiles.</p>
                </div>
                <div className="mt-4 sm:mt-0 flex gap-3">
                    <div className="relative rounded-md shadow-sm">
                        <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                            <Search className="h-4 w-4 text-gray-400" />
                        </div>
                        <input
                            type="text"
                            className="block w-full rounded-md border-gray-300 pl-10 focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm py-2"
                            placeholder="Search users..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>
                    <button
                        onClick={() => setShowAddModal(true)}
                        className="inline-flex items-center rounded-md border border-transparent bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
                    >
                        <Plus className="-ml-1 mr-2 h-4 w-4" />
                        Add User
                    </button>
                </div>
            </div>

            {loading ? (
                <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div></div>
            ) : (
                <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 sm:rounded-lg">
                    <table className="min-w-full divide-y divide-gray-300">
                        <thead className="bg-gray-50">
                            <tr>
                                <th scope="col" className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">User ID</th>
                                <th scope="col" className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Name</th>
                                <th scope="col" className="px-3 py-3.5 text-left text-sm font-semibold text-gray-900">Email</th>
                                <th scope="col" className="relative py-3.5 pl-3 pr-4 sm:pr-6">
                                    <span className="sr-only">Actions</span>
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200 bg-white">
                            {filteredUsers.length > 0 ? filteredUsers.map((person) => (
                                <tr key={person.user_id}>
                                    <td className="whitespace-nowrap px-3 py-4 text-sm text-gray-500 font-mono">{person.user_id}</td>
                                    <td className="whitespace-nowrap px-3 py-4 text-sm font-medium text-gray-900">{person.user_name}</td>
                                    <td className="whitespace-nowrap px-3 py-4 text-sm text-gray-500">{person.user_mail}</td>
                                    <td className="relative whitespace-nowrap py-4 pl-3 pr-4 text-right text-sm font-medium sm:pr-6">
                                        <button
                                            onClick={() => setDeleteId(person.user_id)}
                                            className="text-red-600 hover:text-red-900 ml-4"
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </button>
                                    </td>
                                </tr>
                            )) : (
                                <tr>
                                    <td colSpan={4} className="px-3 py-8 text-center text-sm text-gray-500">No users found</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Delete Confirmation Modal */}
            {deleteId && (
                <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-lg px-4 pt-5 pb-4 sm:p-6 sm:pb-4 max-w-sm w-full">
                        <div className="sm:flex sm:items-start">
                            <div className="mx-auto flex-shrink-0 flex items-center justify-center h-12 w-12 rounded-full bg-red-100 sm:mx-0 sm:h-10 sm:w-10">
                                <Trash2 className="h-6 w-6 text-red-600" aria-hidden="true" />
                            </div>
                            <div className="mt-3 text-center sm:mt-0 sm:ml-4 sm:text-left">
                                <h3 className="text-lg leading-6 font-medium text-gray-900">Delete User</h3>
                                <div className="mt-2">
                                    <p className="text-sm text-gray-500">Are you sure you want to delete this user? This action cannot be undone.</p>
                                </div>
                            </div>
                        </div>
                        <div className="mt-5 sm:mt-4 sm:flex sm:flex-row-reverse">
                            <button
                                type="button"
                                className="w-full inline-flex justify-center rounded-md border border-transparent shadow-sm px-4 py-2 bg-red-600 text-base font-medium text-white hover:bg-red-700 focus:outline-none sm:ml-3 sm:w-auto sm:text-sm"
                                onClick={handleDeleteUser}
                            >
                                Delete
                            </button>
                            <button
                                type="button"
                                className="mt-3 w-full inline-flex justify-center rounded-md border border-gray-300 shadow-sm px-4 py-2 bg-white text-base font-medium text-gray-700 hover:bg-gray-50 focus:outline-none sm:mt-0 sm:w-auto sm:text-sm"
                                onClick={() => setDeleteId(null)}
                            >
                                Cancel
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Add User Modal */}
            {showAddModal && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50">
                    <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 animate-fadeIn">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="text-xl font-bold text-gray-900">Add New User</h3>
                            <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
                        </div>
                        <form onSubmit={handleAddUser} className="space-y-4">
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

export default UserManagement;
