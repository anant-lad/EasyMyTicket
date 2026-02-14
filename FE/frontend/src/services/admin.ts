
import api from './api';

export const adminService = {
    // Organizations
    createOrganization: async (data: any) => {
        const response = await api.post('/organizations/create', data);
        return response.data;
    },

    getOrganizations: async (params?: any) => {
        const response = await api.get('/organizations', { params });
        return response.data;
    },

    getOrganization: async (companyId: string) => {
        const response = await api.get(`/organizations/${companyId}`);
        return response.data;
    },

    updateOrganization: async (companyId: string, data: any) => {
        const response = await api.patch(`/organizations/${companyId}`, data);
        return response.data;
    },

    deleteOrganization: async (companyId: string) => {
        const response = await api.delete(`/organizations/${companyId}`);
        return response.data;
    },

    getOrgAnalytics: async (companyId: string) => {
        const response = await api.get(`/organizations/${companyId}/analytics`);
        return response.data;
    },

    // System Health
    getSystemHealth: async () => {
        const response = await api.get('/system/health');
        return response.data;
    },

    // Audit Logs
    getAuditLogs: async (params?: any) => {
        const response = await api.get('/audit-logs', { params });
        return response.data;
    },

    // Global Settings
    getSettings: async () => {
        const response = await api.get('/settings');
        return response.data;
    },

    updateSetting: async (key: string, value: any, updatedBy: string) => {
        const response = await api.patch(`/settings/${key}`, { value, updated_by: updatedBy });
        return response.data;
    }
};
