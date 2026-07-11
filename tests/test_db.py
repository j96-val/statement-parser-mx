"""
Unit tests for db.py (SQLite persistence layer).

Uses an in-memory DB (":memory:") - no file I/O, no fixtures needed.

Run either way:
    pytest tests/
    python3 tests/test_db.py     # no pytest needed
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


def make_row(bank="Banamex", file="statement", date="2026-01-05",
             desc="OXXO TIENDA 123", category="Convenience Stores (OXXO/misc.)",
             amount=50.0, type_="charge", review=""):
    return {
        "Bank": bank, "File": file, "Date": date, "Description": desc,
        "Category": category, "Amount": amount, "Type": type_, "Review": review,
    }


def fresh_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


# --- dedup: genuine same-day same-amount duplicates must both survive -------

def test_dedup_keeps_genuine_duplicates():
    conn = fresh_conn()
    rows = [make_row(), make_row()]  # identical on purpose
    n = db.insert_transactions(conn, rows)
    assert n == 2
    count = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
    assert count == 2


def test_reinserting_same_batch_is_noop():
    conn = fresh_conn()
    rows = [make_row(), make_row()]
    db.insert_transactions(conn, rows)
    n_second = db.insert_transactions(conn, rows)  # same file, same rows again
    assert n_second == 0
    count = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
    assert count == 2


# --- category_overrides: override wins, non-matching rows keep categorize() -

def test_category_override_applied():
    conn = fresh_conn()
    conn.execute(
        "INSERT INTO category_overrides (merchant_pattern, category, created_at) "
        "VALUES ('%OXXO%', 'Groceries/Supermarkets', '2026-01-01')"
    )
    conn.commit()

    rows = [
        make_row(desc="OXXO TIENDA 123", category="Convenience Stores (OXXO/misc.)"),
        make_row(desc="STARBUCKS COYOACAN", category="Restaurants"),
    ]
    db.insert_transactions(conn, rows)

    cats = {r["description"]: r["category"]
            for r in conn.execute("SELECT description, category FROM transactions")}
    assert cats["OXXO TIENDA 123"] == "Groceries/Supermarkets"  # overridden
    assert cats["STARBUCKS COYOACAN"] == "Restaurants"           # untouched


# --- Phase 4.1: schema migration adds new columns to an existing DB ---------

def test_migrate_adds_new_columns_idempotently():
    conn = db.connect(":memory:")
    # simulate a pre-Phase-4 DB: base schema only, no migrate() call yet
    conn.executescript(db.SCHEMA)
    conn.commit()
    before = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
    assert "charge_date" not in before

    db.migrate(conn)
    after = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
    for col in db.NEW_COLUMNS:
        assert col in after

    db.migrate(conn)  # second call must not raise (duplicate ALTER COLUMN)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
