"""
Custom LLM Observability Tracer
================================
A LangChain callback handler that replicates LangFuse's core functionality
without any external service. Every LLM call is recorded in the `llm_traces`
PostgreSQL table and exposed via /api/traces.

Tracked per LLM call:
  - trace_id        unique ID for this observation
  - ticket_number   the ticket being processed (from context var)
  - node_name       which LangGraph node triggered the call
  - model           e.g. llama-3.3-70b-versatile
  - provider        groq | openrouter (detected from base_url / API response)
  - prompt_preview  first 500 chars of the full prompt
  - response_preview first 500 chars of the generated text
  - input_tokens    prompt token count (from usage metadata)
  - output_tokens   completion token count
  - latency_ms      wall-clock time from start to finish
  - status          success | error | fallback
  - error_message   exception text on failure
  - created_at      UTC timestamp

Context variables (set by the calling node before invoking the LLM):
    from src.observability.tracer import set_trace_context
    set_trace_context(ticket_number="TKT-20260614-ABC123", node_name="classify")
"""
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

log = logging.getLogger(__name__)

# ── Context variables (per-async-task, thread-safe) ───────────────────────────

_ctx_ticket: ContextVar[str] = ContextVar("ticket_number", default="")
_ctx_node:   ContextVar[str] = ContextVar("node_name",     default="unknown")


def set_trace_context(ticket_number: str = "", node_name: str = "unknown"):
    """Call this at the start of each LangGraph node before invoking the LLM."""
    _ctx_ticket.set(ticket_number)
    _ctx_node.set(node_name)


# ── DB writer (non-blocking best-effort) ──────────────────────────────────────

def _write_trace(record: dict):
    """
    Insert one trace row.  Uses a separate connection (not the pool) so that
    a DB failure never disrupts the LLM call itself.
    """
    try:
        from src.database.db_connection import _get_pool
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO llm_traces
                        (trace_id, ticket_number, node_name, model, provider,
                         prompt_preview, response_preview,
                         input_tokens, output_tokens, latency_ms,
                         status, error_message)
                    VALUES
                        (%(trace_id)s, %(ticket_number)s, %(node_name)s, %(model)s, %(provider)s,
                         %(prompt_preview)s, %(response_preview)s,
                         %(input_tokens)s, %(output_tokens)s, %(latency_ms)s,
                         %(status)s, %(error_message)s)
                    """,
                    record,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
    except Exception as e:
        # Never crash the LLM call — just log
        log.debug("Trace write failed (non-fatal): %s", e)


def _detect_provider(serialized: dict) -> str:
    """Detect whether this is a Groq or OpenRouter call from serialized kwargs."""
    base = (serialized.get("kwargs", {}).get("openai_api_base", "")
            or serialized.get("kwargs", {}).get("base_url", "")
            or "").lower()
    if "openrouter" in base:
        return "openrouter"
    name = (serialized.get("name", "") or serialized.get("id", [""])[-1]).lower()
    if "groq" in name:
        return "groq"
    return "unknown"


def _extract_model(serialized: dict) -> str:
    return (serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or "unknown")


def _messages_to_text(messages: List[List[BaseMessage]]) -> str:
    """Flatten message list to a single string for preview."""
    parts = []
    for batch in messages:
        for m in batch:
            role = getattr(m, "type", "msg")
            content = m.content if isinstance(m.content, str) else str(m.content)
            parts.append(f"[{role}]: {content}")
    return "\n".join(parts)


# ── Callback handler ──────────────────────────────────────────────────────────

class PostgresTracerCallback(BaseCallbackHandler):
    """
    LangChain callback that mirrors LangFuse's observation model,
    storing everything in the local `llm_traces` table.

    Lifecycle per LLM call:
        on_llm_start  → record prompt, model, provider, start time
        on_llm_end    → record response, tokens, latency, write row
        on_llm_error  → record error, write row
    """

    def __init__(self):
        super().__init__()
        self._runs: Dict[str, dict] = {}

    # ── LLM events ────────────────────────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        **kwargs,
    ):
        prompt_text = "\n".join(prompts) if prompts else ""
        self._runs[str(run_id)] = {
            "trace_id":       str(uuid.uuid4()),
            "ticket_number":  _ctx_ticket.get(""),
            "node_name":      _ctx_node.get("unknown"),
            "model":          _extract_model(serialized),
            "provider":       _detect_provider(serialized),
            "prompt_preview": prompt_text[:500],
            "_start":         time.monotonic(),
        }

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs,
    ):
        prompt_text = _messages_to_text(messages)
        self._runs[str(run_id)] = {
            "trace_id":       str(uuid.uuid4()),
            "ticket_number":  _ctx_ticket.get(""),
            "node_name":      _ctx_node.get("unknown"),
            "model":          _extract_model(serialized),
            "provider":       _detect_provider(serialized),
            "prompt_preview": prompt_text[:500],
            "_start":         time.monotonic(),
        }

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs):
        run = self._runs.pop(str(run_id), {})
        if not run:
            return

        elapsed_ms = int((time.monotonic() - run.pop("_start", time.monotonic())) * 1000)

        # Extract token usage from LangChain LLMResult
        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("usage", {}) or response.llm_output.get("token_usage", {})
        # Also try generation-level metadata (newer LangChain)
        if not usage and response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    meta = getattr(gen, "generation_info", {}) or {}
                    if "usage" in meta:
                        usage = meta["usage"]
                        break

        response_text = ""
        if response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    response_text = getattr(gen, "text", "") or str(getattr(gen, "message", ""))
                    if response_text:
                        break

        _write_trace({
            **run,
            "response_preview": response_text[:500],
            "input_tokens":     usage.get("prompt_tokens") or usage.get("input_tokens"),
            "output_tokens":    usage.get("completion_tokens") or usage.get("output_tokens"),
            "latency_ms":       elapsed_ms,
            "status":           "success",
            "error_message":    None,
        })

        log.debug(
            "Trace: node=%s model=%s provider=%s latency=%dms in=%s out=%s",
            run.get("node_name"), run.get("model"), run.get("provider"),
            elapsed_ms, usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
        )

    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs,
    ):
        run = self._runs.pop(str(run_id), {})
        if not run:
            return
        elapsed_ms = int((time.monotonic() - run.pop("_start", time.monotonic())) * 1000)
        _write_trace({
            **run,
            "response_preview": None,
            "input_tokens":     None,
            "output_tokens":    None,
            "latency_ms":       elapsed_ms,
            "status":           "error",
            "error_message":    str(error)[:500],
        })


# ── Module-level singleton ────────────────────────────────────────────────────

_handler: Optional[PostgresTracerCallback] = None


def get_tracer() -> PostgresTracerCallback:
    """Return (and lazily create) the process-level tracer instance."""
    global _handler
    if _handler is None:
        _handler = PostgresTracerCallback()
        log.info("Custom PostgreSQL LLM tracer initialised")
    return _handler
