"""
scripts/seed_database.py
========================
Seeds the RDS PostgreSQL database with:

  1. historical_tickets — 55K real MSP tickets from the cleaned Excel file
                          (used for semantic similarity search at inference time)
  2. closed_tickets     — same data mirrored into the legacy semantic search table
                          (db_connection.find_similar_tickets searches this table)

Run once after terraform apply + schema creation:

    python scripts/seed_database.py \
        [--excel  /path/to/cleaned_ticket_data_enhanced.xlsx] \
        [--jsonl  /path/to/resolution.jsonl] \
        [--batch  500] \
        [--dry-run]

The script is idempotent — tickets already present (by ticketnumber) are skipped.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed")

# Resolve project root so imports work regardless of cwd
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Must come after sys.path / dotenv setup
import pandas as pd
from src.database.db_connection import DatabaseConnection
from src.graph.auto_resolve import ISSUETYPE_CATEGORY  # noqa: wrong module — inline below

# Inline mapping (same as dataset builder)
_ISSUETYPE_CATEGORY = {
    "4": "hardware", "5": "software", "6": "network", "7": "general_inquiry",
    "8": "software", "9": "account_access", "10": "email_collaboration",
    "11": "cloud_infrastructure", "12": "hardware", "13": "backup_recovery",
    "14": "security", "15": "email_collaboration", "16": "hardware",
    "17": "general_inquiry", "18": "hardware", "19": "software",
    "20": "security", "21": "billing", "22": "security",
    "23": "account_access", "25": "security", "26": "general_inquiry",
}

_PRIORITY_MAP = {
    "1": "critical", "2": "high", "3": "medium", "4": "low", "5": "low",
    "critical": "critical", "high": "high", "medium": "medium", "low": "low",
}


def _to_category(issuetype_raw) -> str:
    try:
        key = str(int(float(issuetype_raw))) if issuetype_raw is not None else ""
    except (ValueError, TypeError):
        key = str(issuetype_raw or "").strip()
    return _ISSUETYPE_CATEGORY.get(key, "general_inquiry")


def _to_priority(raw) -> str:
    if raw is None:
        return "medium"
    return _PRIORITY_MAP.get(str(raw).strip().lower(), "medium")


# ─────────────────────────────────────────────────────────────────────────────
#  Seed from Excel (primary MSP data)
# ─────────────────────────────────────────────────────────────────────────────

INSERT_HISTORICAL = """
INSERT INTO historical_tickets
    (ticketnumber, title, description, resolution, issuetype, priority,
     status, createdate, source_dataset)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""

INSERT_CLOSED = """
INSERT INTO closed_tickets
    (ticketnumber, title, description, resolution, issuetype, priority, status, createdate)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""


def seed_from_excel(db: DatabaseConnection, excel_path: Path, batch_size: int, dry_run: bool):
    log.info("Reading %s …", excel_path)
    df = pd.read_excel(excel_path)

    # Filter to 'real' rows if DATA_SOURCE column exists
    if "DATA_SOURCE" in df.columns:
        df = df[df["DATA_SOURCE"].astype(str).str.lower() == "real"]

    log.info("Loaded %d rows from Excel", len(df))
    inserted = skipped = 0

    rows_h, rows_c = [], []

    for _, row in df.iterrows():
        title      = str(row.get("TITLE", "") or "")[:500].strip()
        desc       = str(row.get("DESCRIPTION", "") or "")[:10000].strip()
        resolution = str(row.get("RESOLUTION", "") or "")[:10000].strip()

        if len(title) + len(desc) < 20:
            skipped += 1
            continue

        ticket_num  = str(row.get("TICKETNUMBER", "") or "").strip() or f"HST-{inserted}"
        issuetype   = str(row.get("ISSUETYPE", "") or "").strip()
        priority    = _to_priority(row.get("PRIORITY"))
        status      = str(row.get("STATUS", "Closed") or "Closed")[:50]
        createdate  = row.get("CREATEDATE")

        rows_h.append((ticket_num, title, desc, resolution or None,
                       issuetype or None, priority, status, createdate, "enhanced"))
        rows_c.append((ticket_num, title, desc, resolution or None,
                       issuetype or None, priority, status, createdate))

        if len(rows_h) >= batch_size:
            if not dry_run:
                db.execute_many(INSERT_HISTORICAL, rows_h)
                db.execute_many(INSERT_CLOSED, rows_c)
            inserted += len(rows_h)
            log.info("  … %d rows inserted", inserted)
            rows_h.clear()
            rows_c.clear()

    # Flush remainder
    if rows_h:
        if not dry_run:
            db.execute_many(INSERT_HISTORICAL, rows_h)
            db.execute_many(INSERT_CLOSED, rows_c)
        inserted += len(rows_h)

    log.info("Excel seed complete: %d inserted, %d skipped", inserted, skipped)
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
#  Seed from resolution.jsonl (processed dataset — already deduplicated)
# ─────────────────────────────────────────────────────────────────────────────

INSERT_HISTORICAL_JSONL = """
INSERT INTO historical_tickets
    (ticketnumber, title, description, resolution, priority, source_dataset)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""

INSERT_CLOSED_JSONL = """
INSERT INTO closed_tickets
    (ticketnumber, title, description, resolution, priority)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (ticketnumber) DO NOTHING
"""


def seed_from_jsonl(db: DatabaseConnection, jsonl_path: Path, batch_size: int, dry_run: bool):
    log.info("Reading %s …", jsonl_path)
    rows_h, rows_c = [], []
    inserted = 0

    with open(jsonl_path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            # Only take MSP real tickets — skip code/instruction data
            if obj.get("source") != "user_msp_real":
                continue

            problem    = obj.get("problem", "")
            resolution = obj.get("resolution", "")
            if not problem or not resolution:
                continue

            # Split problem into title (first line) + description (rest)
            parts = problem.split("\n", 1)
            title = parts[0].strip()[:500]
            desc  = parts[1].strip()[:10000] if len(parts) > 1 else ""
            if not title:
                continue

            ticket_num = f"JSONL-{i:07d}"
            priority   = "medium"

            rows_h.append((ticket_num, title, desc, resolution, priority, "resolution_jsonl"))
            rows_c.append((ticket_num, title, desc, resolution, priority))

            if len(rows_h) >= batch_size:
                if not dry_run:
                    db.execute_many(INSERT_HISTORICAL_JSONL, rows_h)
                    db.execute_many(INSERT_CLOSED_JSONL, rows_c)
                inserted += len(rows_h)
                log.info("  … %d rows inserted", inserted)
                rows_h.clear()
                rows_c.clear()

    if rows_h:
        if not dry_run:
            db.execute_many(INSERT_HISTORICAL_JSONL, rows_h)
            db.execute_many(INSERT_CLOSED_JSONL, rows_c)
        inserted += len(rows_h)

    log.info("JSONL seed complete: %d rows inserted", inserted)
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
#  execute_many helper (add to db_connection if missing)
# ─────────────────────────────────────────────────────────────────────────────

def _patch_execute_many(db: DatabaseConnection):
    """Add execute_many to DatabaseConnection if not already present."""
    if hasattr(db, "execute_many"):
        return

    def execute_many(self, query, rows):
        from psycopg2.extras import execute_batch
        pool = self._get_pool() if hasattr(self, "_get_pool") else None

        import psycopg2.pool as _pool_mod
        from src.database.db_connection import _get_pool
        conn = _get_pool().getconn()
        try:
            with conn.cursor() as cur:
                execute_batch(cur, query, rows, page_size=500)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _get_pool().putconn(conn)

    import types
    db.execute_many = types.MethodType(execute_many, db)


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed EasyMyTicket RDS database")
    parser.add_argument(
        "--excel",
        default=str(PROJECT_ROOT / "context" / "cleaned_ticket_data_enhanced.xlsx"),
        help="Path to cleaned MSP Excel file",
    )
    parser.add_argument(
        "--jsonl",
        default=str(PROJECT_ROOT.parent / "dataset_creation" / "processed" / "resolution.jsonl"),
        help="Path to resolution.jsonl from dataset pipeline",
    )
    parser.add_argument("--batch", type=int, default=500, help="Insert batch size")
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write to DB")
    parser.add_argument("--skip-excel", action="store_true")
    parser.add_argument("--skip-jsonl", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        log.info("DRY RUN — no data will be written")

    db = DatabaseConnection()
    _patch_execute_many(db)

    total = 0

    if not args.skip_excel:
        excel_path = Path(args.excel)
        if excel_path.exists():
            total += seed_from_excel(db, excel_path, args.batch, args.dry_run)
        else:
            log.warning("Excel file not found: %s — skipping", excel_path)

    if not args.skip_jsonl:
        jsonl_path = Path(args.jsonl)
        if jsonl_path.exists():
            total += seed_from_jsonl(db, jsonl_path, args.batch, args.dry_run)
        else:
            log.warning("JSONL file not found: %s — skipping", jsonl_path)

    log.info("Seed complete. Total rows inserted: %d", total)


if __name__ == "__main__":
    main()
