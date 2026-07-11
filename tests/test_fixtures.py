"""
End-to-end tests: generate a synthetic PDF fixture (see tests/fixtures.py),
parse it with the real parser, and reconcile against validate.py - the same
totals-reconciliation check ROADMAP.md calls the most valuable in production,
now automated against fake data.

Nu, Invex, and Banorte are covered - all parse via pdfplumber text extraction
only. Liverpool is OCR-only and Banamex always runs an OCR fallback pass
(needs tesseract + poppler); their pure text->rows logic is already covered
by tests/test_parsers.py. See tests/fixtures.py for the full rationale.

Needs reportlab (dev-only, see requirements-dev.txt); the __main__ runner
skips cleanly if it's not installed, so the zero-dep local workflow
(`python3 tests/test_X.py`) stays zero-dep. CI installs it, so these actually
run there.

Run either way:
    pytest tests/
    python3 tests/test_fixtures.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import reportlab  # noqa: F401
    HAVE_REPORTLAB = True
except ImportError:
    HAVE_REPORTLAB = False

from parsers.nu import parse_nu
from parsers.invex import parse_invex
from parsers.banorte import parse_banorte
import validate
from fixtures import FIXTURES, make_pdf


def _build(bank: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    make_pdf(bank, tmp.name)
    return tmp.name


def test_nu_fixture_parses_and_reconciles():
    path = _build("nu")
    rows = parse_nu(path)
    fx = FIXTURES["nu"]
    assert len(rows) == fx["expected_rows"]
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    assert charges == fx["expected_charges"]
    assert payments == fx["expected_payments"]

    printed = validate.extract_printed_totals("nu", path)
    assert printed == {"charges": fx["expected_charges"], "payments": fx["expected_payments"]}

    val_rows = [{"Amount": r["amount"], "Description": r["description"], "Review": ""} for r in rows]
    ok, messages = validate.validate_file("nu", val_rows, path)
    assert ok, messages


def test_invex_fixture_parses_and_reconciles():
    path = _build("invex")
    rows = parse_invex(path)
    fx = FIXTURES["invex"]
    assert len(rows) == fx["expected_rows"]

    installment_rows = [r for r in rows if r["is_installment"]]
    assert len(installment_rows) == 1
    assert installment_rows[0]["amount"] == 1000.00
    # Phase 4.1: installment metadata now lives in its own columns, and the
    # description no longer carries the "(installment N de M)" suffix.
    inst = installment_rows[0]
    assert inst["description"] == "LAPTOP DELL MSI"
    assert inst["installment_num"] == 2 and inst["installment_total"] == 12
    assert inst["original_amount"] == 12000.00
    assert inst["remaining_balance"] == 10000.00
    assert inst["rate"] == 1.5
    assert inst["statement_date"] == "25-may-2026"

    regular_rows = [r for r in rows if not r["is_installment"]]
    assert all(r.get("charge_date") for r in regular_rows)
    assert all(r.get("statement_date") == "25-may-2026" for r in regular_rows)

    val_rows = [
        {"Amount": r["amount"], "Description": r["description"], "Review": "", "is_installment": r["is_installment"]}
        for r in rows
    ]
    charges = sum(r["Amount"] for r in val_rows if r["Amount"] > 0 and not r["is_installment"])
    payments = sum(r["Amount"] for r in val_rows if r["Amount"] < 0)
    assert charges == fx["expected_charges"]
    assert payments == fx["expected_payments"]

    printed = validate.extract_printed_totals("invex", path)
    assert printed == {"charges": fx["expected_charges"], "payments": fx["expected_payments"]}

    ok, messages = validate.validate_file("invex", val_rows, path)
    assert ok, messages


def test_banorte_fixture_parses_and_reconciles():
    path = _build("banorte")
    rows = parse_banorte(path)
    fx = FIXTURES["banorte"]
    assert len(rows) == fx["expected_rows"]
    assert all(r.get("charge_date") for r in rows)  # Phase 4.1: plumbed through
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    assert charges == fx["expected_charges"]
    assert payments == fx["expected_payments"]

    printed = validate.extract_printed_totals("banorte", path)
    assert printed == {"charges": fx["expected_charges"], "payments": fx["expected_payments"]}

    val_rows = [{"Amount": r["amount"], "Description": r["description"], "Review": ""} for r in rows]
    ok, messages = validate.validate_file("banorte", val_rows, path)
    assert ok, messages


if __name__ == "__main__":
    if not HAVE_REPORTLAB:
        print("skipped (reportlab not installed)")
        sys.exit(0)
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
