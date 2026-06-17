#!/usr/bin/env python3
"""
db_bootstrap.py — runs inside the EKS bootstrap Job.

Steps:
  1. Download schema SQL from S3 and apply via psycopg2
  2. Seed historical_tickets + closed_tickets from Excel (55K rows)
  3. Seed from resolution.jsonl (MSP real tickets only)
  4. Print row-count verification

All credentials come from environment variables injected by the K8s Secret.
S3 access comes from IRSA (pod service account) — no AWS keys needed in spec.
"""
import boto3
import io
import json
import logging
import os
import sys

import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bootstrap")

# ── Config from env ───────────────────────────────────────────────────────────
DB_HOST     = os.environ["DB_HOST"]
DB_PORT     = int(os.environ.get("DB_PORT", 5432))
DB_NAME     = os.environ["DB_NAME"]
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
S3_BUCKET   = os.environ.get("S3_BUCKET", "ticketing-prod-datasets-808812816838")
AWS_REGION  = os.environ.get("AWS_REGION", "ap-south-1")
BATCH_SIZE  = int(os.environ.get("BATCH_SIZE", 500))

_ISSUETYPE_CATEGORY = {
    "4": "hardware",            "5": "software",
    "6": "network",             "7": "general_inquiry",
    "8": "software",            "9": "account_access",
    "10": "email_collaboration","11": "cloud_infrastructure",
    "12": "hardware",           "13": "backup_recovery",
    "14": "security",           "15": "email_collaboration",
    "16": "hardware",           "17": "general_inquiry",
    "18": "hardware",           "19": "software",
    "20": "security",           "21": "billing",
    "22": "security",           "23": "account_access",
    "25": "security",           "26": "general_inquiry",
}

_PRIORITY_MAP = {
    "1": "critical", "2": "high", "3": "medium", "4": "low", "5": "low",
    "critical": "critical", "high": "high", "medium": "medium", "low": "low",
}


def _to_priority(raw) -> str:
    if raw is None:
        return "medium"
    return _PRIORITY_MAP.get(str(raw).strip().lower(), "medium")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD, sslmode="require",
    )


def s3_download(s3_client, key: str) -> bytes:
    log.info("S3 ← s3://%s/%s", S3_BUCKET, key)
    obj = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
    data = obj["Body"].read()
    log.info("  downloaded %d bytes", len(data))
    return data


# ── Step 1: Apply schema ──────────────────────────────────────────────────────

def apply_schema(conn, sql: str):
    log.info("Applying schema …")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Schema applied")


# ── Step 2: Seed from Excel ───────────────────────────────────────────────────

_INSERT_H = """
INSERT INTO historical_tickets
    (ticketnumber, title, description, resolution, issuetype,
     priority, status, createdate, source_dataset)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""

_INSERT_C = """
INSERT INTO closed_tickets
    (ticketnumber, title, description, resolution, issuetype,
     priority, status, createdate)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""


def seed_excel(conn, data: bytes) -> int:
    import pandas as pd
    log.info("Parsing Excel (%d MiB) …", len(data) // (1024 * 1024))
    df = pd.read_excel(io.BytesIO(data))
    if "DATA_SOURCE" in df.columns:
        df = df[df["DATA_SOURCE"].astype(str).str.lower() == "real"]
    # Coerce date columns — some cells contain bare time strings that psycopg2 rejects
    for col in ("CREATEDATE", "COMPLETEDDATE", "DUEDATETIME", "RESOLVEDDATETIME"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    log.info("Excel: %d real rows", len(df))

    rows_h, rows_c = [], []
    inserted = skipped = 0

    for _, row in df.iterrows():
        title = str(row.get("TITLE", "") or "")[:500].strip()
        desc  = str(row.get("DESCRIPTION", "") or "")[:10000].strip()
        res   = str(row.get("RESOLUTION", "") or "")[:10000].strip()
        if len(title) + len(desc) < 20:
            skipped += 1
            continue

        tnum      = str(row.get("TICKETNUMBER", "") or "").strip() or f"HST-{inserted}"
        issuetype = str(row.get("ISSUETYPE", "") or "").strip()
        priority  = _to_priority(row.get("PRIORITY"))
        status    = str(row.get("STATUS", "Closed") or "Closed")[:50]
        import pandas as pd
        raw_date   = row.get("CREATEDATE")
        createdate = None if (raw_date is None or pd.isna(raw_date)) else raw_date

        rows_h.append((tnum, title, desc, res or None, issuetype or None,
                       priority, status, createdate, "enhanced"))
        rows_c.append((tnum, title, desc, res or None, issuetype or None,
                       priority, status, createdate))

        if len(rows_h) >= BATCH_SIZE:
            with conn.cursor() as cur:
                execute_batch(cur, _INSERT_H, rows_h)
                execute_batch(cur, _INSERT_C, rows_c)
            conn.commit()
            inserted += len(rows_h)
            log.info("  … %d rows inserted", inserted)
            rows_h.clear()
            rows_c.clear()

    if rows_h:
        with conn.cursor() as cur:
            execute_batch(cur, _INSERT_H, rows_h)
            execute_batch(cur, _INSERT_C, rows_c)
        conn.commit()
        inserted += len(rows_h)

    log.info("Excel seed complete: %d inserted, %d skipped", inserted, skipped)
    return inserted


# ── Step 3: Seed from JSONL ───────────────────────────────────────────────────

_INSERT_HJ = """
INSERT INTO historical_tickets
    (ticketnumber, title, description, resolution, priority, source_dataset)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""

_INSERT_CJ = """
INSERT INTO closed_tickets
    (ticketnumber, title, description, resolution, priority)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""


def seed_jsonl(conn, data: bytes) -> int:
    log.info("Parsing JSONL (%d MiB) …", len(data) // (1024 * 1024))
    rows_h, rows_c = [], []
    inserted = 0

    for i, raw_line in enumerate(data.decode("utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("source") != "user_msp_real":
            continue

        problem    = obj.get("problem", "")
        resolution = obj.get("resolution", "")
        if not problem or not resolution:
            continue

        parts = problem.split("\n", 1)
        title = parts[0].strip()[:500]
        desc  = parts[1].strip()[:10000] if len(parts) > 1 else ""
        if not title:
            continue

        tnum = f"JSONL-{i:07d}"
        rows_h.append((tnum, title, desc, resolution, "medium", "resolution_jsonl"))
        rows_c.append((tnum, title, desc, resolution, "medium"))

        if len(rows_h) >= BATCH_SIZE:
            with conn.cursor() as cur:
                execute_batch(cur, _INSERT_HJ, rows_h)
                execute_batch(cur, _INSERT_CJ, rows_c)
            conn.commit()
            inserted += len(rows_h)
            log.info("  … %d JSONL rows inserted", inserted)
            rows_h.clear()
            rows_c.clear()

    if rows_h:
        with conn.cursor() as cur:
            execute_batch(cur, _INSERT_HJ, rows_h)
            execute_batch(cur, _INSERT_CJ, rows_c)
        conn.commit()
        inserted += len(rows_h)

    log.info("JSONL seed complete: %d inserted", inserted)
    return inserted


# ── Step 4: Verify ────────────────────────────────────────────────────────────

def verify(conn):
    tables = ["historical_tickets", "closed_tickets", "new_tickets",
              "technician_data", "agent_tasks", "llm_traces"]
    log.info("Row counts:")
    with conn.cursor() as cur:
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                n = cur.fetchone()[0]
                log.info("  %-25s %d", t, n)
            except Exception as e:
                log.warning("  %-25s ERROR: %s", t, e)
                conn.rollback()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== EasyMyTicket DB Bootstrap ===")
    log.info("Target: %s:%d/%s", DB_HOST, DB_PORT, DB_NAME)

    s3 = boto3.client("s3", region_name=AWS_REGION)
    conn = get_conn()
    log.info("Connected to RDS")

    # 1. Schema
    sql_bytes = s3_download(s3, "bootstrap/create_tables_v2.sql")
    apply_schema(conn, sql_bytes.decode("utf-8"))

    # 2. Excel seed
    excel_bytes = s3_download(s3, "bootstrap/cleaned_ticket_data_enhanced.xlsx")
    seed_excel(conn, excel_bytes)

    # 3. JSONL seed
    jsonl_bytes = s3_download(s3, "bootstrap/resolution.jsonl")
    seed_jsonl(conn, jsonl_bytes)

    # 4. Verify
    verify(conn)

    conn.close()
    log.info("=== Bootstrap complete ===")


if __name__ == "__main__":
    main()
