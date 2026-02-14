import api from './api';
import { Organization, PaginatedResponse } from '../types';

export const organizationService = {
  createOrganization: async (data: any): Promise<any> => {
    const response = await api.post('/organizations/create', data);
    return response.data;
  },
  getOrganizations: async (params?: any): Promise<PaginatedResponse<Organization>> => {
    const response = await api.get<PaginatedResponse<Organization>>('/organizations', { params });
    return response.data;
  },
  getOrganization: async (companyId: string): Promise<any> => {
    const response = await api.get(`/organizations/${companyId}`);
    return response.data;
  },
  updateOrganization: async (companyId: string, data: any): Promise<any> => {
    const response = await api.patch(`/organizations/${companyId}`, data);
    return response.data;
  },
  deleteOrganization: async (companyId: string): Promise<any> => {
    const response = await api.delete(`/organizations/${companyId}`);
    return response.data;
  },
};
