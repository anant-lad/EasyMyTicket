# API Mapping & Functionality Analysis

This document outlines the current state of API mappings between the Backend (FastAPI) and Frontend (React), identifying existing connections, missing functionalities that should be exposed on the UI, and configuration discrepancies.

## 1. Existing API Mappings
These endpoints are successfully mapped in the frontend `src/services` layer.

### Tickets (`src/services/tickets.ts`)
| Backend Endpoint | Frontend Method | Purpose |
|------------------|-----------------|---------|
| `POST /api/tickets/create` | `createTicket` | Create a new ticket |
| `GET /api/tickets` | `getTickets` | List all tickets |
| `GET /api/tickets/{number}` | `getTicket` | Get basic ticket details |
| `GET /api/tickets/by-id/{id}` | `getTicketById` | Get ticket by database ID |
| `GET /api/tickets/{number}/resolution` | `getTicketResolution` | Get ticket resolution |
| `PATCH /api/tickets/{number}/status` | `updateStatus` | Update ticket status |
| `PATCH /api/tickets/{number}/priority` | `updatePriority` | Update ticket priority |
| `PATCH /api/tickets/{number}/estimated-hours` | `updateEstimatedHours` | Update estimated hours |
| `PATCH /api/tickets/{number}/resolution-plan-datetime` | `updateResolutionPlan` | Update resolution plan time |
| `PATCH /api/tickets/{number}/resolve` | `resolveTicket` | Mark ticket as resolved |
| `GET /api/database/tickets/{number}/assignments` | `getAssignmentHistory` | Get assignment history |

### Database & Technicians (`src/services/database.ts`, `src/services/technicians.ts`)
| Backend Endpoint | Frontend Method | Purpose |
|------------------|-----------------|---------|
| `GET /api/database/status` | `getStatus` | Check DB status |
| `POST /api/database/start` | `startDatabase` | Start DB container |
| `POST /api/database/restart` | `restartDatabase` | Restart DB container |
| `GET /api/database/tables` | `getTables` | List DB tables |
| `GET /api/database/tables/{name}` | `getTableInfo` | Get table schema |
| `GET /api/database/tables/{name}/data` | `getTableData` | View table data |
| `DELETE /api/database/tables/{name}/clear` | `clearTable` | Clear table data |
| `GET /api/database/technicians` | `getTechnicians` | List technicians |
| `POST /api/database/technicians` | `addTechnicians` | Add new technicians |
| `PATCH /api/database/technicians/{id}/availability` | `updateAvailability` | Toggle tech availability |
| `POST /api/technician/assist` | `assistTechnician` | AI Assistant for technicians |

### Organizations (`src/services/organizations.ts`)
| Backend Endpoint | Frontend Method | Purpose |
|------------------|-----------------|---------|
| `POST /api/organizations/create` | `createOrganization` | Register organization |
| `GET /api/organizations` | `getOrganizations` | List organizations |
| `GET /api/organizations/{id}` | `getOrganization` | Get organization details |

### Feedback (`src/services/feedback.ts`)
| Backend Endpoint | Frontend Method | Purpose |
|------------------|-----------------|---------|
| `POST /api/feedback/classification` | `submitClassificationFeedback` | RLHF for classification |
| `POST /api/feedback/assignment` | `submitAssignmentFeedback` | RLHF for assignment |
| `POST /api/feedback/resolution` | `submitResolutionFeedback` | Rate resolution quality |
| `GET /api/feedback/stats` | `getFeedbackStats` | View feedback dashboard |

---

## 2. Discrepancies & Bugs
**CRITICAL**: The following mappings exist but have mismatched URLs.

| Service File | Function | Frontend Call (Wrong) | Actual Backend Route | Fix Required |
|--------------|----------|-----------------------|----------------------|--------------|
| `feedback.ts` | `exportTrainingData` | `/feedback/training-data` | `/api/training/export` | Update frontend path to `/training/export` (Note: prefix is likely `/api`) |

---

## 3. Missing Mappings & New Functionalities
The following backend endpoints exist but are **NOT** connected to the frontend. These represent opportunities for new UI features.

### A. Communication & Collaboration (High Verification Value)
*Feature: Enable chat/comments within a ticket.*
- `POST /api/tickets/{ticket_number}/communicate` - Send a message (Text, Email, etc.)
- `GET /api/tickets/{ticket_number}/communications` - View message history

### B. Ticket Queue Management (Technician Dashboard)
*Feature: dedicated view for technicians to see their assigned work.*
- `GET /api/tickets/queue/{tech_id}` - Get tickets assigned to a specific technician
- `GET /api/tickets/queue` - Get Global/Unassigned queue

### C. Advanced Ticket View
*Feature: A "Single Pane of Glass" view for tickets.*
- `GET /api/tickets/{ticket_number}/full-details` - Returns a massive object with Ticket + Technician + User + Attachments + Context + Communications + History.
    - *UI Recommendation:* Create a "Master View" or "Inspector" using this endpoint instead of parallel calls.

### D. End-User Feedback Loop
*Feature: Validation portal for ticket creators.*
- `POST /api/tickets/{ticket_number}/feedback` - Allows the *user* (not technician) to confirm if the issue is actually resolved and optionally reopen the ticket.

### E. User Management (Admin)
*Feature: Manage system users (not technicians).*
- `GET /api/database/users` - List all users
- `POST /api/database/users` - Add new users

### F. Technician Integrations
*Feature: Connect technician calendars/tools.*
- `POST /api/database/technicians/{tech_id}/oauth-client` - Configure external tool integration (OAuth).

---

## 4. Recommendations
1.  **Fix the Feedback Export Bug:** Immediate one-line fix in `feedback.ts`.
2.  **Implement Technician Dashboard:** Create a page utilizing `/tickets/queue/{techId}` to show "My Work".
3.  **Enhance Ticket Detail View:** Refactor the Ticket Detail page to use `/full-details` to show the complete lifecycle, including the newly available `communications` data.
4.  **Add Comment/Chat Component:** Create a UI component to hit the `communicate` endpoints.
