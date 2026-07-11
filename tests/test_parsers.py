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
from parsers import banamex, invex, liverpool, nu, banorte, santander
import build_report
import enrich
import msi_debt
import statements
import db
import validate


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

def test_categorize_banorte_payment_phrase():
    assert categorize("PAGO BANCA DIGITAL / SUCURSAL, GRACIAS.", -125.0) == "Payments"

def test_categorize_internal_transfer_either_sign():
    # transfers can be positive (leaving cheques) or negative (returning) -
    # must land in Transferencias Internas regardless, not Payments/Refunds
    assert categorize("CARGO APERTURA INV CRECIENTE CHEQUES A INVERSION VISTA", 8530.0) == "Transferencias Internas"
    assert categorize("LIQ A CHE INVERSION CRECIENTE INVERSION VISTA A CHEQUES", -2300.0) == "Transferencias Internas"


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

def test_banamex_charge_date_plumbed():
    # Phase 4.1: charge_date (2nd date column) is captured, not discarded.
    rows, _ = banamex.extract_rows_from_text(
        "05-ene-2026 06-ene-2026 OXXO TIENDA 123 + $50.00\n", "primary", set(), dedup=False)
    assert rows[0]["charge_date"] == "06-ene-2026"


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


# --- Banorte -------------------------------------------------------------

def test_banorte_regular_charge_row():
    line = "17-MAR-2026 10-ABR-2026 MAPFRE L COBRANZA CIUDAD DE M 01/12 +$352.31"
    m = banorte.ROW_REGULAR_RE.match(line)
    assert m and m.group(4) == "+" and m.group(5) == "352.31"

def test_banorte_payment_row_sign_and_type():
    line = "26-MAR-2026 27-MAR-2026 PAGO BANCA DIGITAL / SUCURSAL, GRACIAS. -$125.00"
    m = banorte.ROW_REGULAR_RE.match(line)
    assert m and m.group(4) == "-" and m.group(5) == "125.00"

def test_banorte_installment_breakdown_row_not_matched():
    # the diferido-a-meses breakdown row (single date, ends in a % rate, no
    # trailing +/-$amount) must NOT match the regular-row regex, or its
    # monthly charge would double-count against the already-included
    # regular-section row for the same purchase.
    line = "17-MAR-2026 MAPFRE L COBRANZA CIUDAD DE M $4,227.82 $3,875.51 $352.31 01/12 0.00%"
    assert banorte.ROW_REGULAR_RE.match(line) is None


# --- Santander -------------------------------------------------------------

def test_santander_row_re_with_ocr_noise():
    # OCR inserts stray "|"/"(" around the folio column border
    line = "01-JUN-2026 |0190598 |PAGO TRANSF RAPIDA SPEI TRANSFERENCIA A SALVADOR MONTES PACA 370.00 8,530.00"
    m = santander.ROW_RE.match(line)
    assert m
    date, folio, desc, amount, balance = m.groups()
    assert date == "01-JUN-2026" and folio == "0190598" and amount == "370.00" and balance == "8,530.00"

def test_santander_row_re_paren_variant():
    line = "29-JUN-2026 (0000680 DEPOSITO EN EFECTIVO ATM 9,000.00 9,000.00"
    m = santander.ROW_RE.match(line)
    assert m and m.group(2) == "0000680"

def test_santander_resolve_sign_deposit():
    # balance went up -> deposit/credit -> negative per repo convention
    signed, needs_review = santander.resolve_sign(amount=8900.0, delta=8900.0)
    assert signed == -8900.0 and needs_review is False

def test_santander_resolve_sign_withdrawal():
    # balance went down -> withdrawal/charge -> positive
    signed, needs_review = santander.resolve_sign(amount=370.0, delta=-370.0)
    assert signed == 370.0 and needs_review is False

def test_santander_resolve_sign_flags_mismatch():
    # OCR misread the amount column: delta and amount disagree beyond tolerance
    signed, needs_review = santander.resolve_sign(amount=300.0, delta=-370.0)
    assert needs_review is True

def test_santander_resolve_sign_flags_zero_delta():
    # a real movement row always changes the balance; zero delta means OCR
    # corrupted the balance column
    _, needs_review = santander.resolve_sign(amount=100.0, delta=0.0)
    assert needs_review is True


# --- Phase 4.2: derived columns (enrich.py) ----------------------------------

def test_normalize_merchant_strips_gateway_prefix():
    assert enrich.normalize_merchant("MERPAGO*STARBUCKS COYOACAN") == "STARBUCKS COYOACAN"
    assert enrich.normalize_merchant("PAYPAL *NETFLIX") == "NETFLIX"

def test_normalize_merchant_passthrough_plain_merchant():
    assert enrich.normalize_merchant("WALMART SUPERCENTER") == "WALMART SUPERCENTER"

def test_day_of_week_info_weekend():
    # 2026-07-11 is a Saturday
    name, is_weekend = enrich.day_of_week_info("2026-07-11")
    assert name == "Saturday" and is_weekend is True

def test_day_of_week_info_weekday():
    # 2026-07-06 is a Monday
    name, is_weekend = enrich.day_of_week_info("2026-07-06")
    assert name == "Monday" and is_weekend is False


# --- Phase 4.3: MSI debt projection (msi_debt.py) ----------------------------

def _msi_df():
    import pandas as pd
    # Two snapshots of the same purchase (installment_num rising 2 -> 3) plus
    # one finished MSI (num == total) that must NOT show up as active.
    return pd.DataFrame([
        {"Bank": "Invex Volaris", "Description": "LAPTOP DELL MSI",
         "InstallmentTotal": 6, "InstallmentNum": 2, "OriginalAmount": 12000.0,
         "StatementDate": "2026-04-25", "Amount": 1000.0},
        {"Bank": "Invex Volaris", "Description": "LAPTOP DELL MSI",
         "InstallmentTotal": 6, "InstallmentNum": 3, "OriginalAmount": 12000.0,
         "StatementDate": "2026-05-25", "Amount": 1000.0},
        {"Bank": "Invex Volaris", "Description": "FINISHED ITEM",
         "InstallmentTotal": 3, "InstallmentNum": 3, "OriginalAmount": 900.0,
         "StatementDate": "2026-05-25", "Amount": 300.0},
    ])

def test_active_msi_keeps_latest_snapshot_only():
    active = msi_debt.active_msi(_msi_df())
    assert len(active) == 1  # FINISHED ITEM excluded, only latest LAPTOP snapshot kept
    row = active.iloc[0]
    assert row["InstallmentNum"] == 3 and row["Remaining"] == 3
    assert row["EndMonth"] == "2026-08"

def test_monthly_projection_sums_committed_amount():
    active = msi_debt.active_msi(_msi_df())
    projection = msi_debt.monthly_projection(active)
    assert projection == [("2026-06", 1000.0), ("2026-07", 1000.0), ("2026-08", 1000.0)]


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

def test_detect_bank_banorte_filename():
    assert build_report.detect_bank("BANORTE-2026-04.pdf") == "banorte"

def test_detect_bank_santander_filename():
    assert build_report.detect_bank("SANTANDER-2026-06.pdf") == "santander"

def test_detect_bank_nu_token_no_false_positive():
    # filename branch returns before any PDF is opened
    assert build_report.detect_bank("NU-2026-05.pdf") == "nu"
    assert build_report.detect_bank("NU_05.pdf") == "nu"
    # "NUMERO..." must NOT be detected as Nu (file doesn't exist -> unknown)
    assert build_report.detect_bank("NUMERO-05.pdf") == "unknown"


# --- Phase 5: statement-level cover-page extraction (statements.py) ---------

TEXT_BANK_COVER_PAGE = (
    "Periodo: 27-May-2026 al 26-Jun-2026\n"
    "Fecha de Corte: 26-Jun-2026\n"
    "Límite de crédito: $48,000.00\n"
    "Adeudo del periodo anterior = $2,972.91\n"
    "Pago mínimo:4 $600.00\n"
    "Pago para no generar intereses:2 $3,058.40\n"
    "Saldo deudor total:11 $5,221.72\n"
    "Número de la tarjeta XXXX XXXX XXXX 8442\n"
)

def test_extract_text_bank_reads_all_fields():
    r = statements._extract_text_bank(TEXT_BANK_COVER_PAGE)
    assert r["period_start"] == "2026-05-27" and r["period_end"] == "2026-06-26"
    assert r["cutoff_date"] == "2026-06-26"
    assert r["credit_limit"] == 48000.00
    assert r["prev_balance"] == 2972.91
    assert r["min_payment"] == 600.00
    assert r["no_interest_payment"] == 3058.40
    assert r["closing_balance"] == 5221.72
    assert r["card"] == "8442"

def test_extract_text_bank_no_prev_balance_derives_closing_from_components():
    # Banamex prints no "Adeudo del periodo anterior" nor "Saldo deudor
    # total" line anywhere - closing balance falls back to summing the
    # regular + installment charge subtotals it does print.
    text = (
        "Periodo: 20-may-2026 al 19-jun-2026\n"
        "Fecha de corte: 19-jun-2026\n"
        "Límite de crédito: $ 38,500.00\n"
        "Pago mínimo:4 $590.00\n"
        "Saldo cargos regulares: $ 1,781.47\n"
        "Saldo cargos a meses: $ 0.00\n"
    )
    r = statements._extract_text_bank(text)
    assert r["prev_balance"] is None
    assert r["closing_balance"] == 1781.47

def test_extract_santander_from_ocr_summary():
    text = (
        "PERIODO DEL 01-JUN-2026 AL 30-JUN-2026\n"
        "CORTE AL 30-JUN-2026\n"
        "TOTAL 2,313.59 100.00% 8,455.99 100.00%\n"
    )
    r = statements._extract_santander(text)
    assert r["period_start"] == "2026-06-01" and r["period_end"] == "2026-06-30"
    assert r["cutoff_date"] == "2026-06-30"
    assert r["prev_balance"] == 2313.59 and r["closing_balance"] == 8455.99
    assert r["min_payment"] is None and r["credit_limit"] is None

def test_extract_liverpool_derives_closing_balance_from_clean_components():
    text = (
        "SALDO ANTERIOR 74,334.73\n"
        "PAGOS Y ABONOS -43,038.00\n"
        "COMPRAS Y CARGOS 63,521.17\n"
        "COMISIONES 0.00\n"
    )
    r = statements._extract_liverpool(text, "liverpool-2026-05-25.pdf")
    assert r["cutoff_date"] == "2026-05-25"
    assert r["prev_balance"] == 74334.73
    assert r["closing_balance"] == 94817.90

def test_extract_liverpool_no_cutoff_without_filename_convention():
    r = statements._extract_liverpool("SALDO ANTERIOR 100.00\n", "liverpool-01-05-26.pdf")
    assert r["cutoff_date"] is None  # legacy filename, not the required YYYY-MM-DD form

def test_extract_statement_dispatches_by_bank():
    assert statements.extract_statement("unknown-bank", "x.pdf") is None


# --- Phase 5: statement identity + dedup/continuity (db.py, validate.py) ----

def test_statement_identity_prefers_card():
    assert db.statement_identity("8442", 48000.0) == "card:8442"

def test_statement_identity_falls_back_to_credit_limit():
    # regression: two real Banamex statements ($18,500 vs $38,500 limits)
    # collided on bank+cutoff_date alone because Banamex never exposes the
    # card number as text - credit_limit tells them apart.
    assert db.statement_identity(None, 38500.0) == "limit:38500.0"

def test_statement_identity_none_when_neither_available():
    assert db.statement_identity(None, None) is None

def _stmt_row(**overrides):
    row = {
        "Bank": "Banamex", "Card": None, "PeriodStart": "2026-05-20",
        "PeriodEnd": "2026-06-19", "CutoffDate": "2026-06-19", "PrevBalance": None,
        "ClosingBalance": 1194.50, "MinPayment": 370.0, "NoInterestPayment": 1194.50,
        "CreditLimit": 18500.0, "File": "f",
    }
    row.update(overrides)
    return row

def test_insert_statements_dedups_same_identity_keeps_distinct_accounts():
    conn = db.connect(":memory:")
    db.init_db(conn)
    rows = [
        _stmt_row(),
        _stmt_row(CreditLimit=38500.0, ClosingBalance=1781.47),  # different real account
        _stmt_row(),  # exact duplicate of the first
    ]
    n_new, duplicates = db.insert_statements(conn, rows)
    assert n_new == 2
    assert len(duplicates) == 1

def test_check_continuity_flags_balance_gap():
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.insert_statements(conn, [_stmt_row(
        Card="8442", CreditLimit=48000.0, CutoffDate="2026-05-26",
        PeriodEnd="2026-05-26", ClosingBalance=3000.0,
    )])
    warning = validate.check_continuity(conn, _stmt_row(
        Card="8442", CreditLimit=48000.0, CutoffDate="2026-06-26", PrevBalance=5000.0,
    ))
    assert warning is not None and "gap" in warning

def test_check_continuity_no_warning_when_balances_match():
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.insert_statements(conn, [_stmt_row(
        Card="8442", CreditLimit=48000.0, CutoffDate="2026-05-26",
        PeriodEnd="2026-05-26", ClosingBalance=3000.0,
    )])
    warning = validate.check_continuity(conn, _stmt_row(
        Card="8442", CreditLimit=48000.0, CutoffDate="2026-06-26", PrevBalance=3000.0,
    ))
    assert warning is None

def test_check_continuity_no_prior_statement_is_silent():
    conn = db.connect(":memory:")
    db.init_db(conn)
    warning = validate.check_continuity(conn, _stmt_row(PrevBalance=1000.0))
    assert warning is None

def test_set_override_retrofits_existing_rows_and_persists():
    # Phase 8 viewer write path: correcting a category must (a) fix rows
    # already in the DB immediately, and (b) persist so future imports of the
    # same description are recategorized via apply_override.
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.insert_transactions(conn, [{
        "Bank": "Nu", "Date": "2026-06-01", "Description": "STARBUCKS COYOACAN",
        "Category": "Restaurants", "Amount": 80.0, "Type": "charge", "Review": "",
        "File": "f",
    }])
    db.set_override(conn, "STARBUCKS COYOACAN", "Health/Gym")

    row = conn.execute(
        "SELECT category FROM transactions WHERE description = ?", ("STARBUCKS COYOACAN",)
    ).fetchone()
    assert row["category"] == "Health/Gym"

    assert db.apply_override(conn, "STARBUCKS COYOACAN", "Restaurants") == "Health/Gym"


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
