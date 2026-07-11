"""
SQLite persistence layer: gives build_report.py memory across runs.

Flow: PDFs -> parsed rows -> insert_transactions() (deduped, category
overrides applied) -> fetch_dataframe() (full history) -> Excel. The DB is
the source of truth; the Excel is a view over it.

No ORM - stdlib sqlite3 only, single user, single file.
"""
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_DB = Path(__file__).parent / "statement_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    month TEXT NOT NULL,
    bank TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL,
    review TEXT DEFAULT '',
    source_file TEXT,
    dedup_key TEXT UNIQUE,
    imported_at TEXT
);
CREATE TABLE IF NOT EXISTS category_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT
);
"""


def connect(path=DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def make_dedup_key(bank, date, description, amount, source_file, occ) -> str:
    # occ = 0-based index of this exact (bank,date,desc,amount) combo within
    # its source file. Needed because genuine same-day same-amount charges
    # are real (see Banamex's dedup fix) - without occ they'd hash identical
    # and INSERT OR IGNORE would silently drop the second one. Re-importing
    # the same file reproduces the same 0,1,2... sequence, so it's still
    # correctly ignored as a duplicate.
    # ponytail: renaming source_file re-imports everything under it (new key).
    raw = f"{bank}|{date}|{description}|{amount}|{source_file}|{occ}"
    return hashlib.sha1(raw.encode()).hexdigest()


def apply_override(conn: sqlite3.Connection, description: str, fallback: str) -> str:
    row = conn.execute(
        "SELECT category FROM category_overrides WHERE ? LIKE merchant_pattern LIMIT 1",
        (description,),
    ).fetchone()
    return row["category"] if row else fallback


def insert_transactions(conn: sqlite3.Connection, rows: list[dict]) -> int:
    seen_occ = {}
    inserted = 0
    now = datetime.now().isoformat()
    for r in rows:
        combo = (r["Bank"], r["Date"], r["Description"], r["Amount"], r["File"])
        occ = seen_occ.get(combo, 0)
        seen_occ[combo] = occ + 1

        key = make_dedup_key(r["Bank"], r["Date"], r["Description"], r["Amount"], r["File"], occ)
        category = apply_override(conn, r["Description"], r["Category"])
        cur = conn.execute(
            """INSERT OR IGNORE INTO transactions
               (date, month, bank, description, category, amount, type,
                review, source_file, dedup_key, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["Date"], r["Date"][:7], r["Bank"], r["Description"], category,
             r["Amount"], r["Type"], r["Review"], r["File"], key, now),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def fetch_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT bank AS Bank, source_file AS File, date AS Date,
                  description AS Description, category AS Category,
                  amount AS Amount, type AS Type, review AS Review,
                  month AS Month
           FROM transactions ORDER BY date, id""",
        conn,
    )
