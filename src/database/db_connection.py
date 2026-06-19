"""
Database connection module — uses a ThreadedConnectionPool for EKS multi-worker deployment.
All Docker-specific management has been removed; connections target RDS via DB_HOST env var.
"""
import os
import json
import re
import time
import logging
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
import numpy as np
from groq import Groq
from fastembed import TextEmbedding
from sklearn.metrics.pairwise import cosine_similarity

from src.config import Config
from src.utils import cache as redis_cache

log = logging.getLogger(__name__)

# ── Semantic model (lazy, process-level singleton) ───────────────────────────

_semantic_model: Optional[TextEmbedding] = None

# FastEmbed uses HuggingFace-style names; all-MiniLM-L6-v2 is under sentence-transformers org
_FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def get_semantic_model() -> TextEmbedding:
    global _semantic_model
    if _semantic_model is None:
        log.info("Loading semantic search model %s (first time only)...", _FASTEMBED_MODEL)
        _semantic_model = TextEmbedding(_FASTEMBED_MODEL)
        log.info("Semantic search model loaded")
    return _semantic_model


# ── Connection pool (process-level singleton) ────────────────────────────────

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        db_cfg = Config.get_db_config()
        log.info("Creating connection pool: %s:%s/%s (min=%s max=%s)",
                 db_cfg["host"], db_cfg["port"], db_cfg["database"],
                 Config.DB_POOL_MIN, Config.DB_POOL_MAX)
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=Config.DB_POOL_MIN,
            maxconn=Config.DB_POOL_MAX,
            **db_cfg,
        )
    return _pool


class DatabaseConnection:
    """Wraps the shared pool; safe to instantiate per-request."""

    def __init__(self):
        self.groq_client: Optional[Groq] = None
        self._init_groq()

    # ── Groq ─────────────────────────────────────────────────────────────────

    def _init_groq(self):
        key = Config.GROQ_API_KEY.strip()
        if not key:
            raise ValueError("GROQ_API_KEY is not configured")
        self.groq_client = Groq(api_key=key)
        log.info("Groq client initialised")

    # ── Connection helpers ────────────────────────────────────────────────────

    def execute_query(
        self,
        query: str,
        params: tuple = None,
        fetch: bool = True,
    ) -> Optional[List[Dict]]:
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                conn.commit()
                if fetch and cur.description:
                    return [dict(row) for row in cur.fetchall()]
                return None
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    # ── LLM ──────────────────────────────────────────────────────────────────

    def call_cortex_llm(
        self,
        prompt: str,
        model: str = "llama-3.1-8b-instant",
        json_response: bool = True,
    ) -> Any:
        model_name = self._resolve_model(model)
        prompt = prompt.strip()

        if json_response:
            prompt += "\n\nIMPORTANT: Respond ONLY with valid JSON."

        messages = [
            {
                "role": "system",
                "content": "You are a helpful IT support assistant."
                           + (" Respond with valid JSON only." if json_response else ""),
            },
            {"role": "user", "content": prompt},
        ]

        content = self._call_groq(model_name, messages)
        if content is None:
            return None

        if not json_response:
            return content

        return self._parse_json(content)

    def _resolve_model(self, model: str) -> str:
        m = model.lower()
        if "70b" in m or "versatile" in m:
            return "llama-3.3-70b-versatile"
        return "llama-3.1-8b-instant"

    def _call_groq(self, model_name: str, messages: list) -> Optional[str]:
        fallback = "llama-3.1-8b-instant"
        for attempt_model in ([model_name] + ([fallback] if model_name != fallback else [])):
            try:
                t0 = time.time()
                resp = self.groq_client.chat.completions.create(
                    model=attempt_model,
                    messages=messages,
                    temperature=Config.LLM_TEMPERATURE,
                    max_tokens=Config.LLM_MAX_TOKENS,
                )
                log.info("Groq call model=%s elapsed=%.2fs tokens=%s",
                         attempt_model, time.time() - t0,
                         resp.usage.total_tokens if resp.usage else "?")
                return resp.choices[0].message.content.strip()
            except Exception as e:
                log.warning("Groq call failed (model=%s): %s", attempt_model, e)
        return None

    def _parse_json(self, content: str) -> Optional[dict]:
        # Strip markdown code fences
        for prefix in ("```json", "```"):
            if content.startswith(prefix):
                content = content[len(prefix):]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            log.warning("Could not parse JSON from LLM response (len=%d)", len(content))
            return None

    # ── Semantic search ───────────────────────────────────────────────────────

    def find_similar_tickets(
        self, title: str, description: str, limit: int = 20
    ) -> List[Dict]:
        log.info("Semantic search: title=%r", title[:80])

        import hashlib
        cache_key = f"sim:{hashlib.sha256((title + description).encode()).hexdigest()[:32]}"
        cached = redis_cache.get(cache_key)
        if cached:
            log.debug("Similarity cache hit")
            return cached

        model = get_semantic_model()
        search_text = f"{title} {description}".strip() or title
        query_emb = next(model.embed([search_text]))

        batch_size = Config.SEMANTIC_SEARCH_BATCH_SIZE
        sql = """
            (SELECT ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution, 'closed' AS source_table
             FROM closed_tickets WHERE title IS NOT NULL)
            UNION ALL
            (SELECT ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution, 'resolved' AS source_table
             FROM resolved_tickets WHERE title IS NOT NULL)
            UNION ALL
            (SELECT ticketnumber, title, description, issuetype, subissuetype,
                    ticketcategory, tickettype, priority, status, createdate,
                    resolveddatetime, resolution, 'new' AS source_table
             FROM new_tickets WHERE title IS NOT NULL)
            ORDER BY createdate DESC
            LIMIT %s
        """
        candidates = self.execute_query(sql, (batch_size,)) or []
        if not candidates:
            return []

        texts = [
            f"{t.get('title','') or ''} {t.get('description','') or ''}".strip()
            for t in candidates
        ]
        embeddings = list(model.embed(texts))
        sims = cosine_similarity([query_emb], embeddings)[0]

        top_idx = np.argsort(sims)[::-1][:limit]
        results = []
        for idx in top_idx:
            ticket = dict(candidates[idx])
            score = float(sims[idx])
            if score >= Config.SIMILARITY_THRESHOLD:
                ticket["similarity_score"] = score
                results.append(ticket)

        if not results:
            results = [dict(candidates[i]) for i in top_idx[:limit]]

        # Remove score before caching — callers don't expect it
        clean = [{k: v for k, v in t.items() if k != "similarity_score"} for t in results]
        redis_cache.set(cache_key, clean, ttl=3600)
        log.info("Similarity search found %d results", len(clean))
        return clean

    # ── Ticket CRUD ───────────────────────────────────────────────────────────

    def insert_ticket(self, ticket_data: Dict[str, Any]) -> Optional[str]:
        if not ticket_data.get("ticketnumber"):
            from datetime import datetime
            ticket_data["ticketnumber"] = (
                f"T{datetime.now().strftime('%Y%m%d')}.{datetime.now().strftime('%H%M%S%f')[:8]}"
            )

        columns = [k for k, v in ticket_data.items() if v is not None]
        values = [ticket_data[k] for k in columns]
        placeholders = ", ".join(["%s"] * len(columns))
        sql = (
            f"INSERT INTO new_tickets ({', '.join(columns)}) "
            f"VALUES ({placeholders}) RETURNING ticketnumber"
        )

        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, values)
                ticket_number = cur.fetchone()[0]
            conn.commit()
            return ticket_number
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    def get_all_tickets(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        issuetype: Optional[str] = None,
        user_id: Optional[str] = None,
        order_by: str = "createdate",
        order_direction: str = "DESC",
    ) -> Dict[str, Any]:
        limit = min(max(1, limit), 1000)
        offset = max(0, offset)
        order_direction = "DESC" if order_direction.upper() != "ASC" else "ASC"

        allowed_cols = {
            "createdate", "duedatetime", "ticketnumber", "title",
            "status", "priority", "issuetype", "lastactivitydate",
        }
        if order_by.lower() not in allowed_cols:
            order_by = "createdate"

        conditions, params = [], []
        for col, val in [("status", status), ("priority", priority),
                         ("issuetype", issuetype), ("user_id", user_id)]:
            if val:
                conditions.append(f"{col} = %s")
                params.append(val)

        where = " AND ".join(conditions) if conditions else "1=1"

        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM new_tickets WHERE {where}", params)
                total = cur.fetchone()[0]

            sql = (
                f"SELECT ticketnumber, title, description, user_id, createdate, "
                f"duedatetime, status, priority, issuetype, subissuetype, "
                f"ticketcategory, tickettype, lastactivitydate, resolveddatetime, "
                f"resolution, companyid, queueid, estimatedhours, assigned_tech_id "
                f"FROM new_tickets WHERE {where} "
                f"ORDER BY {order_by} {order_direction} LIMIT %s OFFSET %s"
            )
            results = self.execute_query(sql, tuple(params + [limit, offset]))
            return {
                "tickets": results or [],
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total,
            }
        finally:
            pool.putconn(conn)

    def get_ticket_by_number(self, ticket_number: str) -> Optional[Dict]:
        sql = """
            SELECT ticketnumber, title, description, status, issuetype,
                   resolution, assigned_tech_id, 'new' AS source_table
            FROM new_tickets WHERE ticketnumber = %s
            UNION ALL
            SELECT ticketnumber, title, description, status, issuetype,
                   resolution, assigned_tech_id, 'resolved' AS source_table
            FROM resolved_tickets WHERE ticketnumber = %s
            UNION ALL
            SELECT ticketnumber, title, description, status, issuetype,
                   resolution, NULL, 'closed' AS source_table
            FROM closed_tickets WHERE ticketnumber = %s
        """
        results = self.execute_query(sql, (ticket_number, ticket_number, ticket_number))
        return results[0] if results else None

    # ── Chat session helpers ──────────────────────────────────────────────────

    def create_chat_session(self, ticket_number: str) -> Optional[str]:
        result = self.execute_query(
            "INSERT INTO chat_sessions (ticket_number) VALUES (%s) RETURNING session_id",
            (ticket_number,),
        )
        return str(result[0]["session_id"]) if result else None

    def save_chat_message(self, session_id: str, role: str, content: str):
        self.execute_query(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, role, content),
            fetch=False,
        )

    def get_chat_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        results = self.execute_query(
            "SELECT role, content, timestamp FROM chat_messages "
            "WHERE session_id = %s ORDER BY timestamp ASC LIMIT %s",
            (session_id, limit),
        )
        return results or []

    def get_session_by_ticket(self, ticket_number: str) -> Optional[str]:
        result = self.execute_query(
            "SELECT session_id FROM chat_sessions "
            "WHERE ticket_number = %s ORDER BY created_at DESC LIMIT 1",
            (ticket_number,),
        )
        return str(result[0]["session_id"]) if result else None

    def close(self):
        """No-op: pool is process-level; connections are returned after each query."""
        pass
