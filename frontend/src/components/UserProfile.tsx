import React from 'react';
import { useAuth } from '../context/AuthContext';
import { User, Mail, Building, Shield, Phone, MapPin, Calendar } from 'lucide-react';

const UserProfile: React.FC = () => {
    const { user } = useAuth();

    if (!user) return null;

    return (
        <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="mb-8">
                <h1 className="text-2xl font-bold text-gray-900 tracking-tight">My Profile</h1>
                <p className="text-gray-500 mt-2">Manage your account settings and preferences.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* ID Card / Left Column */}
                <div className="md:col-span-1 space-y-6">
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 text-center relative overflow-hidden group">
                        <div className="absolute top-0 left-0 w-full h-24 bg-gradient-to-br from-indigo-500 to-purple-600 opacity-10"></div>

                        <div className="relative z-10">
                            <div className="w-24 h-24 mx-auto bg-white rounded-full p-1.5 shadow-lg mb-4">
                                <div className="w-full h-full rounded-full bg-gradient-to-br from-indigo-100 to-purple-50 flex items-center justify-center text-3xl font-bold text-indigo-600">
                                    {user.user_name?.charAt(0).toUpperCase()}
                                </div>
                            </div>
                            <h2 className="text-xl font-bold text-gray-900">{user.user_name}</h2>
                            <p className="text-sm text-gray-500 font-medium uppercase tracking-wide mt-1">{user.role.replace('_', ' ')}</p>

                            <div className="mt-6 flex justify-center">
                                <span className={`px-3 py-1 rounded-full text-xs font-bold border ${user.role === 'super_admin' ? 'bg-purple-50 text-purple-700 border-purple-100' :
                                        'bg-green-50 text-green-700 border-green-100'
                                    }`}>
                                    Active Account
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
                        <h3 className="text-sm font-bold text-gray-900 uppercase tracking-wider mb-4">Quick Stats</h3>
                        <div className="space-y-4">
                            <div className="flex justify-between items-center py-2 border-b border-gray-50">
                                <span className="text-sm text-gray-500">Member Since</span>
                                <span className="text-sm font-medium text-gray-900">Jan 2024</span>
                            </div>
                            <div className="flex justify-between items-center py-2 border-b border-gray-50">
                                <span className="text-sm text-gray-500">Last Login</span>
                                <span className="text-sm font-medium text-gray-900">Today</span>
                            </div>
                            <div className="flex justify-between items-center py-2">
                                <span className="text-sm text-gray-500">Status</span>
                                <span className="text-sm font-medium text-green-600">Online</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Details / Right Column */}
                <div className="md:col-span-2">
                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 bg-gray-50/50 flex justify-between items-center">
                            <h3 className="font-bold text-gray-900">Personal Information</h3>
                            <button className="text-sm text-indigo-600 font-medium hover:text-indigo-700">Edit</button>
                        </div>
                        <div className="p-6 space-y-6">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                                <div>
                                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Full Name</label>
                                    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl border border-gray-100">
                                        <User className="w-5 h-5 text-gray-400" />
                                        <span className="text-gray-900 font-medium">{user.user_name}</span>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Email Address</label>
                                    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl border border-gray-100">
                                        <Mail className="w-5 h-5 text-gray-400" />
                                        <span className="text-gray-900 font-medium truncate">{user.user_mail}</span>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Role</label>
                                    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl border border-gray-100">
                                        <Shield className="w-5 h-5 text-gray-400" />
                                        <span className="text-gray-900 font-medium capitalize">{user.role.replace('_', ' ')}</span>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Organization ID</label>
                                    <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl border border-gray-100">
                                        <Building className="w-5 h-5 text-gray-400" />
                                        <span className="text-gray-900 font-medium">{user.companyid || 'N/A'}</span>
                                    </div>
                                </div>
                            </div>

                            {user.organization && (
                                <div className="mt-6 pt-6 border-t border-gray-100">
                                    <h4 className="text-sm font-bold text-gray-900 mb-4">Organization Details</h4>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                                        <div>
                                            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Company Name</label>
                                            <div className="flex items-center gap-3">
                                                <span className="text-gray-900 font-medium">{user.organization.company_name}</span>
                                            </div>
                                        </div>
                                        {user.organization.address && (
                                            <div>
                                                <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Address</label>
                                                <div className="flex items-center gap-3">
                                                    <MapPin className="w-4 h-4 text-gray-400" />
                                                    <span className="text-gray-900 font-medium">{user.organization.address}</span>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 mt-6 overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-100 bg-gray-50/50">
                            <h3 className="font-bold text-gray-900">Security</h3>
                        </div>
                        <div className="p-6">
                            <div className="flex items-center justify-between">
                                <div>
                                    <p className="text-sm font-medium text-gray-900">Password</p>
                                    <p className="text-sm text-gray-500">Last changed 3 months ago</p>
                                </div>
                                <button className="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
                                    Change Password
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default UserProfile;
