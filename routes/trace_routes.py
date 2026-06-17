"""
LLM Observability Dashboard Routes
====================================
Exposes the custom trace data stored in `llm_traces` as a REST API.
Mirrors the key views LangFuse provides in its UI.

Endpoints:
  GET /api/traces                       — paginated list, with filters
  GET /api/traces/{trace_id}            — single trace detail
  GET /api/traces/stats/summary         — aggregate metrics (tokens, latency, errors)
  GET /api/traces/stats/by-node         — per-node breakdown
  GET /api/traces/stats/by-provider     — provider comparison (groq vs openrouter)
  GET /api/traces/ticket/{ticket_number} — all traces for a specific ticket
  DELETE /api/traces/purge              — delete traces older than N days
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.database.db_connection import DatabaseConnection

router = APIRouter()


def _db():
    return DatabaseConnection()


# ─────────────────────────────────────────────────────────────────────────────
#  Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class TraceRow(BaseModel):
    id: int
    trace_id: str
    ticket_number: Optional[str]
    node_name: Optional[str]
    model: Optional[str]
    provider: Optional[str]
    prompt_preview: Optional[str]
    response_preview: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: Optional[int]
    status: Optional[str]
    error_message: Optional[str]
    created_at: Optional[datetime]


class TraceSummary(BaseModel):
    total_calls: int
    success_calls: int
    error_calls: int
    fallback_calls: int
    total_input_tokens: Optional[int]
    total_output_tokens: Optional[int]
    avg_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    period_hours: int


# ─────────────────────────────────────────────────────────────────────────────
#  List traces
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/traces", response_model=List[TraceRow])
async def list_traces(
    limit: int   = Query(50, ge=1, le=500),
    offset: int  = Query(0, ge=0),
    node:    Optional[str] = Query(None, description="Filter by node_name"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
    status:  Optional[str] = Query(None, description="Filter by status (success|error|fallback)"),
    ticket:  Optional[str] = Query(None, description="Filter by ticket_number"),
    hours:   int = Query(24, ge=1, le=720, description="Look back N hours"),
):
    """List recent LLM traces with optional filters."""
    db = _db()
    conditions = ["created_at >= NOW() - INTERVAL '%s hours'"]
    params: list = [hours]

    if node:
        conditions.append("node_name = %s"); params.append(node)
    if provider:
        conditions.append("provider = %s"); params.append(provider)
    if status:
        conditions.append("status = %s"); params.append(status)
    if ticket:
        conditions.append("ticket_number = %s"); params.append(ticket)

    where = " AND ".join(conditions)
    params += [limit, offset]

    rows = db.execute_query(
        f"""
        SELECT id, trace_id::text, ticket_number, node_name, model, provider,
               prompt_preview, response_preview,
               input_tokens, output_tokens, latency_ms,
               status, error_message, created_at
        FROM llm_traces
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )
    return rows or []


# ─────────────────────────────────────────────────────────────────────────────
#  Single trace
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/traces/{trace_id}", response_model=TraceRow)
async def get_trace(trace_id: str):
    """Get a single trace by its UUID."""
    db = _db()
    rows = db.execute_query(
        """
        SELECT id, trace_id::text, ticket_number, node_name, model, provider,
               prompt_preview, response_preview,
               input_tokens, output_tokens, latency_ms,
               status, error_message, created_at
        FROM llm_traces WHERE trace_id = %s::uuid
        """,
        (trace_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trace not found")
    return rows[0]


# ─────────────────────────────────────────────────────────────────────────────
#  Summary stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/traces/stats/summary", response_model=TraceSummary)
async def summary_stats(hours: int = Query(24, ge=1, le=720)):
    """Overall LLM call statistics for the last N hours."""
    db = _db()
    rows = db.execute_query(
        """
        SELECT
            COUNT(*)                                            AS total_calls,
            SUM(CASE WHEN status='success'  THEN 1 ELSE 0 END) AS success_calls,
            SUM(CASE WHEN status='error'    THEN 1 ELSE 0 END) AS error_calls,
            SUM(CASE WHEN status='fallback' THEN 1 ELSE 0 END) AS fallback_calls,
            SUM(input_tokens)                                   AS total_input_tokens,
            SUM(output_tokens)                                  AS total_output_tokens,
            ROUND(AVG(latency_ms)::numeric, 1)                 AS avg_latency_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP
                (ORDER BY latency_ms)                          AS p95_latency_ms
        FROM llm_traces
        WHERE created_at >= NOW() - INTERVAL '%s hours'
        """,
        (hours,),
    )
    row = rows[0] if rows else {}
    return {
        "total_calls":        row.get("total_calls", 0),
        "success_calls":      row.get("success_calls", 0),
        "error_calls":        row.get("error_calls", 0),
        "fallback_calls":     row.get("fallback_calls", 0),
        "total_input_tokens": row.get("total_input_tokens"),
        "total_output_tokens":row.get("total_output_tokens"),
        "avg_latency_ms":     float(row.get("avg_latency_ms") or 0),
        "p95_latency_ms":     float(row.get("p95_latency_ms") or 0),
        "period_hours":       hours,
    }


@router.get("/traces/stats/by-node")
async def stats_by_node(hours: int = Query(24, ge=1, le=720)):
    """Per-LangGraph-node breakdown: call count, avg latency, error rate, token usage."""
    db = _db()
    rows = db.execute_query(
        """
        SELECT
            node_name,
            COUNT(*)                                            AS calls,
            SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)    AS errors,
            ROUND(AVG(latency_ms)::numeric, 0)                 AS avg_latency_ms,
            SUM(input_tokens)                                   AS total_input_tokens,
            SUM(output_tokens)                                  AS total_output_tokens
        FROM llm_traces
        WHERE created_at >= NOW() - INTERVAL '%s hours'
        GROUP BY node_name
        ORDER BY calls DESC
        """,
        (hours,),
    )
    return rows or []


@router.get("/traces/stats/by-provider")
async def stats_by_provider(hours: int = Query(24, ge=1, le=720)):
    """Compare Groq vs OpenRouter: call counts, latency, fallback rate."""
    db = _db()
    rows = db.execute_query(
        """
        SELECT
            provider,
            COUNT(*)                                             AS calls,
            SUM(CASE WHEN status='error'    THEN 1 ELSE 0 END)  AS errors,
            SUM(CASE WHEN status='fallback' THEN 1 ELSE 0 END)  AS fallbacks,
            ROUND(AVG(latency_ms)::numeric, 0)                  AS avg_latency_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP
                (ORDER BY latency_ms)                           AS p95_latency_ms,
            SUM(input_tokens + COALESCE(output_tokens,0))       AS total_tokens
        FROM llm_traces
        WHERE created_at >= NOW() - INTERVAL '%s hours'
        GROUP BY provider
        ORDER BY calls DESC
        """,
        (hours,),
    )
    return rows or []


# ─────────────────────────────────────────────────────────────────────────────
#  Traces for a specific ticket
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/traces/ticket/{ticket_number}")
async def traces_for_ticket(ticket_number: str):
    """All LLM calls made while processing a specific ticket, in order."""
    db = _db()
    rows = db.execute_query(
        """
        SELECT id, trace_id::text, node_name, model, provider,
               input_tokens, output_tokens, latency_ms, status, error_message, created_at
        FROM llm_traces
        WHERE ticket_number = %s
        ORDER BY created_at ASC
        """,
        (ticket_number,),
    )
    if rows is None:
        rows = []
    total_tokens = sum(
        (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0) for r in rows
    )
    total_latency = sum(r.get("latency_ms") or 0 for r in rows)
    return {
        "ticket_number": ticket_number,
        "llm_calls":     len(rows),
        "total_tokens":  total_tokens,
        "total_latency_ms": total_latency,
        "traces": rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Purge old traces
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/traces/purge")
async def purge_old_traces(days: int = Query(30, ge=1, le=365)):
    """Delete traces older than N days to control table size."""
    db = _db()
    db.execute_query(
        "DELETE FROM llm_traces WHERE created_at < NOW() - INTERVAL '%s days'",
        (days,),
    )
    return {"message": f"Traces older than {days} days deleted"}
