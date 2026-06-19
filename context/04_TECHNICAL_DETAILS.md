# EasyMyTicket — Technical Implementation Details

---

## LLM Architecture

### Model Selection Strategy

```
┌──────────────────────────────────────────────────────────────────┐
│  Two-model strategy (speed vs. accuracy tradeoff)                │
│                                                                   │
│  SMALL (fast, cheap):   llama-3.1-8b-instant                     │
│    Use cases:                                                     │
│    • Metadata extraction (classify_node step A)                   │
│    • Route decision (auto_route_decision_node)                    │
│    • Extracting ticket number from tech's natural language        │
│    Latency: ~200ms                                               │
│                                                                   │
│  LARGE (slower, accurate): llama-3.3-70b-versatile               │
│    Use cases:                                                     │
│    • Ticket classification against picklist                       │
│    • Resolution generation                                        │
│    • Technician conversational assistant                          │
│    • Agentic remediation loop (reasoning + tool calls)           │
│    Latency: ~1-3s                                                │
│                                                                   │
│  Provider: Groq API (primary)                                     │
│    Reason: fastest inference for Llama models (speculative exec)  │
│  Fallback: OpenRouter (via LLM_PROVIDER env var)                  │
│                                                                   │
│  Temperature: LLM_TEMPERATURE (config, default 0.1)              │
│  Max tokens:  LLM_MAX_TOKENS  (config, default 4096)             │
└──────────────────────────────────────────────────────────────────┘
```

### LLM Call Patterns

```
1. Direct Groq (agents layer — DatabaseConnection.call_cortex_llm):
   ─────────────────────────────────────────────────────────────
   groq.chat.completions.create(
     model="llama-3.3-70b-versatile",
     messages=[{role:system,...},{role:user,...}],
     temperature=0.1,
     max_tokens=4096
   )
   • Auto-retry with smaller model if primary fails
   • JSON parsing with markdown stripping + regex fallback

2. LangChain (graph nodes — get_llm() / get_small_llm()):
   ─────────────────────────────────────────────────────────────
   ChatGroq(model="llama-3.3-70b-versatile") | ChatPromptTemplate
   • Structured prompts with SystemMessage + HumanMessage
   • .bind_tools(_TOOLS) for agentic tool-calling (remediation loop)
   • Callbacks: every call logged to llm_traces table

3. Tool-calling (remediation_graph.py):
   ─────────────────────────────────────────────────────────────
   LLM receives: run_command, run_script, finish as tool schemas
   Returns: tool_calls[{name, args, id}]
   Server dispatches to device via WebSocket
   Response appended as ToolMessage to messages[]
```

---

## Semantic Search Implementation

```python
# Model: sentence-transformers/all-MiniLM-L6-v2 (via fastembed)
# Embedding dim: 384 floats
# Loaded once per process, reused (lazy singleton)

# Search flow:
search_text = f"{title} {description}"
query_emb = next(model.embed([search_text]))  # 384-dim vector

# Candidate pool (recent tickets, UNION across 3 tables)
# Batch: Config.SEMANTIC_SEARCH_BATCH_SIZE (default ~500)

# Batch embed all candidates
texts = [f"{t.title} {t.description}" for t in candidates]
embeddings = list(model.embed(texts))  # N × 384 matrix

# Similarity
sims = cosine_similarity([query_emb], embeddings)[0]  # shape (N,)

# Threshold filter + sort
# Config.SIMILARITY_THRESHOLD (default 0.3)
top_idx = np.argsort(sims)[::-1][:limit]
results = [candidates[i] for i in top_idx if sims[i] >= threshold]

# Cache result in Redis: sim:{hash(title+description)} TTL=3600
```

**Why fastembed:**
- Runs entirely in-process, no external embedding API calls
- all-MiniLM-L6-v2 is small (22M params) but accurate enough for IT tickets
- Zero latency on cache hit (Redis check first)

---

## Database Connection Pooling

```python
# psycopg2.ThreadedConnectionPool — thread-safe for uvicorn workers
# Process-level singleton — shared across all request handlers

_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=Config.DB_POOL_MIN,   # typically 2
    maxconn=Config.DB_POOL_MAX,   # typically 20
    host=Config.DB_HOST,           # RDS endpoint
    port=5432,
    database=Config.DB_NAME,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,  # from Secrets Manager
)

# Usage pattern (every query):
conn = pool.getconn()
try:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        conn.commit()
        return [dict(row) for row in cur.fetchall()]
except:
    conn.rollback()
    raise
finally:
    pool.putconn(conn)  # always returned to pool
```

**Why ThreadedConnectionPool:**
- uvicorn runs LangGraph nodes in thread pool executors
- DB calls from multiple threads simultaneously → pool prevents exhaustion
- Note: server runs `workers=1` (single process) because `_connected_agents`
  and `_pending_approvals` are in-process dicts; scale via HPA on single-process pods

---

## WebSocket Architecture (Agent Communication)

```
Server-side (routes/agent_routes.py):
─────────────────────────────────────
_connected_agents: Dict[str, WebSocket]  # device_id → ws
_pending_approvals: Dict[str, asyncio.Future]  # session_id → future

WS endpoint: /ws/agent/{device_id}
  1. Device connects, sends {"type": "register", "device": {...}}
  2. Stored in _connected_agents[device_id]
  3. Processes tickets with status='Pending Agent' for this device
  4. On disconnect: removed from _connected_agents

dispatch_tool_call(device_id, session_id, command, args, timeout=120):
  1. Build message: {"type":"tool_call", "session_id", "call_id", "command", "args"}
  2. ws.send_json(message)
  3. Wait for tool_result via asyncio.Future (stored in _pending_futures)
  4. When device sends {"type":"tool_result", "call_id":..., "output":...}
     → Future.set_result(result)
  5. Timeout: raise TimeoutError after 120s

request_tier2_approval(session_id, command, reasoning, timeout=300):
  1. Store Future in _pending_approvals[session_id]
  2. Await for up to 5 minutes
  3. Technician calls POST /api/agent/sessions/{id}/approve
     → Future.set_result(approved=True/False)

Client-side (agent/main.py):
─────────────────────────────
Message types handled:
  "task"       → handle_task(msg, ws)    # legacy one-shot
  "tool_call"  → handle_tool_call(msg, ws)  # agentic step
  "ping"       → send pong
  "shutdown"   → stop event loop
  "queue_stats" → report offline queue counts
```

---

## Security Model

```
API Authentication:
  All routes: X-API-Key header required (APIKeyMiddleware)
  Skipped: /healthz, /readyz, /docs, /openapi.json
  Keys stored: Secrets Manager /ticketing/prod/api-keys
  Config: VALID_API_KEYS (comma-separated list)

Desktop Agent Security:
  ├── TIER1 (diagnostic): whitelist of read-only commands only
  │     No sudo, no write operations
  ├── TIER2 (fix): requires allow_tier2=True flag
  │     Only set in agentic session context
  │     Technician must approve Tier-2 via dashboard
  ├── BLOCKED_TOKENS: absolute blocklist
  │     rm -rf /, format, mkfs, dd if=/dev/zero, shutdown, reboot, ...
  ├── PROTECTED_PATHS: cannot delete/modify
  │     /, /etc, /boot, /usr, /bin, C:\Windows, ...
  └── Script validation: blocked tokens checked before execution

Network Security:
  RDS: accessible only from EKS node SG (port 5432)
  Redis: accessible only from EKS node SG (port 6379)
  ALB: HTTPS 443 from 0.0.0.0/0
  EKS nodes: port 8000 only from ALB SG
  All private: behind NAT, no public IPs on nodes/DB/Redis

Secrets Management:
  Secrets Manager stores:
    groq-api-key, email-credentials, api-keys, redis-credentials
  Accessed via IRSA (no AWS credentials in pods)
  K8s Secret populated from Secrets Manager (manual step after apply)

Data Encryption:
  RDS: storage_encrypted = true (AES-256)
  ElastiCache: at_rest_encryption_enabled + transit_encryption_enabled
  TF State: encrypted in S3 (SSE-S3)
```

---

## Command Executor Security Detail (agent/executor.py)

```
Command execution flow:
  1. Look up command in TIER1 or TIER2 dict
  2. If TIER2 and allow_tier2=False → reject with error
  3. _pick_os(spec) → select OS-appropriate command tokens
  4. _resolve_cmd(template, args) → substitute __ARG__ placeholders
  5. Check BLOCKED_TOKENS against full command string
  6. Check PROTECTED_PATHS for delete/modify operations
  7. subprocess.run(cmd, capture_output=True, text=True, timeout=120)
     Windows: CREATE_NO_WINDOW flag
  8. Truncate: stdout[:20000], stderr[:4000]

Script execution (execute_script):
  1. Blocked token check on script content
  2. Write to NamedTemporaryFile (.sh/.ps1/.py)
  3. Run: bash / powershell -ExecutionPolicy Bypass / python3
  4. Delete temp file in finally block
  5. Timeout: 300s (scripts can be longer-running)

Web search (_web_search):
  Primary:  ddgs.DDGS().text(query, max_results=6)
  Fallback: DuckDuckGo instant answer JSON API (urllib)
  Returns:  JSON list of {title, url, snippet}
```

---

## Data Migration & Historical Dataset

```
Source datasets:
  cleaned_ticket_data_enhanced.xlsx  → 62,971 tickets (primary)
  ticket_data_updated.csv            → 10,000 tickets (legacy)
  Total: 72,971 tickets in historical_tickets table

scripts/migrate_to_rds.py:
  1. Connect to RDS via DB_HOST + DB_PASSWORD env vars
  2. Read Excel/CSV with pandas
  3. Normalize column names to lowercase
  4. INSERT in batches → historical_tickets
  5. Tag each row: source_dataset = 'enhanced' or 'legacy'

Dataset used for:
  • Semantic similarity search corpus
  • LLM context (classification consistency)
  • Fine-tuning dataset generation (dataset_creation/)

Fine-tuning JSONL outputs (dataset_creation/processed/):
  classification.jsonl    → input: title+desc, output: classification
  resolution.jsonl        → input: ticket, output: resolution steps
  instruction.jsonl       → instruction-following format
  skill_assignment.jsonl  → input: ticket, output: required skills
```

---

## Kubernetes Deployment Detail

```yaml
# api-deployment.yaml key settings:
replicas: 2  # minimum, HPA scales to 6
strategy: RollingUpdate (maxSurge:1, maxUnavailable:0)  # zero-downtime

Resources:
  requests: cpu=256m, memory=1Gi
  limits:   cpu=1000m, memory=2Gi

Probes:
  liveness:  GET /healthz (start:20s, every:15s, fail:3)
  readiness: GET /readyz  (start:10s, every:10s, fail:3)

lifecycle.preStop: sleep 5  # drain in-flight requests before SIGTERM

# HPA (hpa.yaml):
minReplicas: 2
maxReplicas: 6
metric: CPU utilization > 70%
```

---

## Configuration Reference (src/config.py)

```
Database:
  DB_HOST         RDS endpoint (from configmap)
  DB_PORT         5432
  DB_NAME         ticketing
  DB_USER         ticketinguser
  DB_PASSWORD     from K8s secret (Secrets Manager)
  DB_POOL_MIN     2
  DB_POOL_MAX     20

LLM:
  GROQ_API_KEY    from K8s secret
  LLM_PROVIDER    groq / openrouter
  LLM_TEMPERATURE 0.1
  LLM_MAX_TOKENS  4096
  CLASSIFICATION_MODEL  llama-3.3-70b-versatile

Redis:
  REDIS_ENABLED   true/false
  REDIS_HOST      ElastiCache endpoint
  REDIS_PORT      6379
  REDIS_AUTH      from Secrets Manager
  REDIS_SSL       true

SQS:
  SQS_NOTIFICATION_URL   notification queue URL
  SQS_LLM_URL            llm queue URL
  AWS_REGION             ap-south-1

Email:
  EMAIL_HOST      smtp.gmail.com
  EMAIL_PORT      587
  EMAIL_USER      from Secrets Manager
  EMAIL_PASSWORD  from Secrets Manager

Semantic Search:
  SIMILARITY_THRESHOLD    0.3
  SEMANTIC_SEARCH_BATCH_SIZE  500

App:
  HOST            0.0.0.0
  PORT            8000
  ENVIRONMENT     production
  VALID_API_KEYS  comma-separated, from Secrets Manager
```

---

## Picklist System (src/utils/picklist_loader.py)

```
Source: CSV file (loaded at startup, cached 24h in Redis)

Fields: issuetype, subissuetype, ticketcategory, tickettype, priority, status

Operations:
  get_label(field, value)     → "14" → "Cybersecurity"
  get_value(field, label)     → "Cybersecurity" → "14"
  normalize_value(field, val) → handles string/int/label variants
  format_for_prompt(field)    → "issuetype: {1: Incident, 2: Request, ...}"
  get_all_values_for_field(f) → {value: label, ...}

Used by:
  IntakeClassificationAgent  — build classification prompts
  NotificationAgent          — convert numeric IDs to human labels
  classify_node              — send picklist to LLM
  ticket_routes              — include labels in API responses
```

---

## Error Handling Philosophy

```
LangGraph nodes:
  • All errors caught, logged, appended to state["errors"]
  • Pipeline continues even if a node fails (non-fatal)
  • Only ticket creation failure is truly fatal
  • Final response always includes {"errors": [...]}

LLM calls:
  • Fallback to smaller model if primary fails
  • Fallback to keyword/heuristic if LLM returns None
  • JSON parsing: try strict → regex extract → log and return None

Database:
  • Connection returned to pool in `finally` always
  • Rollback on any exception
  • Pool reconnects automatically if connection drops

WebSocket:
  • Agent: auto-reconnect with configurable delay (default 10s)
  • Server: tool call timeout (120s) → escalate gracefully
  • Tier-2 approval: 300s timeout → auto-escalate if no response

Redis:
  • All methods return None / False if Redis unavailable
  • No exceptions propagate — caching is always optional
```

---

## Testing & CI (`.github/workflows/`)

```
PR Workflow:
  trigger: pull_request to main
  steps:
    1. pip install -r requirements.txt
    2. pytest src/tests/ -v
    3. (fail PR if tests fail)

Main Workflow:
  trigger: push to main
  steps:
    1. aws ecr get-login-password | docker login
    2. docker build -t ticketing-api:${SHA} .
    3. docker push 808812816838.dkr.ecr.ap-south-1.amazonaws.com/ticketing-api:latest
    4. aws eks update-kubeconfig --region ap-south-1 --name ticketing-prod-cluster
    5. kubectl apply -f k8s/
    (Rolling update: maxSurge:1 maxUnavailable:0 → zero downtime)
```

---

## Dataset Creation Pipeline (`dataset_creation/`)

```
Purpose: Build fine-tuning datasets from historical ticket data

Step 1: 01_download_all.sh
  Downloads raw datasets:
  ├── IT ticket datasets from Hugging Face
  ├── tldr command reference (for resolution steps)
  └── Code refinement datasets

Step 2: 02_build_unified_dataset.py
  Processes raw data into 4 JSONL outputs:
  ├── classification.jsonl   (input → output classification)
  ├── resolution.jsonl       (ticket → resolution steps)
  ├── instruction.jsonl      (instruction format for fine-tuning)
  └── skill_assignment.jsonl (ticket → required tech skills)

Step 3: 03_verify_outputs.py
  Validates JSONL format and sample statistics

These datasets can be used to:
  • Fine-tune a smaller model specific to IT support
  • Evaluate current LLM classification accuracy
  • Build a RAG knowledge base
```
