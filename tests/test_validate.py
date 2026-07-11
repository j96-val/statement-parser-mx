"""
Unit tests for validate.py's row-level checks and reconciliation math.

Synthetic row lists only - no PDFs. The per-bank printed-total regexes
(extract_printed_totals) are exercised against real statements manually via
build_report.py (see CLAUDE.local.md's totals-reconciliation note); that part
needs real PDFs to mean anything, so it's out of scope for a unit test.

Run either way:
    pytest tests/
    python3 tests/test_validate.py     # no pytest needed
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validate


def row(amount, desc="MERCHANT", review="", is_installment=False):
    return {"Amount": amount, "Description": desc, "Review": review, "is_installment": is_installment}


# --- check_empty --------------------------------------------------------

def test_check_empty_flags_known_bank_with_no_rows():
    assert validate.check_empty("nu", []) is not None

def test_check_empty_passes_with_rows():
    assert validate.check_empty("nu", [row(10.0)]) is None

def test_check_empty_ignores_unknown_bank():
    assert validate.check_empty("unknown", []) is None


# --- check_outliers ------------------------------------------------------

def test_check_outliers_flags_extreme_amount():
    rows = [row(50.0), row(55.0), row(45.0), row(5000.0)]  # one ~100x the median
    warnings = validate.check_outliers(rows)
    assert len(warnings) == 1
    assert "5000.00" in warnings[0]

def test_check_outliers_silent_on_uniform_file():
    rows = [row(50.0), row(55.0), row(45.0), row(60.0)]
    assert validate.check_outliers(rows) == []


# --- check_review_ratio ---------------------------------------------------

def test_check_review_ratio_fires_above_threshold():
    rows = [row(10.0, review="YES")] * 3 + [row(10.0)]  # 75% flagged
    assert validate.check_review_ratio(rows) is not None

def test_check_review_ratio_silent_below_threshold():
    rows = [row(10.0, review="YES")] + [row(10.0)] * 9  # 10% flagged
    assert validate.check_review_ratio(rows) is None


# --- reconcile -------------------------------------------------------------

def test_reconcile_passes_within_tolerance():
    rows = [row(100.0), row(-50.0)]
    assert validate.reconcile(rows, {"charges": 100.30, "payments": -50.0}) == []

def test_reconcile_hard_fails_beyond_tolerance():
    rows = [row(100.0), row(-50.0)]
    messages = validate.reconcile(rows, {"charges": 150.0, "payments": -50.0})
    assert len(messages) == 1 and "charges mismatch" in messages[0]

def test_reconcile_skips_none_side():
    rows = [row(100.0), row(-50.0)]
    assert validate.reconcile(rows, {"charges": None, "payments": None}) == []

def test_reconcile_excludes_installment_charges():
    # Invex's printed "Total cargos" is regular-only; installment rows must
    # not be counted against it (regression: was double-counting installments).
    rows = [row(89.59), row(1081.67, is_installment=True), row(-2973.0)]
    assert validate.reconcile(rows, {"charges": 89.59, "payments": -2973.0}) == []


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
