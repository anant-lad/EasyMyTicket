import api from './api';

export const technicianService = {
  getTechnicians: async (params?: any): Promise<any> => {
    const response = await api.get('/database/technicians', { params });
    return response.data;
  },
  updateAvailability: async (techId: string, availability: string): Promise<any> => {
    const response = await api.patch(`/database/technicians/${techId}/availability`, null, {
      params: { availability },
    });
    return response.data;
  },
  assistTechnician: async (text: string, sessionId?: string): Promise<any> => {
    const response = await api.post('/technician/assist', { text, session_id: sessionId });
    return response.data;
  },
  addTechnicians: async (technicians: any[]): Promise<any> => {
    const response = await api.post('/database/technicians', technicians);
    return response.data;
  },
  getAssignmentHistory: async (ticketNumber: string): Promise<any> => {
    const response = await api.get(`/database/tickets/${ticketNumber}/assignments`);
    return response.data;
  },
  getTechnicianById: async (techId: string): Promise<any> => {
    const response = await api.get('/database/technicians', { params: { tech_id: techId } });
    return response.data;
  },
};
