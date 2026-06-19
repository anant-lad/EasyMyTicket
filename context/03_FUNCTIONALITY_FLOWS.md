# EasyMyTicket — Functionality & Feature Flows

---

## Feature 1: Automated Ticket Processing Pipeline

When a user submits a ticket through the portal or API, the entire process is automated through a LangGraph DAG.

```
USER SUBMITS TICKET
       │
       │  POST /api/tickets/create
       │  { title, description, user_id, source, device_id? }
       ▼
╔══════════════════════════════════════════════════════════════════╗
║  LANGGRAPH PIPELINE  (process_ticket → _graph.invoke(state))    ║
╚══════════════════════════════════════════════════════════════════╝
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  NODE 1: create_ticket                                           │
│  ──────────────────────────────────────────────────────────────  │
│  • Generate unique ID: TKT-{YYYYMMDDHHmmss}-{6hex}             │
│  • INSERT INTO new_tickets (status='Open', source='portal')      │
│  • Pass ticket_number downstream                                 │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  NODE 2: classify                                                │
│  ──────────────────────────────────────────────────────────────  │
│  Phase A — Metadata (Small LLM: llama-3.1-8b-instant):          │
│    Extract: urgency_level, affected_systems, error_messages,     │
│             user_impact, keywords (up to 8)                     │
│                                                                  │
│  Phase B — Classification (Large LLM: llama-3.3-70b):           │
│    Classify against picklist options:                            │
│    • ISSUETYPE:     Incident / Request / Problem / Change        │
│    • SUBISSUETYPE:  Specific sub-category (25 options)          │
│    • TICKETCATEGORY: Software/SaaS / Hardware / Network /        │
│                       Security / Email / Cloud / etc.           │
│    • TICKETTYPE:    Service Request / Incident / Problem         │
│    • PRIORITY:      Critical / High / Medium / Low               │
│    • category_label: normalised string for routing logic         │
│                                                                  │
│  Phase C — Semantic Search:                                      │
│    Query embedding → cosine similarity on historical_tickets     │
│    → similar_tickets[] (top 20 by similarity)                   │
│                                                                  │
│  UPDATE new_tickets SET classification fields                    │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  NODE 3: auto_route_decision                                     │
│  ──────────────────────────────────────────────────────────────  │
│  LLM Prompt: "Can desktop agent fix this with shell commands?"   │
│                                                                  │
│  CAN handle autonomously:                                        │
│    camera/audio, disk cleanup, service restarts, driver reload,  │
│    WiFi diagnostics, temp file cleanup, print spooler restart,   │
│    software install, AV scan, network ping/trace                 │
│                                                                  │
│  CANNOT handle autonomously:                                     │
│    password resets (need identity verification)                  │
│    physical hardware damage                                      │
│    policy/procurement decisions                                  │
│    multi-system incidents needing human judgment                 │
│                                                                  │
│  Decision factors:                                               │
│    can_auto_resolve = LLM says yes AND is_agent_connected(device)│
└─────────────────────────────────────────────────────────────────┘
       │
       ├──────────────────────────┐
       │ can_auto_resolve=TRUE    │ can_auto_resolve=FALSE
       │ AND device connected     │ OR device offline
       ▼                          ▼
┌─────────────────────┐   ┌─────────────────────────────────────┐
│  NODE 4a: agent_task│   │  NODE 4b: assign_tech               │
│  ─────────────────  │   │  ──────────────────────────────────  │
│  Launch async       │   │  SmartAssignmentAgent:               │
│  remediation session│   │  1. Extract required skills from     │
│  on device          │   │     issuetype mapping                │
│  (fire-and-forget   │   │  2. GET available technicians        │
│  via event loop)    │   │     (status: available/wfh)          │
│                     │   │  3. Score: exact (70%) + partial(30%)│
│  If offline:        │   │  4. Sort by (-score, workload)       │
│  Set status=        │   │  5. INSERT ticket_assignments        │
│  'Pending Agent'    │   │  6. UPDATE tech workload +1          │
└─────────────────────┘   └─────────────────────────────────────┘
       │                          │
       └──────────┬───────────────┘
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  NODE 5: generate_resolution                                     │
│  ──────────────────────────────────────────────────────────────  │
│  Large LLM (llama-3.3-70b) with context:                        │
│  • Ticket title + description                                    │
│  • Up to 3 similar resolved tickets (with their resolutions)    │
│  • Category + priority                                           │
│                                                                  │
│  Output: numbered step-by-step resolution guide                  │
│  UPDATE new_tickets SET resolution                               │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  NODE 6: notify                                                  │
│  ──────────────────────────────────────────────────────────────  │
│  NotificationAgent.send_ticket_notification()                    │
│  ├── If agent_dispatched:   "Agent dispatched for auto-fix"     │
│  ├── If auto_resolved:      "Ticket auto-resolved"               │
│  └── If human assigned:     Email technician + ticket creator   │
│                                                                  │
│  Transport: SQS notification-queue → worker pod → SMTP           │
│  Fallback:  synchronous SMTP if SQS unavailable                  │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
    RESPONSE → { ticket_number, priority, assigned_tech_id }
```

---

## Feature 2: Agentic Remote Remediation

When a device agent is connected and the ticket is auto-resolvable, a multi-turn AI loop runs on the server to fix the device remotely.

```
SERVER                              DEVICE AGENT
  │                                      │
  │  run_remediation_session()           │
  │  ─────────────────────              │
  │                                      │
  │  Create session in DB                │
  │  (agent_sessions table)             │
  │                                      │
  │  Init LLM conversation:              │
  │  System: "You are an IT engineer     │
  │   with remote terminal access"       │
  │  Human:  "Ticket: {title}"           │
  │           "Category: {category}"     │
  │           "Please diagnose & fix"    │
  │                                      │
  │  ┌── AGENTIC LOOP (max 20 steps) ──┐ │
  │  │                                 │ │
  │  │  LLM.invoke(messages)           │ │
  │  │  → tool_calls[] or text answer  │ │
  │  │                                 │ │
  │  │  ┌── If tool_call: run_command ─┤ │
  │  │  │   command, args, reasoning   │ │
  │  │  │                              │ │
  │  │  │   If TIER-2 (fix) command:   │ │
  │  │  │     request_tier2_approval() │ │
  │  │  │     Technician reviews in    │ │
  │  │  │     dashboard (5min timeout) │ │
  │  │  │     ├── Approved → proceed   │ │
  │  │  │     └── Denied → escalate    │ │
  │  │  │                              │ │
  │  │  │   dispatch_tool_call()       │──┼──► {"type":"tool_call",
  │  │  │   (via WebSocket)            │ │       "command": ...,
  │  │  │                              │ │       "args": ...,
  │  │  │   Wait for response          │ │       "session_id": ...}
  │  │  │   (timeout: 120s)            │ │
  │  │  │                    ◄─────────┼──┤  {"type":"tool_result",
  │  │  │   Append ToolMessage         │ │       "exit_code": 0,
  │  │  │   to LLM context             │ │       "output": "...",
  │  │  │                              │ │       "stderr": ""}
  │  │  ├── If tool_call: run_script   │ │
  │  │  │   Send custom bash/PS/Python │ │
  │  │  │   script to device           │ │
  │  │  │                              │ │
  │  │  ├── If tool_call: finish()     │ │
  │  │  │   resolved=true/false        │ │
  │  │  │   explanation="..."          │ │
  │  │  │   → EXIT LOOP                │ │
  │  │  │                              │ │
  │  │  └── Auto-escalate after 3      │ │
  │  │      failed fix attempts        │ │
  │  │                                 │ │
  │  └─────────────────────────────────┘ │
  │                                      │
  │  _close_session() → status in DB     │
  │  _update_ticket() → status + resolution│
  │  NotificationAgent → notify outcome  │
```

### Available Commands (TIER1 - Diagnostic, safe, no approval):
```
System:   system_info, uptime, process_list, cpu_usage
Disk:     disk_usage, find_large_files, disk_health
Memory:   memory_usage, memory_top_procs
Network:  network_interfaces, ping, dns_lookup, traceroute,
          netstat, route_table, wifi_status
Camera:   camera_list, camera_driver_check, camera_in_use_check,
          camera_permission_check, camera_v4l2_info
Security: firewall_status, av_status, startup_items
Logs:     system_log, service_log, crash_log, bluetooth_log
Software: installed_packages, pending_updates, app_version
Drivers:  driver_errors, hardware_info, usb_devices
Web:      web_search (DuckDuckGo), check_url, verify_download
```

### Available Commands (TIER2 - Fix, require technician approval):
```
Cleanup:  clear_temp, clear_app_cache
DNS:      flush_dns
Services: restart_service, stop_service, start_service
Bluetooth: restart_bluetooth, reset_bluetooth_prefs
Network:  reset_network_adapter, bring_up_adapter, release_renew_dhcp
Printing: restart_print_spooler, clear_print_queue
Packages: install_package, update_packages, install_system_updates
Drivers:  scan_and_update_drivers
Security: run_av_scan, enable_firewall
Files:    delete_file, delete_directory, reset_app_prefs
Camera:   reload_camera_driver, add_user_to_video_group, kill_camera_process
Download: download_file, install_from_file, open_browser
```

---

## Feature 3: Desktop Agent (Cross-Platform Daemon)

```
INSTALLATION                    DAILY OPERATION
─────────────                   ───────────────

install_linux.sh                Every day at 06:00 (systemd timer):
install_macos.sh                  python -m agent.main --scan
install_windows.ps1               ├── run_diagnostics()
install_ubuntu.sh                 ├── Upload to /api/monitor/report
                                  └── Or cache locally if offline
Builds to standalone binary:
  PyInstaller + build.spec       Always running (WebSocket daemon):
  ├── build_linux.sh               python -m agent.main
  ├── build_macos.sh               ├── Connect to WSS API
  └── build_windows.ps1            ├── Register: {device_id, os, hostname}
                                   ├── Drain offline queue on reconnect
                                   └── Message loop:
                                         "task"      → handle_task()
                                         "tool_call" → handle_tool_call()
                                         "ping"      → pong
                                         "shutdown"  → stop
```

**Offline resilience:**
```
Device offline:
  └── Results queued locally (offline_queue.py)
  └── On reconnect: drain_to_websocket() + drain_pending_tasks()

WebSocket auto-reconnect:
  └── Exponential backoff (RECONNECT_DELAY env var, default 10s)
  └── Handles ConnectionClosed, OSError, WebSocketException
```

---

## Feature 4: Technician Assistant (Conversational AI)

```
TECHNICIAN                          SERVER
    │                                  │
    │  POST /api/technician/assist     │
    │  {"message": "ticket T20240108  │
    │   is having bluetooth issues,   │
    │   need help"}                   │
    │                                  │
    │                                  ├── extract_request_info()
    │                                  │   LLM: extracts ticket_number + query
    │                                  │   Regex fallback for T-number pattern
    │                                  │
    │                                  ├── Get/create chat_sessions
    │                                  │
    │                                  ├── Fetch ticket from DB
    │                                  │
    │                                  ├── Load chat_messages history (last 10)
    │                                  │
    │                                  ├── find_similar_tickets() (top 5)
    │                                  │
    │                                  ├── Build conversational prompt:
    │                                  │   • Ticket context
    │                                  │   • Full conversation history
    │                                  │   • Latest query
    │                                  │   • Similar ticket resolutions
    │                                  │   • "Reasoning-First" instruction
    │                                  │
    │                                  ├── LLM → {analysis, solution,
    │                                  │          sources, follow_up_questions}
    │                                  │
    │                                  └── Save message to chat_messages
    │
    │  Response:                       │
    │  { analysis, solution,           │
    │    sources[], follow_ups[] }     │
```

---

## Feature 5: Semantic Search (Historical Ticket Similarity)

```
New ticket arrives
       │
       ▼
search_text = f"{title} {description}"
       │
       ▼
Check Redis cache (sim:{hash(text)}, TTL 1h)
  Hit → return cached results
  Miss → proceed
       │
       ▼
fastembed.TextEmbedding.embed([search_text])
  Model: sentence-transformers/all-MiniLM-L6-v2
  Output: 384-dim float vector
       │
       ▼
SELECT recent tickets from 3 tables UNION:
  closed_tickets    (LIMIT = SEMANTIC_SEARCH_BATCH_SIZE)
  resolved_tickets
  new_tickets
ORDER BY createdate DESC
       │
       ▼
Embed all candidate texts (batch)
       │
       ▼
cosine_similarity(query_emb, candidate_embs)
       │
       ▼
Filter by SIMILARITY_THRESHOLD
Sort by similarity (descending)
Take top N
       │
       ▼
Store in Redis (TTL 1h)
       │
       ▼
Return similar_tickets[]
  Used by: classify_node, generate_resolution_node,
           TechnicianAssistantAgent
```

**Full-text fallback (PostgreSQL):**
```sql
-- Index on historical_tickets:
CREATE INDEX idx_ht_fts ON historical_tickets
USING GIN(to_tsvector('english',
  COALESCE(title,'') || ' ' || COALESCE(description,'')));
```

---

## Feature 6: Frontend Dashboard (Next.js)

```
┌──────────────────────────────────────────────────────────────────┐
│  Next.js App (easymyticket-frontend/)                            │
│                                                                   │
│  app/                                                             │
│  ├── page.tsx              Landing / login                        │
│  ├── portal/               User portal                           │
│  │   ├── page.tsx          Submit new ticket form                │
│  │   └── track/page.tsx    Track existing ticket status          │
│  └── tech/                 Technician dashboard                  │
│      ├── layout.tsx        Sidebar navigation                    │
│      ├── page.tsx          Dashboard stats (live, 15s refresh)   │
│      ├── tickets/          Ticket management                     │
│      │   ├── page.tsx      Ticket list with filters              │
│      │   └── [id]/page.tsx Ticket detail + resolution viewer     │
│      ├── sessions/         AI remediation sessions               │
│      │   ├── page.tsx      Session list (active/resolved)        │
│      │   └── [id]/page.tsx Session step-by-step log viewer       │
│      └── approvals/        Tier-2 command approval queue         │
│          page.tsx          Approve/deny Tier-2 fix commands      │
│                                                                   │
│  lib/api.ts                Typed API client (fetch + X-API-Key)  │
└──────────────────────────────────────────────────────────────────┘

Dashboard Stats (auto-refresh 15s):
  Tickets: open | in_progress | pending_agent | resolved | today
  Sessions: active | awaiting_approval | resolved_today
  Agents:   connected count + device ID list

Approval Flow:
  Agent running Tier-2 fix → POST /api/agent/sessions/{id}/approve
  Dashboard shows pending approval with 5-minute countdown
  Technician approves/denies → unblocks or escalates session
```

---

## Feature 7: LLM Observability Tracing

```
Every LangChain LLM call → tracked in llm_traces table:

  trace_id      UUID
  ticket_number linked ticket
  node_name     LangGraph node (classify / gen_resolution / etc.)
  model         llama-3.3-70b-versatile / llama-3.1-8b-instant
  provider      groq / openrouter
  prompt_preview  first 500 chars
  response_preview first 500 chars
  input_tokens
  output_tokens
  latency_ms
  status        success / error / fallback
  created_at

API: GET /api/traces  → dashboard can show:
  - Per-model token usage
  - Latency percentiles
  - Error rates by node
  - Cost estimation
```

---

## Feature 8: Daily Device Health Monitoring

```
Agent (--scan mode, runs 06:00 daily):
  └── monitor.py: collect system health report
        ├── system_info (hostname, OS, version)
        ├── disk_usage (df -h output)
        ├── memory_usage (free -h / vm_stat)
        ├── cpu_usage (top / Get-Process)
        ├── list_failed_services (systemctl / Get-Service)
        └── network_interfaces (ip addr / ipconfig)

Upload: POST /api/monitor/report
  { device_id, user_id, report_data, timestamp }

If offline: cache locally in ~/.easymyticket/
  Uploaded on next successful WebSocket connection
  via send_pending_report()
```

---

## Database Schema Overview

```
                 ┌─────────────────┐
                 │  user_data       │
                 │  user_id PK      │
                 │  user_mail       │
                 └────────┬────────┘
                          │ raises
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  new_tickets (active queue)                                   │
│  ticketnumber UNIQUE NOT NULL                                 │
│  title, description, status, priority                         │
│  issuetype, subissuetype, ticketcategory, tickettype          │
│  user_id, assigned_tech_id, source, agent_task_id            │
│  resolution, createdate, duedatetime                          │
│                                                               │
│  CHECK status IN (Open/In Progress/Pending/Resolved/...)      │
│  CHECK source IN (email/portal/agent/api)                     │
└──────────────────────┬───────────────────────────────────────┘
          │            │                    │
          │            │                    │
          ▼            ▼                    ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ticket_        │ │chat_sessions │ │agent_tasks           │
│assignments    │ │session_id UUID│ │task_id UUID PK       │
│               │ │ticket_number │ │device_id             │
│ticket_number  │ └──────┬───────┘ │command_type          │
│tech_id        │        │         │command_payload JSONB  │
│skill_match    │        ▼         │status, result_output  │
│score          │ ┌──────────────┐ └──────────────────────┘
└──────────────┘ │chat_messages │
                 │role, content  │
                 │timestamp      │
                 └──────────────┘

┌─────────────────────────────────────────────────────────────┐
│  historical_tickets (73K rows — semantic search corpus)      │
│  From: cleaned_ticket_data_enhanced.xlsx (62,971)            │
│         ticket_data_updated.csv (10,000)                     │
│  Indexes: GIN full-text + issuetype + priority + createdate  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  technician_data                                              │
│  tech_id PK, tech_name, tech_mail                            │
│  skills TEXT (comma-separated)                               │
│  status CHECK (available/wfh/on_leave/busy/offline/...)      │
│  current_workload, no_tickets_assigned, solved_tickets        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  llm_traces (observability)                                   │
│  trace_id, ticket_number, node_name, model, provider         │
│  prompt_preview, response_preview                            │
│  input_tokens, output_tokens, latency_ms, status            │
└─────────────────────────────────────────────────────────────┘
```
