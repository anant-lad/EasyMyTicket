"""
Linux troubleshooting knowledge base — search and seed functions.

Uses the same FastEmbed + cosine_similarity pattern as find_similar_tickets()
in db_connection.py.  All raw SQL targets linux_troubleshooting_kb.

Public API:
  search_kb(query, category=None, top_k=3) -> list[dict]
  seed_kb(articles)                         -> int
  seed_from_resolved_tickets(limit=500)     -> int
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from src.database.db_connection import DatabaseConnection, get_semantic_model
from src.utils import cache as redis_cache

log = logging.getLogger(__name__)

_SCORE_THRESHOLD = 0.35
_FTS_CANDIDATE_LIMIT = 200
_REDIS_TTL = 1800  # 30 min


# ── Search ────────────────────────────────────────────────────────────────────

def search_kb(
    query: str,
    category: Optional[str] = None,
    top_k: int = 3,
) -> list[dict]:
    """
    Hybrid search: FTS candidates → FastEmbed cosine re-rank → top_k results.
    Returns list of dicts: title, category, symptoms, fix_steps, verification, score.
    """
    query = query.strip()
    if not query:
        return []

    cache_key = "kb:" + hashlib.sha256(f"{query}:{category}".encode()).hexdigest()[:32]
    cached = redis_cache.get(cache_key)
    if cached:
        log.debug("KB cache hit for query=%r", query[:60])
        return cached

    db = DatabaseConnection()

    # FTS candidates
    if category:
        candidates = db.execute_query(
            "SELECT id, title, category, symptoms, diagnostics, root_causes, "
            "fix_steps, verification, embedding "
            "FROM linux_troubleshooting_kb "
            "WHERE category = %s "
            "AND to_tsvector('english', title || ' ' || COALESCE(symptoms,'') || ' ' || COALESCE(fix_steps,'')) "
            "   @@ plainto_tsquery('english', %s) "
            "LIMIT %s",
            (category, query, _FTS_CANDIDATE_LIMIT),
        ) or []
        if not candidates:
            candidates = db.execute_query(
                "SELECT id, title, category, symptoms, diagnostics, root_causes, "
                "fix_steps, verification, embedding "
                "FROM linux_troubleshooting_kb WHERE category = %s LIMIT %s",
                (category, _FTS_CANDIDATE_LIMIT),
            ) or []
    else:
        candidates = db.execute_query(
            "SELECT id, title, category, symptoms, diagnostics, root_causes, "
            "fix_steps, verification, embedding "
            "FROM linux_troubleshooting_kb "
            "WHERE to_tsvector('english', title || ' ' || COALESCE(symptoms,'') || ' ' || COALESCE(fix_steps,'')) "
            "   @@ plainto_tsquery('english', %s) "
            "LIMIT %s",
            (query, _FTS_CANDIDATE_LIMIT),
        ) or []
        if not candidates:
            candidates = db.execute_query(
                "SELECT id, title, category, symptoms, diagnostics, root_causes, "
                "fix_steps, verification, embedding "
                "FROM linux_troubleshooting_kb LIMIT %s",
                (_FTS_CANDIDATE_LIMIT,),
            ) or []

    if not candidates:
        log.info("KB search: no candidates for query=%r", query[:60])
        return []

    # Embedding re-rank
    model = get_semantic_model()
    query_emb = next(model.embed([query]))

    stored_embs = []
    valid_idx = []
    for i, row in enumerate(candidates):
        emb = row.get("embedding")
        if emb:
            stored_embs.append(np.array(emb, dtype=np.float32))
            valid_idx.append(i)

    results = []
    if stored_embs:
        emb_matrix = np.stack(stored_embs)
        sims = cosine_similarity([query_emb], emb_matrix)[0]
        ranked = sorted(
            zip(valid_idx, sims), key=lambda x: -x[1]
        )
        for idx, score in ranked[:top_k]:
            if score < _SCORE_THRESHOLD:
                break
            row = dict(candidates[idx])
            row.pop("embedding", None)
            row["score"] = round(float(score), 4)
            results.append(row)
    else:
        # No embeddings stored yet — return FTS results as-is
        for row in candidates[:top_k]:
            row = dict(row)
            row.pop("embedding", None)
            row["score"] = 0.5
            results.append(row)

    log.info("KB search: %d results for query=%r category=%r", len(results), query[:60], category)
    redis_cache.set(cache_key, results, ttl=_REDIS_TTL)
    return results


def format_kb_context(articles: list[dict]) -> str:
    """Format KB search results as markdown for injection into the agent HumanMessage."""
    if not articles:
        return ""

    lines = [f"KNOWLEDGE BASE — {len(articles)} relevant article(s) found:\n"]
    for i, a in enumerate(articles, 1):
        score = a.get("score", 0)
        lines.append(f"[{i}] {a.get('category','').upper()}: {a.get('title','')} (relevance: {score:.2f})")
        if a.get("symptoms"):
            lines.append(f"  Symptoms: {a['symptoms'][:300]}")
        if a.get("root_causes"):
            lines.append(f"  Root cause: {a['root_causes'][:300]}")
        if a.get("fix_steps"):
            lines.append(f"  Fix:\n{_indent(a['fix_steps'][:600])}")
        if a.get("verification"):
            lines.append(f"  Verify: {a['verification'][:300]}")
        lines.append("")

    lines.append(
        "When applying a KB fix, run diagnostics first to confirm the root cause "
        "matches before executing. Run the VERIFY command verbatim to confirm resolution.\n"
    )
    return "\n".join(lines)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


# ── Seed ─────────────────────────────────────────────────────────────────────

def seed_kb(articles: list[dict]) -> int:
    """
    Insert structured KB articles into linux_troubleshooting_kb.
    Computes FastEmbed embeddings before insert.
    Returns number of rows inserted.
    """
    if not articles:
        return 0

    model = get_semantic_model()
    db = DatabaseConnection()

    texts = [
        f"{a.get('title','')} {a.get('symptoms','')} {a.get('fix_steps','')}".strip()
        for a in articles
    ]
    log.info("Computing embeddings for %d KB articles ...", len(texts))
    embeddings = list(model.embed(texts))

    inserted = 0
    for article, emb in zip(articles, embeddings):
        emb_list = emb.tolist() if hasattr(emb, "tolist") else list(emb)
        try:
            db.execute_query(
                "INSERT INTO linux_troubleshooting_kb "
                "(title, category, os_type, symptoms, diagnostics, root_causes, "
                " fix_steps, verification, source, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (
                    article.get("title", "")[:512],
                    article.get("category", "system"),
                    article.get("os_type", "Linux"),
                    article.get("symptoms", ""),
                    article.get("diagnostics", ""),
                    article.get("root_causes", ""),
                    article.get("fix_steps", ""),
                    article.get("verification", ""),
                    article.get("source", "manual"),
                    emb_list,
                ),
                fetch=False,
            )
            inserted += 1
        except Exception as e:
            log.warning("Failed to insert KB article %r: %s", article.get("title"), e)

    log.info("seed_kb: inserted %d / %d articles", inserted, len(articles))
    return inserted


def seed_from_resolved_tickets(limit: int = 500) -> int:
    """
    Pull resolved/closed tickets with a non-null resolution field,
    structure them as KB articles, and insert.
    Returns number of rows inserted.
    """
    db = DatabaseConnection()
    rows = db.execute_query(
        """
        SELECT title, description, resolution, issuetype
        FROM (
            SELECT title, description, resolution, issuetype FROM resolved_tickets
             WHERE resolution IS NOT NULL AND title IS NOT NULL
            UNION ALL
            SELECT title, description, resolution, issuetype FROM closed_tickets
             WHERE resolution IS NOT NULL AND title IS NOT NULL
        ) t
        ORDER BY random()
        LIMIT %s
        """,
        (limit,),
    ) or []

    if not rows:
        log.info("seed_from_resolved_tickets: no resolved tickets found")
        return 0

    articles = []
    for row in rows:
        title = (row.get("title") or "").strip()
        desc  = (row.get("description") or "").strip()
        res   = (row.get("resolution") or "").strip()
        cat   = (row.get("issuetype") or "system").lower().strip()
        if not title or not res:
            continue
        articles.append({
            "title":       title[:200],
            "category":    cat,
            "os_type":     "Linux",
            "symptoms":    desc[:500],
            "diagnostics": "",
            "root_causes": "",
            "fix_steps":   res[:1000],
            "verification": "",
            "source":      "resolved_ticket",
        })

    log.info("seed_from_resolved_tickets: %d tickets → seeding", len(articles))
    return seed_kb(articles)
