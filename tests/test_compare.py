"""
Unit tests for compare.py's monthly_totals() query logic.

Uses an in-memory DB (":memory:"), seeded via db.insert_transactions - no
fixtures, no real statement files.

Run either way:
    pytest tests/
    python3 tests/test_compare.py     # no pytest needed
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from compare import monthly_totals


def row(bank, file, date, desc, category, amount, type_="charge"):
    return {
        "Bank": bank, "File": file, "Date": date, "Description": desc,
        "Category": category, "Amount": amount, "Type": type_, "Review": "",
    }


def seeded_conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    rows = [
        row("Banamex", "jan", "2026-01-05", "STARBUCKS", "Restaurants", 100.0),
        row("Banamex", "jan", "2026-01-10", "OXXO TIENDA", "Convenience Stores", 50.0),
        row("Banamex", "feb", "2026-02-05", "STARBUCKS", "Restaurants", 150.0),
        row("Banamex", "feb", "2026-02-10", "STARBUCKS", "Restaurants", 50.0),
        row("Banamex", "feb", "2026-02-12", "NETFLIX", "Subscriptions/Software", 199.0),
        row("Banamex", "feb", "2026-02-15", "SU PAGO", "Payments", -500.0, type_="payment"),
    ]
    db.insert_transactions(conn, rows)
    return conn


def test_monthly_totals_sums_per_category():
    conn = seeded_conn()
    totals = monthly_totals(conn, category="Restaurants")
    assert totals == [("2026-01", 100.0), ("2026-02", 200.0)]


def test_category_filter_is_case_insensitive_substring():
    conn = seeded_conn()
    assert monthly_totals(conn, category="restau") == [("2026-01", 100.0), ("2026-02", 200.0)]
    # doesn't leak into unrelated categories
    subs = monthly_totals(conn, category="subscri")
    assert subs == [("2026-02", 199.0)]


def test_no_category_sums_everything_of_that_type():
    conn = seeded_conn()
    totals = monthly_totals(conn, category=None, type_="charge")
    assert totals == [("2026-01", 150.0), ("2026-02", 399.0)]


def test_type_filter_selects_payments():
    conn = seeded_conn()
    assert monthly_totals(conn, category=None, type_="payment") == [("2026-02", -500.0)]


def test_months_window_trims_to_last_n():
    conn = seeded_conn()
    totals = monthly_totals(conn, category="Restaurants", months=1)
    assert totals == [("2026-02", 200.0)]


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
