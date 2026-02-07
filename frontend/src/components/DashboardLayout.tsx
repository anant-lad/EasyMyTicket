import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
    LogOut, User, Settings, ChevronDown, Bell,
    LayoutDashboard, Building2, Activity, FileText,
    Users, Wrench, BarChart3,
    Ticket, Pin, TrendingUp, CheckCircle2, Bot, BookOpen,
    Home, PlusCircle, HelpCircle
} from 'lucide-react';

// ... existing imports ...

interface DashboardLayoutProps {
    children: React.ReactNode;
    role: 'super_admin' | 'org_admin' | 'technician' | 'user';
    title?: string;
}

const DashboardLayout: React.FC<DashboardLayoutProps> = ({ children, role, title }) => {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [userMenuOpen, setUserMenuOpen] = useState(false);
    const userMenuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
                setUserMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const getMenuItems = () => {
        switch (role) {
            case 'super_admin':
                return [
                    { name: 'Dashboard', path: '/admin/dashboard', icon: <LayoutDashboard size={20} /> },
                    { name: 'Organizations', path: '/admin/organizations', icon: <Building2 size={20} /> },
                    { name: 'System Health', path: '/admin/health', icon: <Activity size={20} /> },
                    { name: 'Audit Logs', path: '/admin/logs', icon: <FileText size={20} /> }, // New
                    { name: 'Global Settings', path: '/admin/settings', icon: <Settings size={20} /> }, // New
                ];
            case 'org_admin':
                return [
                    { name: 'Dashboard', path: '/org/dashboard', icon: <LayoutDashboard size={20} /> },
                    { name: 'Users', path: '/org/users', icon: <Users size={20} /> },
                    { name: 'Technicians', path: '/org/technicians', icon: <Wrench size={20} /> },
                    { name: 'Reports', path: '/org/reports', icon: <BarChart3 size={20} /> }, // New
                    { name: 'Settings', path: '/org/settings', icon: <Settings size={20} /> }, // New
                ];
            case 'technician':
                return [
                    { name: 'Dashboard', path: '/technician/dashboard', icon: <LayoutDashboard size={20} /> },
                    { name: 'All Tickets', path: '/technician/tickets', icon: <Ticket size={20} /> },
                    { name: 'My Tickets', path: '/technician/my-tickets', icon: <Pin size={20} /> },
                    { name: 'Analytics', path: '/technician/analytics', icon: <TrendingUp size={20} /> },
                    { name: 'Resolved Tickets', path: '/technician/resolved', icon: <CheckCircle2 size={20} /> },
                    { name: 'AI Assistant', path: '/technician/assistant', icon: <Bot size={20} /> },
                    { name: 'Knowledge Base', path: '/technician/kb', icon: <BookOpen size={20} /> }, // New
                ];
            case 'user':
                return [
                    { name: 'Dashboard', path: '/user/dashboard', icon: <Home size={20} /> },
                    { name: 'My Tickets', path: '/user/tickets', icon: <Ticket size={20} /> },
                    { name: 'Create Ticket', path: '/user/create-ticket', icon: <PlusCircle size={20} /> },
                    { name: 'Help & Support', path: '/user/help', icon: <HelpCircle size={20} /> }, // New
                ];
            default:
                return [];
        }
    };

    const getRolePathPrefix = (role: string) => {
        switch (role) {
            case 'super_admin': return '/admin';
            case 'org_admin': return '/org';
            case 'technician': return '/technician';
            case 'user': return '/user';
            default: return '/';
        }
    };

    const menuItems = getMenuItems();

    return (
        <div className="min-h-screen bg-gray-50 flex font-sans">
            {/* Sidebar */}
            <aside
                className={`bg-white border-r border-gray-200 fixed lg:static inset-y-0 left-0 z-30 transition-all duration-300 ${sidebarOpen ? 'w-64' : 'w-20'
                    } flex flex-col shadow-sm`}
            >
                <div className="h-16 flex items-center justify-between px-4 border-b border-gray-100 bg-white/50 backdrop-blur-sm">
                    {sidebarOpen ? (
                        <div className="flex items-center gap-2">
                            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-200">
                                <span className="font-bold text-lg">E</span>
                            </div>
                            <span className="text-xl font-bold text-gray-900 tracking-tight">
                                EaseMyTkt
                            </span>
                        </div>
                    ) : (
                        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white mx-auto shadow-md shadow-indigo-200">
                            <span className="font-bold text-lg">E</span>
                        </div>
                    )}
                    <button
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 lg:block hidden transition-colors"
                    >
                        {sidebarOpen ? (
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7"></path></svg>
                        ) : (
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 5l7 7-7 7M5 5l7 7-7 7"></path></svg>
                        )}
                    </button>
                </div>

                <nav className="flex-1 py-6 px-3 space-y-1.5 overflow-y-auto">
                    {menuItems.map((item) => {
                        const isActive = location.pathname === item.path;
                        return (
                            <button
                                key={item.path}
                                onClick={() => navigate(item.path)}
                                className={`w-full flex items-center px-3 py-3 rounded-xl transition-all duration-200 group ${isActive
                                    ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-sm shadow-indigo-100'
                                    : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
                                    }`}
                            >
                                <span className={`transition-transform duration-200 ${isActive ? 'text-indigo-600' : 'text-gray-400 group-hover:text-gray-600'}`}>{item.icon}</span>
                                {sidebarOpen && (
                                    <span className="ml-3 transition-opacity duration-200">
                                        {item.name}
                                    </span>
                                )}
                                {!sidebarOpen && (
                                    <div className="absolute left-full ml-6 px-3 py-1.5 bg-gray-900 text-white text-xs font-medium rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-50 shadow-xl transform translate-x-2 group-hover:translate-x-0 transition-all">
                                        {item.name}
                                    </div>
                                )}
                            </button>
                        );
                    })}
                </nav>

                <div className="p-4 border-t border-gray-100 bg-gray-50/50">
                    <button
                        onClick={logout}
                        className={`w-full flex items-center ${sidebarOpen ? 'px-4' : 'justify-center'} py-3 text-red-600 hover:text-red-700 hover:bg-red-50/80 rounded-xl transition-all duration-200 group border border-transparent hover:border-red-100 hover:shadow-sm`}
                        title="Sign Out"
                    >
                        <LogOut className={`w-5 h-5 transition-transform duration-300 group-hover:-translate-x-1 ${!sidebarOpen && 'mx-auto'}`} />
                        {sidebarOpen && <span className="ml-3 font-medium tracking-wide">Log Out</span>}
                    </button>
                </div>
            </aside>

            {/* Main Content */}
            <div className="flex-1 flex flex-col min-w-0 transition-all duration-300">
                {/* Top Header */}
                <header className="bg-white/80 backdrop-blur-md border-b border-gray-200 h-16 flex items-center justify-between px-6 lg:px-8 sticky top-0 z-20 transition-all duration-300 shadow-sm shadow-gray-100/50">
                    <div className="flex items-center">
                        <button
                            className="lg:hidden mr-4 text-gray-500 hover:text-indigo-600 transition-colors p-2 hover:bg-gray-100 rounded-lg"
                            onClick={() => setSidebarOpen(!sidebarOpen)}
                        >
                            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16"></path></svg>
                        </button>
                        <div>
                            <h1 className="text-xl font-bold text-gray-900 tracking-tight leading-none">{title || 'Dashboard'}</h1>
                            {user?.organization?.company_name && (
                                <p className="text-xs text-indigo-600 font-medium tracking-wide uppercase mt-1">
                                    {user.organization.company_name}
                                </p>
                            )}
                        </div>
                    </div>

                    <div className="flex items-center gap-4 sm:gap-6">
                        {/* Notifications (Mock) */}
                        <button className="relative p-2 text-gray-400 hover:text-gray-600 transition-colors rounded-full hover:bg-gray-100">
                            <Bell className="w-5 h-5" />
                            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full border-2 border-white"></span>
                        </button>

                        <div className="h-6 w-px bg-gray-200 hidden sm:block"></div>

                        {/* User Profile Dropdown */}
                        <div className="relative" ref={userMenuRef}>
                            <button
                                onClick={() => setUserMenuOpen(!userMenuOpen)}
                                className={`flex items-center gap-3 pl-2 pr-1 py-1 sm:pl-3 sm:pr-2 sm:py-1.5 rounded-full sm:rounded-xl transition-all duration-200 border border-transparent 
                                    ${userMenuOpen ? 'bg-indigo-50 border-indigo-100 ring-2 ring-indigo-100 ring-offset-2' : 'hover:bg-gray-50 hover:border-gray-200'}`}
                            >
                                <div className="text-right hidden sm:block mr-1">
                                    <div className="text-sm font-bold text-gray-900 leading-tight">{user?.user_name}</div>
                                    <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wider">{role.replace('_', ' ')}</div>
                                </div>
                                <div className="h-9 w-9 rounded-full bg-gradient-to-tr from-indigo-600 to-purple-600 p-[2px] shadow-lg shadow-indigo-500/20 ring-2 ring-white">
                                    <div className="h-full w-full rounded-full bg-white flex items-center justify-center">
                                        <span className="text-indigo-700 font-bold text-sm">
                                            {user?.user_name?.charAt(0).toUpperCase()}
                                        </span>
                                    </div>
                                </div>
                                <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform duration-200 hidden sm:block ${userMenuOpen ? 'rotate-180 text-indigo-500' : ''}`} />
                            </button>

                            {/* Dropdown Menu */}
                            {userMenuOpen && (
                                <div className="absolute right-0 top-full mt-2 w-64 bg-white rounded-2xl shadow-2xl shadow-indigo-100/50 border border-gray-100 py-2 origin-top-right transform transition-all z-50 animate-in fade-in slide-in-from-top-2 duration-200">
                                    <div className="px-5 py-4 border-b border-gray-50 bg-gray-50/50 rounded-t-2xl">
                                        <p className="text-sm font-bold text-gray-900 truncate">{user?.user_name}</p>
                                        <p className="text-xs text-gray-500 truncate font-medium mt-0.5">{user?.user_mail}</p>
                                        {user?.companyid && (
                                            <div className="mt-2 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-gray-200 text-gray-700">
                                                ID: {user?.companyid}
                                            </div>
                                        )}
                                    </div>

                                    <div className="p-2 space-y-1">
                                        <button
                                            onClick={() => navigate(`${getRolePathPrefix(role)}/profile`)}
                                            className="w-full text-left px-3 py-2.5 text-sm font-medium text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 rounded-xl flex items-center gap-3 transition-colors"
                                        >
                                            <User className="w-4 h-4 text-gray-400 group-hover:text-indigo-500" />
                                            My Profile
                                        </button>
                                        <button
                                            onClick={() => navigate(`${getRolePathPrefix(role)}/profile`)} // Using same profile for settings for now
                                            className="w-full text-left px-3 py-2.5 text-sm font-medium text-gray-700 hover:bg-indigo-50 hover:text-indigo-700 rounded-xl flex items-center gap-3 transition-colors"
                                        >
                                            <Settings className="w-4 h-4 text-gray-400 group-hover:text-indigo-500" />
                                            Account Settings
                                        </button>
                                    </div>

                                    <div className="p-2 border-t border-gray-50 mt-1">
                                        <button
                                            onClick={() => { logout(); setUserMenuOpen(false); }}
                                            className="w-full text-left px-3 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50 hover:text-red-700 rounded-xl flex items-center gap-3 transition-colors group"
                                        >
                                            <LogOut className="w-4 h-4 text-red-400 group-hover:text-red-500 transition-transform group-hover:-translate-x-0.5" />
                                            Log Out
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </header>

                {/* Scrollable Page Content */}
                <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 bg-gray-50/50">
                    {children}
                </main>
            </div>
        </div>
    );
};

export default DashboardLayout;
