import api from './api';
import { Ticket, TicketCreateRequest, TicketResponse, PaginatedResponse } from '../types';

export const ticketService = {
  createTicket: async (data: TicketCreateRequest): Promise<TicketResponse> => {
    const formData = new FormData();
    formData.append('title', data.title);
    formData.append('description', data.description);
    formData.append('user_id', data.user_id);
    formData.append('companyid', data.companyid);
    if (data.priority) formData.append('priority', data.priority);
    if (data.due_date_time) formData.append('due_date_time', data.due_date_time);
    if (data.files && data.files.length > 0) {
      data.files.forEach((file) => formData.append('files', file));
    }
    const response = await api.post<TicketResponse>('/tickets/create', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },
  getTickets: async (params?: any): Promise<PaginatedResponse<Ticket>> => {
    const response = await api.get<PaginatedResponse<Ticket>>('/tickets', { params });
    return response.data;
  },
  getTicket: async (ticketNumber: string): Promise<any> => {
    const response = await api.get(`/tickets/${ticketNumber}`);
    return response.data;
  },
  getTicketById: async (ticketId: number): Promise<any> => {
    const response = await api.get(`/tickets/by-id/${ticketId}`);
    return response.data;
  },
  getTicketResolution: async (ticketNumber: string): Promise<any> => {
    const response = await api.get(`/tickets/${ticketNumber}/resolution`);
    return response.data;
  },
  updateStatus: async (ticketNumber: string, status: string, techId?: string): Promise<any> => {
    const response = await api.patch(`/tickets/${ticketNumber}/status`, { status, tech_id: techId });
    return response.data;
  },
  updatePriority: async (ticketNumber: string, priority: string): Promise<any> => {
    const response = await api.patch(`/tickets/${ticketNumber}/priority`, { priority });
    return response.data;
  },
  updateEstimatedHours: async (ticketNumber: string, hours: number): Promise<any> => {
    const response = await api.patch(`/tickets/${ticketNumber}/estimated-hours`, { estimated_hours: hours });
    return response.data;
  },
  updateResolutionPlan: async (ticketNumber: string, datetime: string): Promise<any> => {
    const response = await api.patch(`/tickets/${ticketNumber}/resolution-plan-datetime`, { resolution_plan_datetime: datetime });
    return response.data;
  },
  resolveTicket: async (ticketNumber: string): Promise<any> => {
    const response = await api.patch(`/tickets/${ticketNumber}/resolve`);
    return response.data;
  },
  getAssignmentHistory: async (ticketNumber: string): Promise<any> => {
    const response = await api.get(`/database/tickets/${ticketNumber}/assignments`);
    return response.data;
  },
  reopenTicket: async (ticketNumber: string, reason: string, userId: string): Promise<any> => {
    // Uses the existing feedback endpoint which supports reopening
    const response = await api.post(`/tickets/${ticketNumber}/feedback`, {
      user_id: userId,
      is_resolved: false,
      reopen_reason: reason
    });
    return response.data;
  },
  acceptReopen: async (ticketNumber: string): Promise<any> => {
    const response = await api.post(`/tickets/${ticketNumber}/reopen/accept`);
    return response.data;
  },
  rejectReopen: async (ticketNumber: string, reason: string, techId: string): Promise<any> => {
    const response = await api.post(`/tickets/${ticketNumber}/reopen/reject`, {
      reason,
      tech_id: techId
    });
    return response.data;
  },
};
