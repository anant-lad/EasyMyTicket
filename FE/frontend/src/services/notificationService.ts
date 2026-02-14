import api from './api';

export interface Notification {
    id: number;
    recipient_id: string;
    title: string;
    message: string;
    type: 'info' | 'success' | 'warning' | 'error';
    is_read: boolean;
    related_entity_id?: string;
    related_entity_type?: string;
    created_at: string;
}

export interface NotificationsResponse {
    items: Notification[];
    unread_count: number;
}

export const notificationService = {
    getNotifications: async (limit = 20, offset = 0) => {
        const response = await api.get<NotificationsResponse>('/notifications', {
            params: { limit, offset }
        });
        return response.data;
    },

    markAsRead: async (id: number) => {
        const response = await api.put(`/notifications/${id}/read`);
        return response.data;
    },

    markAllAsRead: async () => {
        const response = await api.put('/notifications/mark-all-read');
        return response.data;
    },

    // Test trigger (for verification)
    triggerTestNotification: async () => {
        const response = await api.post('/notifications/test-trigger');
        return response.data;
    }
};
