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
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL,
    card TEXT,
    period_start TEXT,
    period_end TEXT,
    cutoff_date TEXT,
    prev_balance REAL,
    closing_balance REAL,
    min_payment REAL,
    no_interest_payment REAL,
    credit_limit REAL,
    source_file TEXT,
    statement_key TEXT UNIQUE,
    imported_at TEXT
);
"""

# Phase 4.1/4.2 columns, added to `transactions` after the base CREATE above.
# Kept as an ALTER-based migration (not folded into SCHEMA) so existing users'
# statement_history.db gets upgraded in place instead of silently missing
# these columns forever.
NEW_COLUMNS = {
    "charge_date": "TEXT",
    "card": "TEXT",
    "statement_date": "TEXT",
    "installment_num": "INTEGER",
    "installment_total": "INTEGER",
    "original_amount": "REAL",
    "remaining_balance": "REAL",
    "rate": "REAL",
    "day_of_week": "TEXT",
    "is_weekend": "INTEGER",
    "merchant_norm": "TEXT",
}


def connect(path=DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotent: adds any column in NEW_COLUMNS missing from `transactions`."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
    for col, sql_type in NEW_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {sql_type}")
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)


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


def statement_identity(card: str | None, credit_limit: float | None) -> str | None:
    # Card last-4 is the natural identifier for telling two accounts at the
    # same bank apart. Banamex never exposes it in text (the digits render
    # as an image), so two different Banamex cards can otherwise collide on
    # bank+cutoff_date alone (seen with two real statements: $18,500 vs
    # $38,500 limits, same cutoff date). credit_limit is a stable per-card
    # fallback in that case. If neither is available (Liverpool, Santander -
    # no printed limit), identity is None and statements from a second
    # account at that bank on the same cutoff date would collide.
    # ponytail: no known case of that yet; revisit if it happens.
    if card is not None:
        return f"card:{card}"
    if credit_limit is not None:
        return f"limit:{credit_limit}"
    return None


def make_statement_key(bank: str, identity: str | None, cutoff_date: str | None, period_end: str | None) -> str:
    # cutoff_date is preferred; period_end is the fallback for a bank/file
    # where cutoff extraction failed but the period still parsed.
    raw = f"{bank}|{identity}|{cutoff_date or period_end}"
    return hashlib.sha1(raw.encode()).hexdigest()


def apply_override(conn: sqlite3.Connection, description: str, fallback: str) -> str:
    row = conn.execute(
        "SELECT category FROM category_overrides WHERE ? LIKE merchant_pattern LIMIT 1",
        (description,),
    ).fetchone()
    return row["category"] if row else fallback


def set_override(conn: sqlite3.Connection, description: str, category: str) -> None:
    """Persists a category correction (viewer click-to-correct) and retro-fixes
    every already-inserted transaction with the same description, so the
    change is visible immediately, not just on the next import.
    # ponytail: exact-description override; add wildcard/merchant-norm
    # patterns if per-merchant (not per-description) grouping is wanted."""
    conn.execute(
        "INSERT INTO category_overrides (merchant_pattern, category, created_at) VALUES (?, ?, ?)",
        (description, category, datetime.now().isoformat()),
    )
    conn.execute(
        "UPDATE transactions SET category = ? WHERE description = ?",
        (category, description),
    )
    conn.commit()


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
                review, source_file, dedup_key, imported_at,
                charge_date, card, statement_date, installment_num,
                installment_total, original_amount, remaining_balance, rate,
                day_of_week, is_weekend, merchant_norm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["Date"], r["Date"][:7], r["Bank"], r["Description"], category,
             r["Amount"], r["Type"], r["Review"], r["File"], key, now,
             r.get("ChargeDate"), r.get("Card"), r.get("StatementDate"),
             r.get("InstallmentNum"), r.get("InstallmentTotal"),
             r.get("OriginalAmount"), r.get("RemainingBalance"), r.get("Rate"),
             r.get("DayOfWeek"), r.get("IsWeekend"), r.get("MerchantNorm")),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def insert_statements(conn: sqlite3.Connection, rows: list[dict]) -> tuple[int, list[dict]]:
    """Returns (inserted_count, duplicate_rows). A duplicate is a statement
    whose (bank, card, cutoff) key already exists - INSERT OR IGNORE left it
    untouched, meaning this exact statement was already imported."""
    inserted = 0
    duplicates = []
    now = datetime.now().isoformat()
    for r in rows:
        identity = statement_identity(r.get("Card"), r.get("CreditLimit"))
        key = make_statement_key(r["Bank"], identity, r.get("CutoffDate"), r.get("PeriodEnd"))
        cur = conn.execute(
            """INSERT OR IGNORE INTO statements
               (bank, card, period_start, period_end, cutoff_date, prev_balance,
                closing_balance, min_payment, no_interest_payment, credit_limit,
                source_file, statement_key, imported_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["Bank"], r.get("Card"), r.get("PeriodStart"), r.get("PeriodEnd"),
             r.get("CutoffDate"), r.get("PrevBalance"), r.get("ClosingBalance"),
             r.get("MinPayment"), r.get("NoInterestPayment"), r.get("CreditLimit"),
             r.get("File"), key, now),
        )
        if cur.rowcount:
            inserted += 1
        else:
            duplicates.append(r)
    conn.commit()
    return inserted, duplicates


def latest_statement(
    conn: sqlite3.Connection, bank: str, card: str | None, credit_limit: float | None, before_cutoff: str | None
) -> sqlite3.Row | None:
    """Most recent statement for the same (bank, identity) strictly before
    before_cutoff - the one validate.check_continuity compares against.
    Mirrors statement_identity()'s card-then-credit_limit fallback."""
    if card is not None:
        query = "SELECT * FROM statements WHERE bank = ? AND card = ?"
        params = [bank, card]
    else:
        query = "SELECT * FROM statements WHERE bank = ? AND card IS NULL AND credit_limit IS ?"
        params = [bank, credit_limit]
    if before_cutoff:
        query += " AND cutoff_date < ?"
        params.append(before_cutoff)
    query += " ORDER BY cutoff_date DESC LIMIT 1"
    return conn.execute(query, params).fetchone()


def fetch_statements(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT bank AS Bank, card AS Card, period_start AS PeriodStart,
                  period_end AS PeriodEnd, cutoff_date AS CutoffDate,
                  prev_balance AS PrevBalance, closing_balance AS ClosingBalance,
                  min_payment AS MinPayment, no_interest_payment AS NoInterestPayment,
                  credit_limit AS CreditLimit, source_file AS File
           FROM statements ORDER BY cutoff_date, id""",
        conn,
    )


def fetch_dataframe(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT bank AS Bank, source_file AS File, date AS Date,
                  description AS Description, category AS Category,
                  amount AS Amount, type AS Type, review AS Review,
                  month AS Month, charge_date AS ChargeDate, card AS Card,
                  statement_date AS StatementDate,
                  installment_num AS InstallmentNum,
                  installment_total AS InstallmentTotal,
                  original_amount AS OriginalAmount,
                  remaining_balance AS RemainingBalance, rate AS Rate,
                  day_of_week AS DayOfWeek, is_weekend AS IsWeekend,
                  merchant_norm AS MerchantNorm
           FROM transactions ORDER BY date, id""",
        conn,
    )
