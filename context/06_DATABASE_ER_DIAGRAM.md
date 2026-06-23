# EasyMyTicket — Database Schema & ER Diagram

See [database_er_diagram.svg](database_er_diagram.svg) for the visual diagram.

---

## Table Groups

### Identity & Auth
| Table | Purpose |
|-------|---------|
| `organizations` | Multi-tenant org registry (Blackshift Technologies LLP = ORG001) |
| `user_data` | End users who submit tickets; holds `org_id`, `agent_api_key` |
| `technician_data` | Support techs/admins; holds `tech_role`, `is_admin`, `agent_api_key`, workload counters |

### Device Registry
| Table | Purpose |
|-------|---------|
| `devices` | Desktop agent registrations — `device_id`, `hostname`, `os_type`, `ip_address`, `last_seen` |

### Ticket System (central entity: `new_tickets`)
| Table | Purpose |
|-------|---------|
| `new_tickets` | Primary ticket table. All active tickets live here. |
| `ticket_comments` | User↔tech dialogue per ticket; `is_internal` flag for tech-only notes |
| `ticket_attachments` | S3-backed file uploads; may link to a specific comment |
| `ticket_assignments` | Audit log of tech assignments; tracks `skill_match_score` |
| `ticket_feedback` | Post-resolution feedback (rating 1–5, classification accuracy) |

### Chat
| Table | Purpose |
|-------|---------|
| `chat_sessions` | AI chatbot or direct tech-user chat sessions; `chat_type` = bot/direct |
| `chat_messages` | Individual messages within a session; `role` = user/assistant/system |

### Agent / AI Remediation
| Table | Purpose |
|-------|---------|
| `agent_sessions` | Desktop agent remediation runs; tracks `oversight_tech_id`, `step_count`, `approval_command` |
| `session_steps` | Every step the agent takes: LLM reasoning → command dispatch → output |
| `agent_tasks` | Legacy command-queue model (v2); single-shot tasks vs multi-step sessions |
| `daily_reports` | Proactive health scans sent by the desktop agent; LLM-analysed summary |

### Archive / Observability (no FK constraints — standalone)
| Table | Purpose |
|-------|---------|
| `historical_tickets` | 73K merged records for semantic search / RAG context |
| `closed_tickets` | Historical closed ticket archive for similarity search |
| `resolved_tickets` | Resolved ticket archive |
| `llm_traces` | Every LangGraph LLM call: model, tokens, latency, node name |
| `technician_attendance` | Punch-in/out log; status (available/wfh/on_leave/…) |

---

## Key Foreign Key Relationships

```
organizations ←─ user_data.org_id
organizations ←─ technician_data.org_id

user_data        ←─ new_tickets.user_id
technician_data  ←─ new_tickets.assigned_tech_id
devices          ←─ new_tickets.device_id
new_tickets      ←─ new_tickets.parent_ticket  (self-ref for re-raised tickets)

new_tickets      ←─ ticket_comments.ticket_number
ticket_comments  ←─ ticket_attachments.comment_id
new_tickets      ←─ ticket_attachments.ticket_number
new_tickets      ←─ ticket_assignments.ticket_number
technician_data  ←─ ticket_assignments.tech_id
new_tickets      ←─ ticket_feedback.ticket_number

user_data        ←─ chat_sessions.user_id        (loose FK)
new_tickets      ←─ chat_sessions.ticket_number  (optional)
chat_sessions    ←─ chat_messages.session_id

new_tickets      ←─ agent_sessions.ticket_number
devices          ←─ agent_sessions.device_id
user_data        ←─ agent_sessions.user_id
technician_data  ←─ agent_sessions.oversight_tech_id
agent_sessions   ←─ session_steps.session_id

new_tickets      ←─ agent_tasks.ticket_number
devices          ←─ agent_tasks.device_id

devices          ←─ daily_reports.device_id
user_data        ←─ daily_reports.user_id

technician_data  ←─ technician_attendance.tech_id

new_tickets      ←─ llm_traces.ticket_number  (loose, no constraint)
```

---

## `new_tickets` Status Flow

```
Open → In Progress → Resolved → Closed
     → Pending Agent → In Progress (agent running) → Resolved
                                                    → Escalated → (tech takes over)
     → Escalated
     → On Hold / Awaiting User / Cancelled / Reopened
```

`Pending Agent` = LLM decided agent can solve it, but device is offline. Auto-starts when device reconnects.

---

## Agent Session Flow

```
agent_sessions (open) → session_steps (reasoning → command → result × N)
                      → agent_sessions (resolved | escalated)
                      ↓
              escalated → assigned tech notified via email
              resolved  → ticket status = Resolved
```

`oversight_tech_id` is set from the start (dual assignment). Tech sees every step live via SSE stream at `/api/agent/sessions/{id}/stream`.

---

## Archive Tables

`historical_tickets`, `closed_tickets`, `resolved_tickets` have **no foreign key constraints**. They are:
- Populated from bulk CSV imports (73K+ records)
- Used for semantic similarity search via pgvector / full-text index
- Fed into RAG context for the LangGraph classification node
- Never shown in the frontend ticket list (display filter: `ticketnumber LIKE 'TKT-%'`)
