import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Command, ArrowRight, Settings, FileText, User, LayoutDashboard, PlusCircle } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface CommandItem {
    id: string;
    title: string;
    icon: React.ElementType;
    shortcut?: string;
    action: () => void;
    category: string;
}

const CommandPalette: React.FC = () => {
    const [isOpen, setIsOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [selectedIndex, setSelectedIndex] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const navigate = useNavigate();
    const { user } = useAuth();

    // Define commands based on user role
    const getCommands = (): CommandItem[] => {
        const commands: CommandItem[] = [
            // Navigation
            {
                id: 'nav-dashboard',
                title: 'Go to Dashboard',
                icon: LayoutDashboard,
                category: 'Navigation',
                action: () => {
                    if (user?.role === 'technician') navigate('/technician/dashboard');
                    else if (user?.role === 'org_admin') navigate('/org/dashboard');
                    else if (user?.role === 'super_admin') navigate('/admin/dashboard');
                    else navigate('/user/dashboard');
                }
            },
            {
                id: 'nav-settings',
                title: 'Go to Settings',
                icon: Settings,
                category: 'Navigation',
                action: () => navigate('/settings') // Placeholder route
            },
            // Actions
            {
                id: 'act-new-ticket',
                title: 'Create New Ticket',
                icon: PlusCircle,
                shortcut: 'C',
                category: 'Actions',
                action: () => navigate('/user/create-ticket') // Assuming route
            },
            {
                id: 'act-view-reports',
                title: 'View Reports',
                icon: FileText,
                category: 'Actions',
                action: () => navigate('/org/reports')
            }
        ];

        return commands;
    };

    const allCommands = getCommands();
    const filteredCommands = allCommands.filter(cmd =>
        cmd.title.toLowerCase().includes(query.toLowerCase()) ||
        cmd.category.toLowerCase().includes(query.toLowerCase())
    );

    // Toggle with Cmd+K / Ctrl+K
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                setIsOpen(prev => !prev);
                setQuery('');
                setSelectedIndex(0);
            } else if (e.key === 'Escape') {
                setIsOpen(false);
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    // Focus input when opened
    useEffect(() => {
        if (isOpen && inputRef.current) {
            inputRef.current.focus();
        }
    }, [isOpen]);

    // Handle keyboard navigation inside the palette
    const handlePaletteKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSelectedIndex(prev => (prev + 1) % filteredCommands.length);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSelectedIndex(prev => (prev - 1 + filteredCommands.length) % filteredCommands.length);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (filteredCommands[selectedIndex]) {
                filteredCommands[selectedIndex].action();
                setIsOpen(false);
            }
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/50 backdrop-blur-sm transition-all duration-200">
            <div
                className="w-full max-w-lg bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-gray-200 dark:border-slate-700 overflow-hidden transform transition-all"
                onKeyDown={handlePaletteKeyDown}
            >
                {/* Search Input */}
                <div className="flex items-center px-4 py-3 border-b border-gray-100 dark:border-slate-800">
                    <Search className="w-5 h-5 text-gray-400 mr-3" />
                    <input
                        ref={inputRef}
                        type="text"
                        className="w-full bg-transparent outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400 text-lg"
                        placeholder="Type a command or search..."
                        value={query}
                        onChange={e => {
                            setQuery(e.target.value);
                            setSelectedIndex(0);
                        }}
                    />
                    <div className="text-xs text-gray-400 border border-gray-200 dark:border-slate-700 rounded px-1.5 py-0.5">
                        ESC
                    </div>
                </div>

                {/* Results List */}
                <div className="max-h-[300px] overflow-y-auto py-2">
                    {filteredCommands.length === 0 ? (
                        <div className="px-4 py-8 text-center text-gray-500">
                            No results found.
                        </div>
                    ) : (
                        <>
                            {/* Group by category if we wanted, for now flat list */}
                            {filteredCommands.map((command, index) => (
                                <div
                                    key={command.id}
                                    className={`
                    group flex items-center justify-between px-4 py-3 mx-2 rounded-lg cursor-pointer transition-colors duration-150
                    ${index === selectedIndex ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-slate-800'}
                  `}
                                    onClick={() => {
                                        command.action();
                                        setIsOpen(false);
                                    }}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                >
                                    <div className="flex items-center gap-3">
                                        <command.icon className={`w-5 h-5 ${index === selectedIndex ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'}`} />
                                        <span className="font-medium">{command.title}</span>
                                    </div>
                                    {command.shortcut && (
                                        <span className="text-xs text-gray-400 font-mono border border-gray-200 dark:border-slate-700 px-1 rounded">
                                            {command.shortcut}
                                        </span>
                                    )}
                                    {index === selectedIndex && (
                                        <ArrowRight className="w-4 h-4 text-indigo-500 opacity-60" />
                                    )}
                                </div>
                            ))}
                        </>
                    )}
                </div>

                {/* Footer */}
                <div className="px-4 py-2 bg-gray-50 dark:bg-slate-800/50 border-t border-gray-100 dark:border-slate-800 text-xs text-gray-500 flex justify-between">
                    <div className="flex gap-4">
                        <span>Tasks: <strong>{filteredCommands.length}</strong></span>
                    </div>
                    <div className="flex gap-2">
                        <span>Use <strong>↑↓</strong> to navigate</span>
                        <span><strong>↵</strong> to select</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default CommandPalette;
