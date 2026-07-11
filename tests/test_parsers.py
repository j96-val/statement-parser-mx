"""
Unit tests for the pure text->rows / categorization logic.

These deliberately avoid PDFs: every function under test takes plain strings,
so no fixtures or OCR are needed. The PDF I/O wrappers (ocr_pdf_pages,
convert_from_path, pdfplumber.open) are not covered here — validate those by
running a real statement through build_report.py and reconciling totals.

Run either way:
    pytest tests/
    python3 tests/test_parsers.py     # no pytest needed
"""
import os
import sys

# make the project root importable whether run via pytest or directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from categorize import categorize
from parsers import banamex, invex, liverpool, nu
import build_report


# --- categorize.py -----------------------------------------------------------

def test_categorize_positive_keyword():
    assert categorize("STARBUCKS COYOACAN", 80.0) == "Restaurants"
    assert categorize("WALMART SUPERCENTER", 500.0) == "Groceries/Supermarkets"
    assert categorize("OXXO TIENDA 123", 50.0).startswith("Convenience Stores")

def test_categorize_first_rule_wins():
    # NETFLIX is only in Subscriptions; must not fall through to Uncategorized
    assert categorize("NETFLIX.COM", 199.0) == "Subscriptions/Software"

def test_categorize_uncategorized():
    assert categorize("SOME UNKNOWN MERCHANT", 10.0) == "Uncategorized"

def test_categorize_negative_splits_payment_vs_refund():
    assert categorize("GRACIAS POR SU PAGO", -1000.0) == "Payments"
    assert categorize("DEVOLUCION MERCANCIA", -50.0) == "Refunds/Adjustments"


# --- Liverpool: B1 (amount truncation) + normalize_line ----------------------

def test_liverpool_money_re_keeps_ungrouped_thousands():
    # regression for B1: OCR often drops the thousands comma
    assert liverpool.MONEY_RE.findall("11131.00") == ["11131.00"]
    assert liverpool.MONEY_RE.findall("1234.56") == ["1234.56"]
    assert liverpool.MONEY_RE.findall("-1,234.56") == ["-1,234.56"]

def test_liverpool_clean_amount():
    assert liverpool.clean_amount("11,131.00") == 11131.0
    assert liverpool.clean_amount("-1 234.56") == -1234.56

def test_liverpool_normalize_line_merges_split_amount():
    # OCR split "-1 1,131.00" -> should become "-11,131.00"
    assert liverpool.normalize_line("-1 1,131.00") == "-11,131.00"
    # decimal misread as comma: "-11,725,00" -> "-11,725.00"
    assert liverpool.normalize_line("-11,725,00") == "-11,725.00"


# --- Banamex: B2 (dedup keeps genuine duplicates, drops OCR re-reads) --------

TWO_IDENTICAL = (
    "05-ene-2026 06-ene-2026 OXXO TIENDA 123 + $50.00\n"
    "05-ene-2026 06-ene-2026 OXXO TIENDA 123 + $50.00\n"
)

def test_banamex_text_pass_keeps_genuine_duplicates():
    rows, _ = banamex.extract_rows_from_text(TWO_IDENTICAL, "primary", set(), dedup=False)
    assert len(rows) == 2  # both real charges survive

def test_banamex_ocr_pass_dedups_against_text():
    seen = set()
    text_rows, _ = banamex.extract_rows_from_text(TWO_IDENTICAL, "primary", seen, dedup=False)
    # OCR re-reads the same two rows -> must add nothing
    ocr_rows, _ = banamex.extract_rows_from_text(TWO_IDENTICAL, "primary", seen, dedup=True)
    assert len(text_rows) == 2 and len(ocr_rows) == 0

def test_banamex_sign_and_type():
    rows, _ = banamex.extract_rows_from_text(
        "10-ene-2026 10-ene-2026 SU PAGO - $1,000.00\n", "primary", set(), dedup=False)
    assert rows[0]["amount"] == -1000.00 and rows[0]["type"] == "payment"


# --- Nu ----------------------------------------------------------------------

def test_nu_date_to_iso():
    assert nu.date_to_iso("05 ENE 2026") == "2026-01-05"

def test_nu_row_re():
    line = "05 ENE 2026 06 ENE 2026 STARBUCKS | RFC: ABC123456 +$80.00"
    m = nu.ROW_RE.match(line)
    assert m and m.group(3) == "STARBUCKS" and m.group(5) == "80.00"


# --- Invex -------------------------------------------------------------------

def test_invex_regular_row():
    m = invex.ROW_REGULAR_RE.match("05-ene-2026 06-ene-2026 UBER TRIP - $120.00")
    assert m and m.group(4) == "-" and m.group(5) == "120.00"

def test_invex_installment_row():
    line = "05-ene-2026 COMPRA MSI TIENDA $1,000.00 $800.00 $200.00 3 de 6 0.00%"
    m = invex.ROW_INSTALLMENT_RE.match(line)
    assert m
    purchase_date, desc, original, balance, due, num, rate = m.groups()
    assert purchase_date == "05-ene-2026" and due == "200.00" and num == "3 de 6"


# --- build_report: date helpers + C3 (detect_bank NU token match) -----------

def test_dashed_date_to_iso():
    assert build_report.dashed_date_to_iso("27-may-2026") == "2026-05-27"

def test_liverpool_date_to_iso():
    assert build_report.liverpool_date_to_iso("05-ENE", 2026) == "2026-01-05"

def test_guess_year_from_filename():
    assert build_report.guess_year_from_filename("liverpool-2025-05.pdf") == 2025
    # no year in name -> current year (not a frozen literal)
    from datetime import datetime
    assert build_report.guess_year_from_filename("liverpool.pdf") == datetime.now().year

def test_detect_bank_nu_token_no_false_positive():
    # filename branch returns before any PDF is opened
    assert build_report.detect_bank("NU-2026-05.pdf") == "nu"
    assert build_report.detect_bank("NU_05.pdf") == "nu"
    # "NUMERO..." must NOT be detected as Nu (file doesn't exist -> unknown)
    assert build_report.detect_bank("NUMERO-05.pdf") == "unknown"


if __name__ == "__main__":
    # zero-dependency runner: execute every test_* function in this module
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
