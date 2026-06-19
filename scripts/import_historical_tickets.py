"""
Import historical tickets from cleaned_ticket_data_enhanced.xlsx into RDS new_tickets table.
Run from EasyMyTicket/ directory:
    python scripts/import_historical_tickets.py

Uses ON CONFLICT DO NOTHING so safe to re-run.
"""
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Load env ──────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import pandas as pd
import psycopg2
import psycopg2.extras

# ── DB connection ─────────────────────────────────────────────────────────────
DB_HOST = os.environ["DB_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASSWORD"]
DB_PORT = int(os.environ.get("DB_PORT", 5432))

EXCEL_PATH = Path(__file__).parent.parent / "context" / "cleaned_ticket_data_enhanced.xlsx"
BATCH_SIZE = 500

# ── Status mapping ────────────────────────────────────────────────────────────
# Numeric status codes → allowed text values in new_tickets CHECK constraint
_STATUS_MAP = {
    1:  "Open",
    5:  "Closed",
    7:  "In Progress",
    8:  "Pending",
    15: "Resolved",
    17: "On Hold",
    19: "Escalated",
    33: "Closed",
    39: "Closed",
    46: "Closed",
    52: "Closed",
    53: "Closed",
}

# ── Priority mapping ──────────────────────────────────────────────────────────
_PRIORITY_MAP = {
    1: "Critical",
    2: "High",
    3: "Medium",
    4: "Low",
    5: "Planning",
}

def _map_status(row) -> str:
    code = row.get("STATUS")
    if pd.notna(row.get("COMPLETEDDATE")):
        return "Closed"
    if pd.notna(row.get("RESOLVEDDATETIME")):
        return "Resolved"
    return _STATUS_MAP.get(int(code) if pd.notna(code) else 0, "Closed")

def _ts(val):
    """Convert pandas Timestamp / NaT to datetime or None."""
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val
    try:
        return pd.Timestamp(val).to_pydatetime()
    except Exception:
        return None

def _str(val):
    """Convert value to str, None if NaN."""
    if pd.isna(val):
        return None
    return str(val).strip() or None

def main():
    log.info("Reading %s", EXCEL_PATH)
    df = pd.read_excel(str(EXCEL_PATH))
    log.info("Loaded %d rows", len(df))

    conn = psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=DB_PASS, port=DB_PORT,
        connect_timeout=10,
    )
    conn.autocommit = False
    cur = conn.cursor()

    inserted = skipped = errors = 0
    batch = []

    for i, row in df.iterrows():
        ticket_number = _str(row.get("TICKETNUMBER"))
        title = _str(row.get("TITLE")) or "(no title)"
        if not ticket_number:
            errors += 1
            continue

        status   = _map_status(row)
        priority_code = row.get("PRIORITY")
        priority = _PRIORITY_MAP.get(int(priority_code) if pd.notna(priority_code) else 0, "Medium")

        batch.append((
            ticket_number,                          # ticketnumber
            title,                                  # title
            _str(row.get("DESCRIPTION")),           # description
            status,                                 # status
            priority,                               # priority
            _str(row.get("ISSUETYPE")),             # issuetype
            _str(row.get("SUBISSUETYPE")),          # subissuetype
            _str(row.get("TICKETCATEGORY")),        # ticketcategory
            _str(row.get("TICKETTYPE")),            # tickettype
            _str(row.get("QUEUEID")),               # queueid
            _str(row.get("RESOLUTION")),            # resolution
            _str(row.get("COMPANYID")),             # companyid
            _str(row.get("CONTACTID")),             # user_id
            _ts(row.get("CREATEDATE")),             # createdate
            _ts(row.get("DUEDATETIME")),            # duedatetime
            _ts(row.get("RESOLVEDDATETIME")),       # resolveddatetime
            _ts(row.get("COMPLETEDDATE")),          # completeddate
        ))

        if len(batch) >= BATCH_SIZE:
            inserted, skipped, errors = _flush(cur, conn, batch, inserted, skipped, errors)
            batch = []
            log.info("Progress: %d inserted, %d skipped, %d errors", inserted, skipped, errors)

    if batch:
        inserted, skipped, errors = _flush(cur, conn, batch, inserted, skipped, errors)

    cur.close()
    conn.close()
    log.info("Done. inserted=%d skipped=%d errors=%d total=%d", inserted, skipped, errors, len(df))

def _flush(cur, conn, batch, inserted, skipped, errors):
    sql = """
        INSERT INTO new_tickets
            (ticketnumber, title, description, status, priority,
             issuetype, subissuetype, ticketcategory, tickettype, queueid,
             resolution, companyid, user_id,
             createdate, duedatetime, resolveddatetime, completeddate)
        VALUES %s
        ON CONFLICT (ticketnumber) DO NOTHING
    """
    try:
        result = psycopg2.extras.execute_values(cur, sql, batch, page_size=BATCH_SIZE)
        conn.commit()
        inserted += len(batch)
    except Exception as e:
        conn.rollback()
        log.error("Batch failed (%d rows): %s", len(batch), e)
        # Insert one-by-one to isolate bad rows
        single_sql = sql.replace("VALUES %s", "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
        for row in batch:
            try:
                cur.execute(single_sql, row)
                conn.commit()
                inserted += 1
            except Exception as e2:
                conn.rollback()
                log.warning("Row skipped (%s): %s", row[0], e2)
                errors += 1
    return inserted, skipped, errors

if __name__ == "__main__":
    main()
