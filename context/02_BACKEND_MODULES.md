# EasyMyTicket — Backend Modules & Services

**Stack:** Python 3.12, FastAPI, LangGraph, LangChain, Groq API, PostgreSQL 16, Redis 7, SQS

---

## Application Entry Point — `main.py`

```
FastAPI App (v2.0.0)
│
├── Middleware
│     ├── APIKeyMiddleware  — checks X-API-Key header on all routes
│     │                       skips /healthz, /readyz, /docs paths
│     └── CORSMiddleware    — open for now (tighten in prod via ALLOWED_ORIGINS)
│
├── Startup Events
│     ├── Capture uvicorn asyncio event loop → stored in agent_routes._main_loop
│     │     (required so LangGraph threads can dispatch WebSocket coroutines)
│     ├── Config.validate()  — check all required env vars present
│     └── run_migrations()   — idempotent schema migrations (E1–E5 additions)
│
├── Health Probes (K8s)
│     ├── GET /healthz  — liveness:  always 200 if process alive
│     └── GET /readyz   — readiness: 200 only if DB pool connects
│
└── Routers (all under /api except agent + monitoring + chat)
      ├── /api/tickets/*         ticket_routes
      ├── /api/database/*        database_routes
      ├── /api/technician/*      technician_routes
      ├── /ws/agent/*  etc.      agent_routes
      ├── /api/traces/*          trace_routes
      ├── /healthz etc.          monitoring_routes
      └── /api/chat/*            chat_routes
```

---

## Module Map

```
EasyMyTicket/
├── main.py                        FastAPI entry point
├── src/
│   ├── config.py                  Central config (reads env vars)
│   ├── agents/                    AI Agent layer
│   │   ├── intake_classification.py   Metadata extraction + ticket classification
│   │   ├── smart_ticket_assignment.py Skill-match technician assignment
│   │   ├── resolution_generation.py   LLM-based resolution synthesis
│   │   ├── technician_assistant.py    Conversational chat for techs
│   │   └── notification_agent.py      Email dispatch (SQS-first, sync fallback)
│   ├── graph/                     LangGraph pipeline
│   │   ├── ticket_graph.py            Main ticket processing DAG
│   │   ├── nodes.py                   All 6 LangGraph node implementations
│   │   ├── state.py                   TicketState TypedDict
│   │   ├── auto_resolve.py            Keyword-rule fallback for routing
│   │   ├── remediation_graph.py       Agentic multi-turn repair loop
│   │   ├── chat_graph.py              Chat session management
│   │   └── daily_report_graph.py      Scheduled daily diagnostics
│   ├── database/
│   │   ├── db_connection.py           ThreadedConnectionPool + Groq + semantic search
│   │   ├── create_tables_v2.sql       RDS schema (v2) — 10 tables, 12+ indexes
│   │   ├── create_tables.sql          Legacy schema (v1)
│   │   └── migrations.py              Idempotent ALTER TABLE migrations
│   ├── llm/
│   │   └── provider.py                LangChain LLM factory (Groq / OpenRouter)
│   ├── utils/
│   │   ├── cache.py                   Redis wrapper (get/set/delete, graceful fallback)
│   │   ├── queue.py                   SQS notification producer
│   │   ├── email_sender.py            SMTP email (Gmail / SMTP relay)
│   │   ├── logger.py                  Structured JSON logging
│   │   ├── picklist_loader.py         CSV picklist loader (normalize/lookup values)
│   │   └── database_startup.py        Retry loop waiting for DB at startup
│   ├── middleware/
│   │   └── auth.py                    APIKeyMiddleware (Starlette)
│   └── guardrails/
│       ├── guardrails.py              LLM output validation
│       └── config.yml                 Guardrails rules
├── routes/
│   ├── ticket_routes.py               POST/GET/PATCH ticket endpoints
│   ├── database_routes.py             Tech/user data CRUD
│   ├── technician_routes.py           Tech assist endpoint
│   ├── agent_routes.py                WebSocket server + approval gates
│   ├── chat_routes.py                 Chat session endpoints
│   ├── trace_routes.py                LLM observability dashboard
│   └── monitoring_routes.py           /healthz, /readyz, stats
├── agent/                         Desktop Agent (cross-platform)
│   ├── main.py                        Agent entry point (WebSocket + scan modes)
│   ├── executor.py                    Command registry (TIER1 + TIER2) + script runner
│   ├── diagnostics.py                 System health collectors
│   ├── monitor.py                     Daily scan scheduler
│   ├── reporter.py                    Upload scan results to backend
│   ├── offline_queue.py               Local queue for offline operation
│   └── installer/                     OS-specific install scripts
├── infra/terraform/               AWS IaC
└── k8s/                           Kubernetes manifests
```

---

## AI Agents (src/agents/)

### 1. Intake Classification Agent (`intake_classification.py`)

**Purpose:** Extract structured metadata and classify a new ticket using LLM.

```
┌──────────────────────────────────────────────────────────────────┐
│  IntakeClassificationAgent                                        │
│                                                                   │
│  extract_metadata(title, description)                             │
│  ────────────────────────────────────                             │
│  Prompt → Groq llama-3.1-8b-instant                               │
│  Returns JSON:                                                    │
│    main_issue, affected_system, urgency_level,                    │
│    error_messages, technical_keywords,                            │
│    user_actions, resolution_indicators, STATUS="Open"             │
│                                                                   │
│  classify_ticket(ticket, metadata, similar_tickets)               │
│  ────────────────────────────────────────────────                 │
│  1. Build summary of most-common classification values            │
│     across similar historical tickets (Counter-based)             │
│  2. Prompt → Groq llama-3.3-70b-versatile                         │
│     Content-first analysis: classify ISSUETYPE, SUBISSUETYPE,     │
│     TICKETCATEGORY, TICKETTYPE, PRIORITY, STATUS                  │
│  3. Normalize output via picklist_loader                          │
│     (handles LLM returning labels vs. numeric IDs)               │
│  4. Fallback: keyword-matching classification if LLM fails        │
│                                                                   │
│  Picklist: 6 fields, loaded from CSV at startup, cached in Redis  │
└──────────────────────────────────────────────────────────────────┘
```

### 2. Smart Ticket Assignment Agent (`smart_ticket_assignment.py`)

**Purpose:** Match ticket to the best available technician using skill scoring.

```
┌──────────────────────────────────────────────────────────────────┐
│  SmartAssignmentAgent                                             │
│                                                                   │
│  assign_ticket(ticket_data, classification)                       │
│  ────────────────────────────────────────                         │
│  Step 1: Extract required skills from issuetype                   │
│          e.g. issuetype '14' → ['Cybersecurity', 'Security']      │
│                                                                   │
│  Step 2: SELECT technicians WHERE status IN ('available','wfh')   │
│          ORDER BY current_workload ASC                            │
│                                                                   │
│  Step 3: Score each technician (0–100)                            │
│          Exact skill match  → 70% weight                          │
│          Partial word match → 30% weight                          │
│          Threshold: score > 30 to be considered                   │
│                                                                   │
│  Step 4: If no tech clears threshold → reranker                   │
│          Semantic keyword overlap between ticket and tech skills   │
│          Returns top-5 candidates                                 │
│                                                                   │
│  Step 5: Sort by (−score, workload) → pick best                   │
│  Step 6: INSERT ticket_assignments record                         │
│  Step 7: UPDATE technician_data.current_workload += 1             │
│                                                                   │
│  decrement_workload(tech_id)  — called on ticket resolve          │
│    current_workload -= 1, solved_tickets += 1                     │
└──────────────────────────────────────────────────────────────────┘
```

**Skill map (issuetype → skills):**
```
'11' → Cloud, Email, Office 365, OneDrive, SharePoint
'4'  → Hardware, Network, Assessment
'5'  → Software, Installation, SaaS
'6'  → Network, VPN, Remote Access
'8'  → Server, Administration, Database
'9'  → Active Directory, File Permissions, Access Control
'13' → Backup, DATTO, Azure
'14' → Cybersecurity, Intrusion, Security
'18' → Printer, Printing, Hardware
```

### 3. Resolution Generation Agent (`resolution_generation.py`)

**Purpose:** Generate step-by-step resolution guide using similar resolved tickets as context.

```
┌──────────────────────────────────────────────────────────────────┐
│  ResolutionGenerationAgent                                        │
│                                                                   │
│  generate_resolution(ticket, metadata, similar_tickets)           │
│  ─────────────────────────────────────────────────────           │
│  1. Filter similar tickets that have non-empty resolutions        │
│                                                                   │
│  2. Build prompt with up to 5 similar ticket resolutions          │
│     as reference context                                          │
│                                                                   │
│  3. Call Groq llama-3.3-70b-versatile                             │
│     Instructs: ~10 actionable technical steps with commands       │
│     Response format: {"steps": ["Step 1: ...", ...]}             │
│                                                                   │
│  4. Extract text from various LLM response formats                │
│     (handles 'steps', 'resolution', 'content', plain strings)    │
│                                                                   │
│  Fallback paths (if LLM fails):                                   │
│  ├── Pattern from similar resolutions                             │
│  └── Hard-coded technical steps by category:                      │
│        email/vpn/network/printer/password → domain-specific cmds  │
│        generic → systemctl, Event Viewer, journalctl steps        │
└──────────────────────────────────────────────────────────────────┘
```

### 4. Technician Assistant Agent (`technician_assistant.py`)

**Purpose:** Conversational AI assistant for technicians working on a ticket.

```
┌──────────────────────────────────────────────────────────────────┐
│  TechnicianAssistantAgent                                         │
│                                                                   │
│  assist_technician(input_text, session_id)                        │
│  ────────────────────────────────────────                         │
│  Step 1: extract_request_info()                                   │
│          LLM extracts {ticket_number, query} from free-form text  │
│          Regex fallback if LLM misses T-number pattern            │
│                                                                   │
│  Step 2: Session management                                       │
│          GET/CREATE chat_sessions record (UUID)                   │
│                                                                   │
│  Step 3: Load ticket details + conversation history               │
│          (last 10 chat_messages for context window)               │
│                                                                   │
│  Step 4: find_similar_tickets(title, description, limit=5)        │
│          Semantic search on historical_tickets                     │
│                                                                   │
│  Step 5: Build conversational prompt                              │
│          Includes: ticket info, history, query, similar tickets    │
│          "Reasoning-First" approach — identify blockers first     │
│          Output: {analysis, solution, sources, follow_up_questions}│
│                                                                   │
│  Step 6: Call Groq llama-3.3-70b-versatile                        │
│  Step 7: Save assistant reply to chat_messages                    │
└──────────────────────────────────────────────────────────────────┘
```

### 5. Notification Agent (`notification_agent.py`)

**Purpose:** Email notifications to technicians and ticket creators, async via SQS.

```
┌──────────────────────────────────────────────────────────────────┐
│  NotificationAgent                                                │
│                                                                   │
│  _send(payload)  — core dispatch                                  │
│  ├── Try: SQS.send_message(queue_url, body=payload)               │
│  │         (fire-and-forget, non-blocking)                        │
│  └── Fallback: EmailSender.send_email() synchronously            │
│                (SMTP via Gmail / configured relay)                │
│                                                                   │
│  notify_technician(ticket_data, tech_data)                        │
│    Subject: "New Ticket Assigned: TKT-xxx — Title"               │
│    Body: ticket number, title, description, priority, due date    │
│                                                                   │
│  notify_user(ticket_data, user_data, tech_data)                   │
│    Subject: "Ticket Created: TKT-xxx"                             │
│    Body: ticket details + assigned tech info                      │
│                                                                   │
│  send_ticket_notification(...)  — high-level orchestrator         │
│    Looks up tech/user email from DB                               │
│    Sends different message based on outcome:                      │
│    ├── agent_dispatched=True → "Agent dispatched for auto-fix"    │
│    ├── auto_resolved=True   → "Ticket auto-resolved"              │
│    └── else                 → "Technician assigned"               │
└──────────────────────────────────────────────────────────────────┘
```

---

## LangGraph Pipeline (src/graph/)

### Ticket Processing DAG (`ticket_graph.py`)

```
                 create_ticket_node
                        │
                        ▼
                   classify_node
                        │
                        ▼
              auto_route_decision_node
                  (LLM decides)
                  /            \
         can_auto_resolve=True   can_auto_resolve=False
         AND device connected    OR device offline
                /                          \
      agent_task_node              assign_technician_node
                \                          /
                 ▼                        ▼
              generate_resolution_node
                        │
                        ▼
                   notify_node
                        │
                        ▼
                       END
```

### Node Details (`nodes.py`)

**Node 1 — create_ticket_node:**
```
Input:  title, description, user_id, source, device_id
Action: INSERT INTO new_tickets with unique TKT-{timestamp}-{hex} ID
Output: ticket_number
```

**Node 2 — classify_node (two-step):**
```
Step A (small LLM — fast):
  → get_small_llm() extracts metadata JSON
     {urgency_level, affected_systems, error_messages, user_impact, keywords}

Step B (large LLM — accurate):
  → get_llm() classifies against picklist values
     {issuetype, subissuetype, ticketcategory, tickettype, priority, status, category_label, confidence}

Step C (semantic search):
  → db.find_similar_tickets() returns top matches from historical/closed/resolved
  → UPDATE new_tickets SET classification fields
```

**Node 3 — auto_route_decision_node (LLM-based):**
```
LLM prompt: "Can a desktop agent resolve this by running shell commands?"
  CAN handle: camera/audio/display, disk cleanup, service restarts,
              driver reloads, network diagnostics, printer issues
  CANNOT:     password resets, physical damage, policy decisions

Returns: {can_agent_solve: bool, confidence: float, reasoning, suggested_first_command}

Also checks: is_agent_connected(device_id)  — WebSocket registry lookup
```

**Node 4a — agent_task_node (auto-resolve path):**
```
If device connected:
  → asyncio.run_coroutine_threadsafe(run_remediation_session(...), _main_loop)
  → Fire-and-forget: session runs async in background
  → Returns immediately so graph continues to notify

If device offline:
  → UPDATE new_tickets SET status='Pending Agent'
  → Session starts when device reconnects
```

**Node 4b — assign_technician_node (human path):**
```
→ SmartAssignmentAgent.assign_ticket()
→ UPDATE new_tickets SET assigned_tech_id
```

**Node 5 — generate_resolution_node:**
```
→ LLM prompt with ticket details + up to 3 similar resolved tickets
→ Structured numbered steps in plain English
→ UPDATE new_tickets SET resolution
```

**Node 6 — notify_node:**
```
→ NotificationAgent.send_ticket_notification()
→ Emails technician (if assigned) + ticket creator
→ Message varies by path (agent dispatched / human assigned)
```

---

## Database Layer (`src/database/db_connection.py`)

```
┌──────────────────────────────────────────────────────────────────┐
│  DatabaseConnection  (instantiate per-request, uses shared pool) │
│                                                                   │
│  Connection Pool (process-level singleton)                        │
│  ├── psycopg2.ThreadedConnectionPool                              │
│  │     minconn=2, maxconn=20 (from Config)                        │
│  │     Targets: DB_HOST (RDS endpoint via env var)                │
│  └── getconn() / putconn() pattern — auto-return after query     │
│                                                                   │
│  Groq Client (per-instance)                                       │
│  └── groq.Groq(api_key=GROQ_API_KEY)                             │
│       call_cortex_llm(prompt, model, json_response)               │
│       ├── Resolves model: "70b"/"versatile" → llama-3.3-70b      │
│       │                   else              → llama-3.1-8b-instant│
│       ├── Calls Groq API (primary)                                │
│       └── Falls back to llama-3.1-8b-instant if primary fails    │
│                                                                   │
│  Semantic Search (lazy process-level singleton)                   │
│  └── fastembed.TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')│
│       find_similar_tickets(title, description, limit=20)          │
│       ├── Check Redis cache (key: sim:{hash(text)}, TTL 1h)       │
│       ├── Query: UNION of closed/resolved/new tickets (recent N)  │
│       ├── Embed all candidates with fastembed                     │
│       ├── cosine_similarity(query_emb, all_embs)                  │
│       ├── Filter by SIMILARITY_THRESHOLD                          │
│       └── Cache result, return top matches                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## Redis Cache (`src/utils/cache.py`)

```
Config: REDIS_HOST, REDIS_PORT, REDIS_AUTH, REDIS_SSL
        Graceful fallback: if Redis unavailable → all ops no-op

Usage:
  sim:{hash}        → semantic search results        TTL: 1h
  picklist:{field}  → picklist CSV lookup data       TTL: 24h

ElastiCache (AWS):
  Engine: Redis 7.1
  TLS: transit_encryption_enabled = true
  Auth: random 32-char token in Secrets Manager
  Eviction: allkeys-lru
```

---

## API Routes Summary

| Route | Method | Purpose |
|---|---|---|
| `/api/tickets/create` | POST | Run full LangGraph pipeline |
| `/api/tickets` | GET | List with filter/pagination |
| `/api/tickets/{id}` | GET | Single ticket + labels |
| `/api/tickets/{id}/resolve` | PATCH | Mark resolved, decrement workload |
| `/api/tickets/{id}/feedback` | POST | Rating + classification feedback |
| `/api/database/technicians` | GET | List all technicians |
| `/api/technician/assist` | POST | Conversational tech assistant |
| `/ws/agent/{device_id}` | WebSocket | Desktop agent connection |
| `/api/agent/sessions` | GET | List agentic sessions |
| `/api/agent/sessions/{id}/approve` | POST | Approve/deny Tier-2 command |
| `/api/sessions/{id}/steps` | GET | Session step history |
| `/api/agents/connected` | GET | List connected device IDs |
| `/api/chat/message` | POST | Chat with ticket context |
| `/api/chat/{id}/history` | GET | Chat message history |
| `/api/traces` | GET | LLM observability data |
| `/api/dashboard/stats` | GET | Dashboard metrics |
| `/healthz` | GET | Kubernetes liveness |
| `/readyz` | GET | Kubernetes readiness (DB check) |

---

## LLM Provider Layer (`src/llm/provider.py`)

```
Provider selection (env: LLM_PROVIDER):
  "groq"        → Groq API (llama models, very fast, free tier)
  "openrouter"  → OpenRouter.ai (broader model selection)

get_llm()       → Large model  (llama-3.3-70b-versatile)
get_small_llm() → Small model  (llama-3.1-8b-instant)
get_callbacks() → LangChain callbacks for LLM tracing

Traces: every LangChain call → INSERT INTO llm_traces
  Captures: model, provider, prompt preview, response preview,
            input/output tokens, latency_ms, status
```

---

## SQS Queue Architecture (`src/utils/queue.py`)

```
notification-queue
  Visibility timeout:  120s (email worker processing time)
  Retention:           1 day
  Long polling:        20s
  DLQ after 3 fails → notification-dlq (14-day retention)

llm-queue
  Visibility timeout:  300s (LLM inference time)
  Retention:           1 hour
  DLQ after 2 fails → llm-dlq (14-day retention)

Producer (NotificationAgent._send):
  boto3.sqs.send_message(QueueUrl, MessageBody=json.dumps(payload))

Consumer (ticketing-worker pod):
  Long-poll loop → deserialize → EmailSender.send_email()
```
