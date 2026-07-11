"""
Santander debit/checking account statement parser (cuenta de cheques).
Image-only PDF, OCR required (like Liverpool).

Unlike the credit-card parsers, this is a debit account: the printed table
has separate DEPOSITO/RETIRO columns plus a running SALDO, no per-row sign.
--psm 6 (assume a uniform block of text) is required to keep OCR reading the
table row-by-row instead of column-by-column (the default psm scrambles row
order on this layout). Even with --psm 6 the two amount columns collapse
into a single number per row, so the sign (deposit vs withdrawal) is
recovered from the running-balance delta between consecutive rows, seeded
from "SALDO FINAL DEL PERIODO ANTERIOR". abs(amount) is cross-checked
against abs(balance delta); a mismatch flags the row for review rather than
guessing.

Only the "cuenta de cheques" (checking) section is parsed. The statement
also prints a separate "Dinero Creciente" (savings/investment) sub-ledger
with its own balance track and daily interest-accrual rows - a different
product with no spend semantics, out of scope here (same reasoning as not
parsing a linked brokerage statement).

Internal transfers between the two sub-accounts (e.g. "CARGO APERTURA INV
CRECIENTE ... A INVERSION VISTA", "LIQ A CHE INVERSION ... A CHEQUES") DO
show up as real rows in the checking ledger and ARE captured here - the
statement's own printed totals include them - but categorize.py buckets
them under "Transferencias Internas" so they don't inflate spend summaries.
"""
from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

from parsers.base import clean_amount, ocr_pdf_pages as _ocr_pdf_pages

if TYPE_CHECKING:
    from parsers.base import Transaction

# NOTE: section labels below are the literal Spanish text printed on
# Santander statements, so they must stay in Spanish.
CHEQUES_SECTION_START = ("DETALLE", "CUENTA DE CHEQUES")

# Folios on this statement are consistently 7 digits. OCR adds stray "|" or
# "(" noise around the folio column border, tolerated below.
ROW_RE = re.compile(
    r"^(\d{2}-[A-Za-z]{3}-\d{4})\s*[|(]?\s*(\d{7})\s*\|?\s*(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*\$?\s*$"
)
PREV_BALANCE_RE = re.compile(
    r"SALDO FINAL DEL PERIODO ANTERIOR:?\s*\$?([\d,]+\.\d{2})", re.IGNORECASE
)

BALANCE_TOLERANCE = 0.01  # pesos; absorbs float rounding only


def ocr_pdf_pages(pdf_path: str) -> list[str]:
    return _ocr_pdf_pages(pdf_path, tesseract_config="--psm 6")


def resolve_sign(amount: float, delta: float) -> tuple[float, bool]:
    """Returns (signed_amount, needs_review) from the unsigned OCR'd amount and
    the running-balance delta (balance_now - balance_prev). A positive delta
    means a deposit/credit (negative per repo convention); a negative delta
    means a withdrawal/charge (positive). needs_review flags a mismatch
    between abs(delta) and the OCR'd amount, or a zero delta (should never
    happen for a real movement row - signals OCR corruption)."""
    if delta > 0:
        return -amount, abs(delta - amount) > BALANCE_TOLERANCE
    if delta < 0:
        return amount, abs(-delta - amount) > BALANCE_TOLERANCE
    return amount, True


def parse_santander(pdf_path: str) -> tuple[list[Transaction], str]:
    pages_text = ocr_pdf_pages(pdf_path)
    full_text = "\n".join(pages_text)

    rows = []
    in_cheques_section = False
    prev_balance = None

    for raw_line in full_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()

        if all(token in upper for token in CHEQUES_SECTION_START):
            in_cheques_section = True
            continue
        if in_cheques_section and upper.startswith("TOTAL"):
            in_cheques_section = False
            continue
        if not in_cheques_section:
            continue

        if prev_balance is None:
            m_bal = PREV_BALANCE_RE.search(line)
            if m_bal:
                prev_balance = clean_amount(m_bal.group(1))
                continue

        m = ROW_RE.match(line)
        if not m:
            continue
        date, folio, description, amount_raw, balance_raw = m.groups()
        amount = clean_amount(amount_raw)
        balance = clean_amount(balance_raw)
        delta = balance - prev_balance
        signed_amount, needs_review = resolve_sign(amount, delta)

        rows.append({
            "date": date,
            "description": description.strip(),
            "amount": signed_amount,
            "type": "payment" if signed_amount < 0 else "charge",
            "needs_review": needs_review,
        })
        prev_balance = balance

    return rows, full_text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parsers/santander.py path/to/statement.pdf")
    rows, _ = parse_santander(sys.argv[1])
    print(f"Total transactions: {len(rows)}")
    for r in rows:
        print(r)
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    print(f"\nTotal charges (retiros): {charges:.2f}")
    print(f"Total payments (depositos): {payments:.2f}")
    flagged = sum(1 for r in rows if r["needs_review"])
    print(f"Flagged for review: {flagged}")
    print("Reconcile these against +Depositos/-Retiros printed on the statement.")
