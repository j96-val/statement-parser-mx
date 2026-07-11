"""
Banorte credit card statement parser (Tarjeta Clásica).
Text is directly extractable, no OCR needed.

Only parses "CARGOS, ABONOS Y COMPRAS REGULARES (NO A MESES)" - the monthly
installment charge from "COMPRAS Y CARGOS DIFERIDOS A MESES SIN INTERESES"
already reappears as a regular-section row each period (unlike Invex, where
installments are a separate line not covered by the regular section), so
parsing both would double-count. The printed "Total cargos"/"Total abonos"
only cover the regular section anyway, which is what this reconciles against.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pdfplumber

if TYPE_CHECKING:
    from parsers.base import Transaction

# NOTE: month abbreviations and section labels below are the literal
# Spanish text printed on Banorte statements, so they must stay in Spanish.
MONTHS = "ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic"

ROW_REGULAR_RE = re.compile(
    rf"^(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(.+?)\s*([+-])\s*\$?\s*([\d,]+\.\d{{2}})\s*$",
    re.IGNORECASE,
)


def clean_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_banorte(pdf_path: str) -> list[Transaction]:
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "DESGLOSE DE MOVIMIENTOS" not in text.upper():
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                m = ROW_REGULAR_RE.match(line)
                if not m:
                    continue
                op_date, charge_date, description, sign, amount_raw = m.groups()
                amount = clean_amount(amount_raw)
                if sign == "-":
                    amount = -amount
                rows.append({
                    "date": op_date,
                    "description": description.strip(),
                    "amount": amount,
                    "type": "payment" if amount < 0 else "charge",
                })
    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parsers/banorte.py path/to/statement.pdf")
    rows = parse_banorte(sys.argv[1])
    print(f"Total transactions: {len(rows)}")
    for r in rows:
        print(r)
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    print(f"\nTotal charges: {charges:.2f}")
    print(f"Total payments: {payments:.2f}")
    print("Reconcile these against the totals printed on the statement.")
