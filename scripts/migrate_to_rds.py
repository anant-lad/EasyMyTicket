"""
One-time migration script: create v2 schema on RDS + import combined dataset.

Usage:
    DB_HOST=<rds-endpoint> DB_PASSWORD=<password> python scripts/migrate_to_rds.py

The script is idempotent — safe to re-run. Uses ON CONFLICT DO NOTHING.
"""

import os
import sys
import time
import logging
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "port":     int(os.environ.get("DB_PORT", 5432)),
    "dbname":   os.environ.get("DB_NAME", "tickets_db"),
    "user":     os.environ.get("DB_USER", "ticketing_admin"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "connect_timeout": 10,
    "sslmode": "require",   # RDS enforces SSL
}

REPO_ROOT   = Path(__file__).parent.parent
SCHEMA_FILE = REPO_ROOT / "src" / "database" / "create_tables_v2.sql"
ENHANCED_DS = REPO_ROOT.parent.parent / "context" / "cleaned_ticket_data_enhanced.xlsx"
LEGACY_DS   = REPO_ROOT / "dataset" / "ticket_data_updated.csv"

BATCH_SIZE = 500


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_connection():
    for attempt in range(5):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as e:
            log.warning("DB connect attempt %d failed: %s", attempt + 1, e)
            time.sleep(3)
    log.error("Could not connect to database after 5 attempts")
    sys.exit(1)


def run_schema(conn):
    log.info("Applying v2 schema from %s", SCHEMA_FILE)
    sql = SCHEMA_FILE.read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Schema applied successfully")


def normalize_ts(val):
    if pd.isna(val) or val == "" or val is None:
        return None
    try:
        return pd.to_datetime(val).to_pydatetime()
    except Exception:
        return None


def normalize_str(val, max_len=100):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


def import_enhanced_dataset(conn):
    log.info("Loading enhanced dataset from %s", ENHANCED_DS)
    if not ENHANCED_DS.exists():
        log.warning("Enhanced dataset not found at %s — skipping", ENHANCED_DS)
        return

    df = pd.read_excel(ENHANCED_DS, dtype=str)
    df.columns = [c.upper() for c in df.columns]
    log.info("Enhanced dataset: %d rows, columns: %s", len(df), df.columns.tolist())

    # Column mapping: DataFrame col → DB col
    col_map = {
        "COMPANYID":             "companyid",
        "COMPANYLOCATIONID":     "companylocationid",
        "COMPLETEDBYRESOURCEID": "completedbyresourceid",
        "COMPLETEDDATE":         "completeddate",
        "CONTACTID":             "contactid",
        "CREATEDATE":            "createdate",
        "CREATEDBYCONTACTID":    "createdbycontactid",
        "DESCRIPTION":           "description",
        "DUEDATETIME":           "duedatetime",
        "ID":                    "external_id",
        "ISSUETYPE":             "issuetype",
        "PRIORITY":              "priority",
        "QUEUEID":               "queueid",
        "RESOLUTION":            "resolution",
        "RESOLVEDDATETIME":      "resolveddatetime",
        "RESOLVEDDUEDATETIME":   "resolvedduedatetime",
        "STATUS":                "status",
        "SUBISSUETYPE":          "subissuetype",
        "TICKETCATEGORY":        "ticketcategory",
        "TICKETNUMBER":          "ticketnumber",
        "TICKETTYPE":            "tickettype",
        "TITLE":                 "title",
    }

    ts_cols = {"completeddate", "createdate", "duedatetime", "resolveddatetime", "resolvedduedatetime"}
    db_cols = list(col_map.values()) + ["source_dataset"]

    inserted = skipped = 0
    rows_batch = []

    for _, row in df.iterrows():
        ticketnumber = normalize_str(row.get("TICKETNUMBER", ""), 100)
        title = normalize_str(row.get("TITLE", ""), 1000)
        if not ticketnumber or not title:
            skipped += 1
            continue

        record = []
        for src_col, dst_col in col_map.items():
            val = row.get(src_col)
            if dst_col in ts_cols:
                record.append(normalize_ts(val))
            else:
                record.append(normalize_str(val, 500 if dst_col in ("description", "resolution") else 100))
        record.append("enhanced")
        rows_batch.append(record)

        if len(rows_batch) >= BATCH_SIZE:
            _bulk_insert_historical(conn, db_cols, rows_batch)
            inserted += len(rows_batch)
            rows_batch = []
            log.info("  ...inserted %d rows", inserted)

    if rows_batch:
        _bulk_insert_historical(conn, db_cols, rows_batch)
        inserted += len(rows_batch)

    log.info("Enhanced dataset: %d inserted, %d skipped (missing ticketnumber/title)", inserted, skipped)


def import_legacy_dataset(conn):
    log.info("Loading legacy dataset from %s", LEGACY_DS)
    if not LEGACY_DS.exists():
        log.warning("Legacy dataset not found at %s — skipping", LEGACY_DS)
        return

    # This file is actually Excel format despite .csv extension
    try:
        df = pd.read_excel(LEGACY_DS, dtype=str)
    except Exception:
        df = pd.read_csv(LEGACY_DS, dtype=str)

    df.columns = [c.upper() for c in df.columns]
    log.info("Legacy dataset: %d rows", len(df))

    col_map = {
        "COMPANYID":    "companyid",
        "COMPLETEDDATE":"completeddate",
        "CREATEDATE":   "createdate",
        "DESCRIPTION":  "description",
        "DUEDATETIME":  "duedatetime",
        "ISSUETYPE":    "issuetype",
        "PRIORITY":     "priority",
        "QUEUEID":      "queueid",
        "RESOLUTION":   "resolution",
        "RESOLVEDDATETIME": "resolveddatetime",
        "STATUS":       "status",
        "SUBISSUETYPE": "subissuetype",
        "TICKETCATEGORY":"ticketcategory",
        "TICKETNUMBER": "ticketnumber",
        "TICKETTYPE":   "tickettype",
        "TITLE":        "title",
    }

    ts_cols = {"completeddate", "createdate", "duedatetime", "resolveddatetime"}
    db_cols = list(col_map.values()) + ["source_dataset"]

    inserted = skipped = 0
    rows_batch = []

    for _, row in df.iterrows():
        ticketnumber = normalize_str(row.get("TICKETNUMBER", ""), 100)
        title = normalize_str(row.get("TITLE", ""), 1000)
        if not ticketnumber or not title:
            skipped += 1
            continue

        record = []
        for src_col, dst_col in col_map.items():
            val = row.get(src_col)
            if dst_col in ts_cols:
                record.append(normalize_ts(val))
            else:
                record.append(normalize_str(val, 500 if dst_col in ("description", "resolution") else 100))
        record.append("legacy")
        rows_batch.append(record)

        if len(rows_batch) >= BATCH_SIZE:
            _bulk_insert_historical(conn, db_cols, rows_batch)
            inserted += len(rows_batch)
            rows_batch = []
            log.info("  ...inserted %d rows", inserted)

    if rows_batch:
        _bulk_insert_historical(conn, db_cols, rows_batch)
        inserted += len(rows_batch)

    log.info("Legacy dataset: %d inserted, %d skipped", inserted, skipped)


def _bulk_insert_historical(conn, db_cols, rows):
    placeholders = ",".join(["%s"] * len(db_cols))
    col_list = ",".join(db_cols)
    sql = f"""
        INSERT INTO historical_tickets ({col_list})
        VALUES %s
        ON CONFLICT (ticketnumber) DO NOTHING
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()


def populate_closed_tickets(conn):
    """
    Populate closed_tickets (used by semantic search) from historical_tickets.
    Only copies records that have both title and resolution (good for similarity).
    """
    log.info("Populating closed_tickets from historical_tickets...")
    sql = """
        INSERT INTO closed_tickets (
            companyid, createdate, description, duedatetime,
            issuetype, priority, queueid, resolution,
            resolveddatetime, status, subissuetype,
            ticketcategory, ticketnumber, tickettype, title
        )
        SELECT
            companyid, createdate, description, duedatetime,
            issuetype, priority, queueid, resolution,
            resolveddatetime, status, subissuetype,
            ticketcategory, ticketnumber, tickettype, title
        FROM historical_tickets
        WHERE resolution IS NOT NULL
          AND resolution != ''
          AND title IS NOT NULL
        ON CONFLICT (ticketnumber) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        count = cur.rowcount
    conn.commit()
    log.info("Copied %d records to closed_tickets", count)


def verify(conn):
    tables = ["new_tickets", "historical_tickets", "closed_tickets",
              "technician_data", "user_data", "ticket_assignments",
              "chat_sessions", "chat_messages", "agent_tasks"]
    log.info("\n=== Verification ===")
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            log.info("  %-25s %d rows", table, count)


def main():
    log.info("Starting RDS migration...")
    conn = get_connection()
    try:
        run_schema(conn)
        import_enhanced_dataset(conn)
        import_legacy_dataset(conn)
        populate_closed_tickets(conn)
        verify(conn)
        log.info("\n✅ Migration complete!")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
