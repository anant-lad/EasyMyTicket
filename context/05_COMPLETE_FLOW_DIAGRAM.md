# EasyMyTicket — Complete End-to-End Flow Diagram

---

## Master System Overview

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                         EASYMYTICKET — COMPLETE SYSTEM FLOW                         ║
╚══════════════════════════════════════════════════════════════════════════════════════╝

                                    ┌─────────────────────┐
                                    │     EXTERNAL          │
                                    │                      │
                           ┌────────┤  • Groq API (LLMs)   │
                           │        │  • Gmail SMTP        │
                           │        └─────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────────────────────┐
│                          │              AWS  (ap-south-1)                            │
│                          │                                                           │
│  ┌────────────┐  ┌───────┴──────┐  ┌──────────────┐  ┌───────────────────────────┐ │
│  │   USER     │  │  NEXT.JS     │  │  TECH PORTAL  │  │  DESKTOP AGENTS           │ │
│  │  BROWSER   │  │  FRONTEND    │  │  (Next.js)    │  │  (Win / Mac / Linux)      │ │
│  │            │  │              │  │              │  │                           │ │
│  │  Submit    │  │  /portal     │  │  /tech/dash  │  │  agent/main.py            │ │
│  │  ticket    │  │  /track      │  │  /tickets    │  │  ├── WebSocket daemon      │ │
│  └────────────┘  └──────────────┘  │  /sessions   │  │  ├── Daily scan           │ │
│        │                │          │  /approvals  │  │  └── Offline queue        │ │
│        │                │          └──────────────┘  └──────────┬────────────────┘ │
│        │                │                 │                      │ WSS              │
│        │         HTTPS  │         HTTPS   │               HTTPS  │ /ws/agent/{id}  │
│        └────────────────┴─────────────────┼──────────────────────┘                 │
│                                           │                                          │
│                              ┌────────────▼─────────────────────────────────────┐   │
│                              │          ALB  (Internet-facing)                   │   │
│                              │          HTTPS:443 → EKS pods :8000              │   │
│                              └────────────────────────────────────────────────┬─┘   │
│                                                                                │     │
│                              ┌─────────────────────────────────────────────────▼─┐  │
│                              │  EKS CLUSTER  (K8s 1.32)                           │  │
│                              │                                                    │  │
│                              │  ┌────────────────────────────────────────────┐   │  │
│                              │  │  ticketing-api Pods (×2, autoscale to ×6)  │   │  │
│                              │  │                                            │   │  │
│                              │  │  FastAPI/Uvicorn  main.py                  │   │  │
│                              │  │                                            │   │  │
│                              │  │  ┌──────────────────────────────────────┐  │   │  │
│                              │  │  │         LANGGRAPH PIPELINE            │  │   │  │
│                              │  │  │                                      │  │   │  │
│                              │  │  │  create → classify → route →         │  │   │  │
│                              │  │  │  (agent|assign) → resolve → notify   │  │   │  │
│                              │  │  └──────────────────────────────────────┘  │   │  │
│                              │  │                                            │   │  │
│                              │  │  ┌──────────────────────────────────────┐  │   │  │
│                              │  │  │  AGENTIC REMEDIATION LOOP            │  │   │  │
│                              │  │  │  (remediation_graph.py)              │  │   │  │
│                              │  │  │  LLM → tool_call → dispatch →        │  │   │  │
│                              │  │  │  await result → repeat (max 20)      │  │   │  │
│                              │  │  └──────────────────────────────────────┘  │   │  │
│                              │  │                                            │   │  │
│                              │  │  Routes: tickets|agents|chat|tech|traces   │   │  │
│                              │  │  Auth:   X-API-Key middleware              │   │  │
│                              │  │  Health: /healthz /readyz (K8s probes)     │   │  │
│                              │  └────────────────────────────────────────────┘   │  │
│                              │                                                    │  │
│                              │  ┌──────────────────────────────────────────────┐ │  │
│                              │  │  ticketing-worker Pod (×1, worker nodes)      │ │  │
│                              │  │  SQS consumer → EmailSender (SMTP)            │ │  │
│                              │  └──────────────────────────────────────────────┘ │  │
│                              └────────────────────────────────────────────────────┘  │
│                                     │            │         │                          │
│                          ┌──────────▼──┐  ┌──────▼──┐  ┌──▼───────────────────────┐ │
│                          │ RDS Postgres │  │ Redis   │  │ SQS Queues               │ │
│                          │ (Private)   │  │ (Cache) │  │ notification-queue        │ │
│                          │ 10 tables   │  │ 1h TTL  │  │ llm-queue                │ │
│                          │ 73K history │  │ vectors │  │ + DLQs                   │ │
│                          └─────────────┘  └─────────┘  └──────────────────────────┘ │
│                                                                                       │
│  Supporting: ECR (3 repos) | Secrets Manager | CloudWatch | S3 (TF state + assets)  │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

---

## End-to-End Ticket Lifecycle

```
╔════════════════════════════════════════════════════════════════════════════════╗
║                        TICKET LIFECYCLE — FULL PATH                            ║
╚════════════════════════════════════════════════════════════════════════════════╝

USER                  FRONTEND              BACKEND               DEVICE AGENT
 │                       │                     │                       │
 │  Fill ticket form      │                     │                       │
 ├──────────────────────►│                     │                       │
 │                       │  POST /api/tickets  │                       │
 │                       ├────────────────────►│                       │
 │                       │  {title, desc,       │                       │
 │                       │   user_id, device_id}│                       │
 │                       │                     │                       │
 │                       │         ┌───────────▼───────────────────┐  │
 │                       │         │  LangGraph Pipeline            │  │
 │                       │         │                               │  │
 │                       │         │  1. create_ticket             │  │
 │                       │         │     → TKT-20260619-A3B2C1     │  │
 │                       │         │                               │  │
 │                       │         │  2. classify                  │  │
 │                       │         │     Small LLM: metadata       │  │
 │                       │         │     Large LLM: category +     │  │
 │                       │         │       priority + issue type   │  │
 │                       │         │     Semantic: find similar    │  │
 │                       │         │       tickets (top 20)        │  │
 │                       │         │                               │  │
 │                       │         │  3. auto_route_decision       │  │
 │                       │         │     LLM: "can agent fix it?"  │  │
 │                       │         │     + is_agent_connected()?   │  │
 │                       │         │                               │  │
 │                       │         └──────────┬──────────┬─────────┘  │
 │                       │                    │          │             │
 │                       │           YES/dev  │          │ NO/offline  │
 │                       │           connected│          │             │
 │                       │                    ▼          ▼             │
 │                       │    ┌───────────────────┐  ┌──────────────┐ │
 │                       │    │  AGENTIC PATH      │  │ HUMAN PATH   │ │
 │                       │    │  agent_task_node  │  │ assign_tech  │ │
 │                       │    │  → run_remediation│  │ score techs  │ │
 │                       │    │    _session()     │  │ → best match │ │
 │                       │    │  (async, bg task) │  └──────────────┘ │
 │                       │    └─────────┬─────────┘          │        │
 │                       │              │                     │        │
 │                       │              │  tool_call (WSS)    │        │
 │                       │              ├────────────────────►│        │
 │                       │              │  {command, args}    │ Execute│
 │                       │              │                     │ command│
 │                       │              │◄────────────────────┤        │
 │                       │              │  {output, exit_code}│        │
 │                       │              │                     │        │
 │                       │              │  [repeat up to 20x] │        │
 │                       │              │                     │        │
 │                       │    ┌─────────▼─────────┐          │        │
 │                       │    │  4. gen_resolution │          │        │
 │                       │    │     Large LLM      │          │        │
 │                       │    │     + similar tkts │          │        │
 │                       │    └─────────┬─────────┘          │        │
 │                       │              │                     │        │
 │                       │    ┌─────────▼─────────┐          │        │
 │                       │    │  5. notify         │          │        │
 │                       │    │     SQS → email   │          │        │
 │                       │    │     tech + user    │          │        │
 │                       │    └─────────┬─────────┘          │        │
 │                       │              │                     │        │
 │  ◄────────────────────◄──────────────┘                     │        │
 │  Response:            │                                    │        │
 │  {ticket_number,      │                                    │        │
 │   priority,           │                                    │        │
 │   assigned_tech_id}   │                                    │        │
 │                       │                                    │        │
 │     [minutes later]   │                                    │        │
 │  Email arrives:       │                                    │        │
 │  "Ticket Created"     │                                    │        │
```

---

## Agentic Remediation Detail Flow

```
╔══════════════════════════════════════════════════════════════════════════╗
║            AGENTIC REMEDIATION SESSION — STEP BY STEP                    ║
╚══════════════════════════════════════════════════════════════════════════╝

run_remediation_session(ticket_number, device_id, title, desc, category)
  │
  ├── _create_session() → INSERT agent_sessions (session_id UUID)
  │
  ├── Build initial messages:
  │     [SystemMessage("You are an IT engineer with terminal access")
  │      HumanMessage("Ticket: ... Category: ... Fix it.")]
  │
  ├── llm = get_llm().bind_tools([run_command, run_script, finish])
  │
  └── LOOP (step=1 to MAX_STEPS=20):
         │
         ├── Check is_agent_connected(device_id)
         │     └── Device disconnected? → escalate, break
         │
         ├── response = llm.invoke(messages)
         │
         ├── No tool_calls? → take as text explanation → mark resolved, break
         │
         └── For each tool_call:
               │
               ├── name = "finish"
               │     └── resolved=T/F, explanation, escalation_reason
               │         → break outer loop
               │
               ├── name = "run_command"
               │     ├── command in TIER2?
               │     │     └── request_tier2_approval(session_id, command, reason)
               │     │           ├── Approved (within 5min) → continue
               │     │           └── Denied → escalate, break
               │     │
               │     ├── _save_step(type="command")
               │     │
               │     ├── dispatch_tool_call(device_id, command, args, timeout=120)
               │     │     → ws.send_json({"type":"tool_call", ...})
               │     │     ← ws.recv → {"type":"tool_result", "output":...}
               │     │
               │     ├── _save_step(type="result")
               │     └── messages.append(ToolMessage(content=output))
               │
               ├── name = "run_script"
               │     ├── Send script content as inline script
               │     ├── device executes bash/powershell/python
               │     └── Same dispatch/result flow as run_command
               │
               └── fix_attempts >= 3 AND last result failed?
                     └── Auto-escalate, break

  ├── _close_session(status=resolved/escalated/failed)
  ├── _update_ticket(status, resolution)
  └── NotificationAgent.send_ticket_notification()
```

---

## Technician Approval Flow (Tier-2 Gate)

```
SESSION LOOP                BACKEND                    TECH DASHBOARD
     │                         │                            │
     │  run_command(tier2)      │                            │
     ├────────────────────────►│                            │
     │                         │  Create Future in          │
     │                         │  _pending_approvals[sid]   │
     │                         │                            │
     │                         │  ──── GET /api/agent ────►  │
     │                         │  sessions → awaiting_approval│
     │                         │  count increases by 1      │
     │                         │                            │
     │                         │                            │  Tech sees
     │                         │                            │  "Action Required"
     │                         │                            │  in dashboard
     │                         │                            │
     │                         │  ◄── POST /api/agent/  ───┤
     │                         │  sessions/{id}/approve    │
     │                         │  {approved: true/false}   │
     │                         │                            │
     │                         │  Future.set_result(True)   │
     │                         │  (or False)                │
     │                         │                            │
     │  ◄──── return approved ─┤                            │
     │                         │                            │
     │  Continue (T) or         │                            │
     │  Escalate (F)            │                            │
```

---

## Data Flow: Semantic Search in Context

```
INCOMING TICKET
  title + description
         │
         ▼
  fastembed.embed()  →  [384-dim vector]
         │
         ▼
  Redis cache check
  key: sim:{hash(title+desc)}
         │
    ┌────┴────┐
    │ HIT     │ MISS
    │         │
    │         ▼
    │   SQL UNION (closed + resolved + new tickets)
    │   ORDER BY createdate DESC LIMIT 500
    │         │
    │         ▼
    │   fastembed.embed(all_candidates)  → [N × 384]
    │         │
    │         ▼
    │   cosine_similarity([query], [N×384]) → scores[N]
    │         │
    │         ▼
    │   filter: score >= 0.3
    │   sort: descending
    │   take: top 20
    │         │
    │         ▼
    │   Redis.set(key, results, ttl=3600)
    │         │
    └────►  similar_tickets[]
              │
    ┌─────────┼─────────────────┐
    ▼         ▼                 ▼
classify    generate          tech
(context)  (resolution)    assistant
```

---

## Email Notification Flow

```
ticket created/resolved
       │
       ▼
NotificationAgent._send(payload)
       │
   ┌───┴────────────────────────────┐
   │  Try SQS (async, non-blocking) │
   │  boto3.sqs.send_message()      │
   │  queue: notification-queue     │
   └───┬────────────────────────────┘
       │ If SQS unavailable
       ▼
   EmailSender.send_email() (sync SMTP)
       │
       ▼
  gmail:587 (STARTTLS)

SQS consumer (ticketing-worker pod):
  long-poll 20s
  ├── deserialize payload
  ├── EmailSender.send_email()
  └── SQS.delete_message()

  If email fails × 3:
  └── DLQ (14-day retention)
      → manual investigation
```

---

## CI/CD Deployment Pipeline

```
Developer
   │
   │ git push origin main
   ▼
GitHub Repository
   │
   ├── Pull Request?
   │     └── GitHub Actions: test workflow
   │           ├── pip install requirements.txt
   │           ├── pytest
   │           └── ❌ Block merge if fails
   │
   └── Merge to main?
         └── GitHub Actions: deploy workflow
               │
               ├── aws ecr get-login-password → docker login
               │
               ├── docker build -t ticketing-api:${SHA} .
               │   (uses Dockerfile in EasyMyTicket/)
               │
               ├── docker push ECR:latest
               │   808812816838.dkr.ecr.ap-south-1.amazonaws.com/ticketing-api:latest
               │
               ├── aws eks update-kubeconfig
               │
               └── kubectl apply -f k8s/
                     │
                     └── RollingUpdate:
                           Step 1: Start new pod (surge +1)
                           Step 2: Wait for readiness probe /readyz
                           Step 3: Remove old pod (maxUnavailable=0)
                           → Zero downtime deployment
```

---

## Component Dependency Map

```
                     ┌─────────────────────────┐
                     │   External APIs         │
                     │   Groq (LLM inference)  │
                     │   Gmail SMTP            │
                     └────────────┬────────────┘
                                  │
              ┌───────────────────▼───────────────────┐
              │         FastAPI Application            │
              │                                       │
              │   src/llm/provider.py ──► Groq/OR     │
              │        │                              │
              │        ▼                              │
              │   src/graph/nodes.py                  │
              │        │                              │
              │   ┌────┴────────────────────┐         │
              │   │  src/agents/            │         │
              │   │  intake_classification  │         │
              │   │  smart_assignment       │         │
              │   │  resolution_generation  │         │
              │   │  technician_assistant   │         │
              │   │  notification_agent     │         │
              │   └────────────────────────┘         │
              │        │                              │
              │   ┌────▼───────────────────────────┐  │
              │   │  src/database/db_connection.py  │  │
              │   │  ├── ThreadedConnectionPool     │  │
              │   │  ├── fastembed (semantic)       │  │
              │   │  └── Groq client (direct)       │  │
              │   └────────────────────────────────┘  │
              │        │            │          │       │
              └────────┼────────────┼──────────┼───────┘
                       │            │          │
               ┌───────▼──┐  ┌──────▼──┐  ┌───▼─────────┐
               │  RDS PG16 │  │  Redis  │  │ SQS Queues  │
               │  (Primary │  │  Cache  │  │ (Async      │
               │   DB)     │  │         │  │  email)     │
               └───────────┘  └─────────┘  └─────────────┘
```

---

## Security Perimeter Summary

```
INTERNET
   │
   │ HTTPS only (port 443)
   ▼
 ALB  ──── HTTP→HTTPS redirect
   │
   │ port 8000 only (SG rule: from ALB SG)
   ▼
EKS Pods
   │
   ├── RDS:   port 5432 only (SG rule: from EKS Nodes SG only)
   ├── Redis: port 6379 only (SG rule: from EKS Nodes SG only)
   ├── SQS:   HTTPS (IAM/IRSA auth, no network exposure)
   └── Secrets Manager: HTTPS (IAM/IRSA auth)

Desktop Agent WebSocket:
   • WSS (TLS) via same ALB → same EKS pods
   • X-API-Key in headers
   • Commands: TIER1 (read-only, no approval)
                TIER2 (fix ops, technician must approve)
   • BLOCKED_TOKENS prevents destructive shell injection
   • PROTECTED_PATHS prevents OS-critical file deletion

No resources have public IPs except:
   • ALB (intentional, internet entry point)
   • NAT Gateways (egress only — no inbound possible)
```

---

## Key Numbers

| Metric | Value |
|---|---|
| Historical tickets in DB | 72,971 |
| LangGraph nodes per ticket | 6 |
| LLM calls per ticket (typical) | 3–4 |
| Max agentic remediation steps | 20 |
| Semantic search batch size | 500 candidates |
| Embedding dimensions | 384 (all-MiniLM-L6-v2) |
| Redis TTL (similarity cache) | 1 hour |
| Redis TTL (picklist) | 24 hours |
| API pod replicas (normal) | 2 |
| API pod replicas (peak, HPA) | 6 |
| RDS connections max | 200 |
| DB pool size | 2–20 per pod |
| SQS visibility timeout | 120s (email) / 300s (LLM) |
| WebSocket tool call timeout | 120s |
| Tier-2 approval timeout | 5 minutes |
| DB backup retention | 7 days |
| DLQ retention | 14 days |
| AWS Account | 808812816838 |
| AWS Region | ap-south-1 (Mumbai) |
