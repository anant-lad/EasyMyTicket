import React, { useState, useEffect, useRef } from 'react';
import { Bell, Check, Trash2, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { notificationService, Notification } from '../../services/notificationService';
import { useNavigate } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { cn } from '../../lib/utils';
import toast from 'react-hot-toast';

const NotificationCenter: React.FC = () => {
    const [isOpen, setIsOpen] = useState(false);
    const [notifications, setNotifications] = useState<Notification[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const [loading, setLoading] = useState(false);
    const { user } = useAuth();
    const navigate = useNavigate();
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Fetch notifications
    const fetchNotifications = async () => {
        if (!user) return;
        try {
            const data = await notificationService.getNotifications(10); // Get latest 10

            // Check for new notifications to toast
            if (data.items.length > 0) {
                const latestId = data.items[0].id;
                const lastSeenId = parseInt(localStorage.getItem('last_seen_notification_id') || '0');

                if (latestId > lastSeenId) {
                    // Find all new notifications since last check
                    const newNotifications = data.items.filter(n => n.id > lastSeenId);

                    // Toast the newest one (or summary if multiple)
                    if (newNotifications.length === 1) {
                        toast(newNotifications[0].title, {
                            icon: '🔔',
                            duration: 5000,
                            position: 'top-right',
                            style: {
                                background: '#333',
                                color: '#fff',
                                zIndex: 9999,
                            },
                        });
                    } else if (newNotifications.length > 1) {
                        toast(`${newNotifications.length} new notifications`, {
                            icon: '🔔',
                            duration: 5000,
                            position: 'top-right',
                        });
                    }

                    // Update last seen
                    localStorage.setItem('last_seen_notification_id', latestId.toString());
                }
            }

            setNotifications(data.items);
            setUnreadCount(data.unread_count);
        } catch (error) {
            console.error('Failed to fetch notifications', error);
        }
    };

    // Visibility-aware polling
    useEffect(() => {
        let timeoutId: NodeJS.Timeout;

        const poll = async () => {
            // Only fetch if tab is visible
            if (document.visibilityState === 'visible' && user) {
                await fetchNotifications();
            }
            // Schedule next poll
            timeoutId = setTimeout(poll, 10000); // 10 seconds
        };

        // Initial fetch
        if (user) {
            fetchNotifications();
            // Start loop
            timeoutId = setTimeout(poll, 10000);
        }

        return () => clearTimeout(timeoutId);
    }, [user]);

    const handleMarkAsRead = async (id: number, e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await notificationService.markAsRead(id);
            // Optimistic update
            setNotifications(prev => prev.map(n =>
                n.id === id ? { ...n, is_read: true } : n
            ));
            setUnreadCount(prev => Math.max(0, prev - 1));
        } catch (error) {
            console.error('Error marking as read', error);
        }
    };

    const handleMarkAllRead = async () => {
        try {
            setLoading(true);
            await notificationService.markAllAsRead();
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
            setUnreadCount(0);
        } catch (error) {
            console.error('Error marking all as read', error);
        } finally {
            setLoading(false);
        }
    };

    // Helper for notification type styles
    const getIconColor = (type: string) => {
        switch (type) {
            case 'success': return 'text-green-500 bg-green-50 dark:bg-green-900/20';
            case 'warning': return 'text-yellow-500 bg-yellow-50 dark:bg-yellow-900/20';
            case 'error': return 'text-red-500 bg-red-50 dark:bg-red-900/20';
            default: return 'text-blue-500 bg-blue-50 dark:bg-blue-900/20';
        }
    };

    const handleNotificationClick = (notification: Notification) => {
        if (!notification.is_read) {
            handleMarkAsRead(notification.id, { stopPropagation: () => { } } as React.MouseEvent);
        }

        // Navigate based on type
        if (notification.related_entity_type === 'ticket' && notification.related_entity_id) {
            // Determine route based on user role
            // const prefix = user?.role === 'technician' ? '/technician/tickets' : '/user/view-ticket'; 
            if (user?.role === 'technician') {
                navigate(`/technician/tickets/${notification.related_entity_id}`);
            } else {
                navigate(`/user/view-ticket/${notification.related_entity_id}`);
            }
            setIsOpen(false);
        }
    };

    if (!user) return null;

    return (
        <div className="relative" ref={dropdownRef}>
            {/* Bell Icon Trigger */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="relative p-2 rounded-full hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
                <Bell className="w-5 h-5 text-gray-600 dark:text-gray-300" />
                {unreadCount > 0 && (
                    <span className="absolute top-0 right-0 inline-flex items-center justify-center px-1.5 py-0.5 text-xs font-bold leading-none text-white transform translate-x-1/4 -translate-y-1/4 bg-red-500 rounded-full">
                        {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                )}
            </button>

            {/* Dropdown Panel */}
            {isOpen && (
                <div className="absolute right-0 mt-2 w-80 md:w-96 bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-gray-200 dark:border-slate-700 overflow-hidden z-50 animate-in fade-in zoom-in-95 duration-200">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-800/50">
                        <h3 className="font-semibold text-sm text-gray-900 dark:text-gray-100">Notifications</h3>
                        {unreadCount > 0 && (
                            <button
                                onClick={handleMarkAllRead}
                                disabled={loading}
                                className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 font-medium transition-colors"
                            >
                                Mark all as read
                            </button>
                        )}
                    </div>

                    <div className="max-h-[400px] overflow-y-auto">
                        {notifications.length === 0 ? (
                            <div className="flex flex-col items-center justify-center py-8 text-center px-4">
                                <Bell className="w-8 h-8 text-gray-300 mb-2" />
                                <p className="text-sm text-gray-500">No notifications yet</p>
                            </div>
                        ) : (
                            <div className="divide-y divide-gray-100 dark:divide-slate-800">
                                {notifications.map((notification) => (
                                    <div
                                        key={notification.id}
                                        onClick={() => handleNotificationClick(notification)}
                                        className={cn(
                                            "group flex gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors cursor-pointer",
                                            !notification.is_read && "bg-blue-50/30 dark:bg-blue-900/10"
                                        )}
                                    >
                                        <div className={`mt-1 flex-shrink-0 w-2 h-2 rounded-full ${!notification.is_read ? 'bg-blue-500' : 'bg-transparent'}`} />

                                        <div className="flex-1 min-w-0">
                                            <p className={cn("text-sm font-medium text-gray-900 dark:text-gray-100", !notification.is_read && "font-semibold")}>
                                                {notification.title}
                                            </p>
                                            <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5 line-clamp-2">
                                                {notification.message}
                                            </p>
                                            <p className="text-xs text-gray-400 mt-1">
                                                {formatDistanceToNow(new Date(notification.created_at), { addSuffix: true })}
                                            </p>
                                        </div>

                                        {/* Hover Actions */}
                                        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-start">
                                            {!notification.is_read && (
                                                <button
                                                    onClick={(e) => handleMarkAsRead(notification.id, e)}
                                                    className="p-1 hover:bg-gray-200 dark:hover:bg-slate-700 rounded text-gray-400 hover:text-blue-500"
                                                    title="Mark as read"
                                                >
                                                    <Check className="w-4 h-4" />
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="px-4 py-2 bg-gray-50 dark:bg-slate-800/50 border-t border-gray-100 dark:border-slate-800 flex justify-end items-center">
                        <button className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
                            View all history
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

export default NotificationCenter;
