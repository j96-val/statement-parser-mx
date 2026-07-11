"""
INVEX credit card statement parser (Volaris Invex card).
Text is directly extractable, no OCR needed.
Handles two sections:
  1. Purchases deferred to interest-free monthly installments (MSI)
  2. Regular charges, payments and purchases (not on installments)
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pdfplumber

if TYPE_CHECKING:
    from parsers.base import Transaction

# NOTE: month abbreviations and section labels below are the literal
# Spanish text printed on INVEX statements, so they must stay in Spanish.
MONTHS = "ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic"

ROW_REGULAR_RE = re.compile(
    rf"^(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(.+?)\s*([+-])\s*\$?\s*([\d,]+\.\d{{2}})\s*$",
    re.IGNORECASE,
)

ROW_INSTALLMENT_RE = re.compile(
    rf"^(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(.+?)\s+\$([\d,]+\.\d{{2}})\s+\$([\d,]+\.\d{{2}})\s+"
    rf"\$([\d,]+\.\d{{2}})\s+(\d+\s+de\s+\d+)\s+([\d.]+)%\s*$",
    re.IGNORECASE,
)

STATEMENT_DATE_RE = re.compile(r"Fecha de [Cc]orte:?\s*(\d{2}-\w{3}-\d{4})", re.IGNORECASE)

def clean_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def get_statement_date(pdf) -> str | None:
    for page in pdf.pages[:2]:
        text = page.extract_text() or ""
        m = STATEMENT_DATE_RE.search(text)
        if m:
            return m.group(1)
    return None


def parse_invex(pdf_path: str) -> list[Transaction]:
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        statement_date = get_statement_date(pdf)

        for page in pdf.pages:
            text = page.extract_text() or ""
            if "DESGLOSE DE MOVIMIENTOS" not in text.upper():
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                m_installment = ROW_INSTALLMENT_RE.match(line)
                if m_installment:
                    purchase_date, desc, original, balance, installment_due, installment_num, rate = m_installment.groups()
                    num, total = installment_num.split(" de ")
                    rows.append({
                        # Use the statement's cut-off date, not the original
                        # purchase date: this same purchase reappears on every
                        # monthly statement with a different installment_num,
                        # and each one is a separate real charge to the card
                        # in that month. Using purchase_date would collapse
                        # every installment onto the same month, which breaks
                        # month-over-month comparisons. Falls back to the
                        # purchase date only if the cut-off date wasn't found.
                        "date": statement_date or purchase_date,
                        "statement_date": statement_date,
                        "description": desc.strip(),
                        "amount": clean_amount(installment_due),
                        "type": "charge",
                        "is_installment": True,
                        "installment_num": int(num),
                        "installment_total": int(total),
                        "original_amount": clean_amount(original),
                        "remaining_balance": clean_amount(balance),
                        "rate": float(rate),
                    })
                    continue

                m_regular = ROW_REGULAR_RE.match(line)
                if m_regular:
                    op_date, charge_date, description, sign, amount_raw = m_regular.groups()
                    amount = clean_amount(amount_raw)
                    if sign == "-":
                        amount = -amount
                    rows.append({
                        "date": op_date,
                        "charge_date": charge_date,
                        "statement_date": statement_date,
                        "description": description.strip(),
                        "amount": amount,
                        "type": "payment" if amount < 0 else "charge",
                        "is_installment": False,
                    })
    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parsers/invex.py path/to/statement.pdf")
    rows = parse_invex(sys.argv[1])
    print(f"Total transactions: {len(rows)}")
    for r in rows:
        print(r)
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    print(f"\nTotal charges: {charges:.2f}")
    print(f"Total payments: {payments:.2f}")
    print("Reconcile these against the totals printed on the statement.")
