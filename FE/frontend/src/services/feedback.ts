import api from './api';
import { ClassificationFeedback, AssignmentFeedback, ResolutionFeedback } from '../types';

export const feedbackService = {
  submitClassificationFeedback: async (feedback: ClassificationFeedback): Promise<any> => {
    const response = await api.post('/feedback/classification', feedback);
    return response.data;
  },
  submitAssignmentFeedback: async (feedback: AssignmentFeedback): Promise<any> => {
    const response = await api.post('/feedback/assignment', feedback);
    return response.data;
  },
  submitResolutionFeedback: async (feedback: ResolutionFeedback): Promise<any> => {
    const response = await api.post('/feedback/resolution', feedback);
    return response.data;
  },
  getFeedbackStats: async (): Promise<any> => {
    const response = await api.get('/feedback/stats');
    return response.data;
  },
  exportTrainingData: async (limit: number = 100): Promise<any> => {
    const response = await api.get('/feedback/training-data', { params: { limit } });
    return response.data;
  },
};
