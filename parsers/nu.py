"""
Nu credit card statement parser.
Text is directly extractable, no OCR needed - the simplest of the four.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pdfplumber

from parsers.base import MONTHS, SPANISH_MONTHS, clean_amount

if TYPE_CHECKING:
    from parsers.base import Transaction

ROW_RE = re.compile(
    rf"^(\d{{2}}\s+(?:{MONTHS})\s+\d{{4}})\s+(\d{{2}}\s+(?:{MONTHS})\s+\d{{4}})\s+"
    rf"(.+?)\s*\|\s*RFC:\s*\S+\s*([+-])\$?\s*([\d,]+\.\d{{2}})\s*$",
    re.IGNORECASE,
)


def date_to_iso(date_str: str) -> str:
    day, mon, year = date_str.split()
    return f"{year}-{SPANISH_MONTHS[mon.upper()]:02d}-{int(day):02d}"


def parse_nu(pdf_path: str) -> list[Transaction]:
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "CARGOS, ABONOS Y COMPRAS REGULARES" not in text.upper():
                continue
            for line in text.split("\n"):
                line = line.strip()
                m = ROW_RE.match(line)
                if not m:
                    continue
                op_date, charge_date, description, sign, amount_raw = m.groups()
                amount = clean_amount(amount_raw)
                if sign == "-":
                    amount = -amount
                rows.append({
                    "date": date_to_iso(op_date),
                    "description": description.strip(),
                    "amount": amount,
                    "type": "payment" if amount < 0 else "charge",
                })
    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parsers/nu.py path/to/statement.pdf")
    rows = parse_nu(sys.argv[1])
    print(f"Total transactions: {len(rows)}")
    for r in rows:
        print(r)
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    print(f"\nTotal charges: {charges:.2f}")
    print(f"Total payments: {payments:.2f}")
    print("Reconcile these against the totals printed on the statement.")
