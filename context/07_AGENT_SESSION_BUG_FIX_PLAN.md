# Agent Session Stuck at 0 Steps — Root Cause & Fix Plan

## Context

Session `6539c768` for ticket `TKT-20260622144247-358C2B` ("laptop camera not working") is stuck
at `status=running`, `step_count=0` after 25+ minutes. The agent is connected (WebSocket open),
dual assignment worked (TECH003 = Shrushti), but the remediation loop never wrote a single step.

DB state confirmed via `kubectl exec`:
```
agent_sessions: status='running', step_count=0, device_id='ab58d836-...-9b0ab9290f00'
new_tickets:    status='In Progress', device_id=NULL, assigned_tech_id='TECH003'
```

---

## Root Causes

### Bug 1 — LLM call has no timeout (PRIMARY — causes the stuck session)

**File:** `EasyMyTicket/src/graph/remediation_graph.py` ~line 677

```python
# current — hangs indefinitely if Groq/OpenRouter is slow or rate-limited
response = await asyncio.get_event_loop().run_in_executor(
    None, lambda: llm.invoke(messages)
)
```

Groq hit a 429 rate limit during the ticket pipeline (logged at 14:43:13) and retried with a
4 s delay. The remediation LLM call (tool-calling format) followed immediately. If Groq held
the TCP connection open without sending a proper response (common during heavy rate limiting),
the thread blocks forever. No timeout → session stays `running` forever with 0 steps.

Also uses deprecated `asyncio.get_event_loop()` instead of `asyncio.get_running_loop()`.

**Fix — replace the LLM invoke block:**

```python
log.info("Session %s step %d: invoking LLM...", session_id[:8], step_count)
try:
    response = await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(
            None, lambda: llm.invoke(messages)
        ),
        timeout=90,   # 90 s max per LLM step
    )
except asyncio.TimeoutError:
    log.error("Session %s: LLM timed out at step %d", session_id[:8], step_count)
    escalation = f"LLM timed out at step {step_count} — Groq/OpenRouter did not respond within 90 s."
    break
except Exception as e:
    log.error("Session %s: LLM failed at step %d: %s", session_id[:8], step_count, e)
    escalation = f"LLM error at step {step_count}: {e}"
    break
```

### Bug 2 — `ticket.device_id` never written to DB

**File:** `EasyMyTicket/routes/ticket_routes.py` ~line 181

The INSERT at ticket creation doesn't include `device_id` even though `effective_device_id`
is computed (logged as "Auto-attached device") and passed to the pipeline. So `new_tickets.device_id`
always stays NULL. This breaks the reconnect auto-start path in `_auto_start_pending_sessions`.

**Fix — add before the `if ticket_request.priority:` block:**

```python
if effective_device_id:
    extra_cols += ", device_id"
    extra_vals.append(effective_device_id)
```

### Bug 3 — Current stuck session must be cleaned up manually

After deploying the fix, the existing session still hangs. Clean it up:

```bash
kubectl exec -n ticketing deployment/ticketing-api -- python3 -c "
from src.database.db_connection import DatabaseConnection
db = DatabaseConnection()
db.execute_query(
    \"UPDATE agent_sessions SET status='failed', escalation_reason='LLM timed out — session stuck before first step.', completed_at=NOW() WHERE session_id='6539c768-2ac8-4c17-9cca-2ae2c64f8d3d' AND status='running'\",
    fetch=False
)
db.execute_query(
    \"UPDATE new_tickets SET status='Open' WHERE ticketnumber='TKT-20260622144247-358C2B'\",
    fetch=False
)
print('done')
"
```

---

## Deployment

| Step | File | ConfigMap |
|------|------|-----------|
| 1 | `EasyMyTicket/src/graph/remediation_graph.py` | `remediation-graph-py` |
| 2 | `EasyMyTicket/routes/ticket_routes.py` | `ticket-routes-py` |
| 3 | `kubectl rollout restart deployment/ticketing-api -n ticketing` | — |
| 4 | Manual DB cleanup (kubectl exec python3 -c above) | — |

---

## Verification

1. After restart + cleanup, resubmit the camera ticket from the portal (agent running)
2. Watch logs: see `"invoking LLM..."` then within ~5–30 s, first step appears in the session page
3. If Groq is rate-limited again: session escalates within 90 s with a clear reason, tech gets email
4. Check `SELECT device_id FROM new_tickets WHERE ticketnumber='TKT-...'` is no longer NULL
