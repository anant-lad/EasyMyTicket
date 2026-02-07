// User and Authentication Types
export interface User {
  user_id: string;
  user_name: string;
  user_mail: string;
  role: 'user' | 'technician' | 'super_admin' | 'org_admin';
  companyid?: string;
  organization?: Organization;
}

export interface Technician {
  tech_id: string;
  tech_name: string;
  tech_mail: string;
  skills: string;
  no_tickets_assigned: number;
  solved_tickets: number;
  current_workload: number;
  available: boolean;
  availability: string;
}

// Ticket Types
export interface Ticket {
  id?: number;
  ticketnumber: string;
  title: string;
  description: string;
  user_id: string;
  companyid: string;
  status: string;
  priority: string;
  issuetype?: string;
  subissuetype?: string;
  ticketcategory?: string;
  tickettype?: string;
  assigned_tech_id?: string;
  createdate: string;
  duedatetime?: string;
  resolution?: string;
  resolveddatetime?: string;
  estimatedhours?: number;
  resolutionplandatetime?: string;
  attachments?: any[];
}

export interface TicketCreateRequest {
  title: string;
  description: string;
  user_id: string;
  companyid: string;
  priority?: string;
  due_date_time?: string;
  files?: File[];
}

export interface TicketResponse {
  success: boolean;
  ticket_number: string;
  ticket_data: Partial<Ticket>;
  extracted_metadata: any;
  classification: any;
  similar_tickets_found: number;
  resolution?: string;
  assigned_tech_id?: string;
}

// Organization Types
export interface Organization {
  id?: number;
  companyid: string;
  company_name: string;
  company_email?: string;
  contact_phone?: string;
  address?: string;
  created_at?: string;
  updated_at?: string;
  status?: 'active' | 'disabled';
  subscription_plan?: 'free' | 'pro' | 'enterprise';
}

// Feedback Types
export interface ClassificationFeedback {
  ticket_number: string;
  is_correct: boolean;
  correction_data?: any;
  technician_id?: string;
  comments?: string;
}

export interface AssignmentFeedback {
  ticket_number: string;
  is_correct: boolean;
  correct_tech_id?: string;
  technician_id?: string;
  comments?: string;
}

export interface ResolutionFeedback {
  ticket_number: string;
  rating: number;
  technician_id?: string;
  comments?: string;
}

// API Response Types
export interface ApiResponse<T = any> {
  success: boolean;
  message?: string;
  data?: T;
}

export interface PaginatedResponse<T> {
  success: boolean;
  tickets?: T[];
  organizations?: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface Attachment {
  attachment_id: number;
  filename: string;
  file_type: string;
  file_size: number;
  file_path: string;
  uploaded_at: string;
}

export interface AssignmentHistory {
  assignment_id: number;
  ticket_number: string;
  tech_id: string;
  tech_name?: string;
  assigned_at: string;
  unassigned_at?: string;
  assignment_status: string;
  assignment_reason?: string;
}

export interface TechnicianAssistResponse {
  success: boolean;
  session_id?: string;
  ticket_number?: string;
  analysis?: string;
  solution?: string;
  sources: { ticket_number: string; reason: string }[];
  follow_up_questions: string[];
}
