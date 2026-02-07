import api from './api';
import { ApiResponse } from '../types';

export const databaseService = {
    getStatus: async (): Promise<any> => {
        const response = await api.get('/database/status');
        return response.data;
    },

    startDatabase: async (): Promise<any> => {
        const response = await api.post('/database/start');
        return response.data;
    },

    restartDatabase: async (): Promise<any> => {
        const response = await api.post('/database/restart');
        return response.data;
    },

    getTables: async (): Promise<any> => {
        const response = await api.get('/database/tables');
        return response.data;
    },

    getTableInfo: async (tableName: string): Promise<any> => {
        const response = await api.get(`/database/tables/${tableName}`);
        return response.data;
    },

    getTableData: async (tableName: string, params?: { limit?: number; offset?: number; order_by?: string }): Promise<any> => {
        const response = await api.get(`/database/tables/${tableName}/data`, { params });
        return response.data;
    },

    clearTable: async (tableName: string): Promise<any> => {
        const response = await api.delete(`/database/tables/${tableName}/clear`);
        return response.data;
    }
};
