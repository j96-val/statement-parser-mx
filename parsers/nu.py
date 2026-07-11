"""
Nu credit card statement parser.
Text is directly extractable, no OCR needed - the simplest of the four.
"""
import re

import pdfplumber

# NOTE: month abbreviations and the section label below are the literal
# Spanish text printed on Nu statements, so they must stay in Spanish.
MONTHS = "ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC"

ROW_RE = re.compile(
    rf"^(\d{{2}}\s+(?:{MONTHS})\s+\d{{4}})\s+(\d{{2}}\s+(?:{MONTHS})\s+\d{{4}})\s+"
    rf"(.+?)\s*\|\s*RFC:\s*\S+\s*([+-])\$?\s*([\d,]+\.\d{{2}})\s*$",
    re.IGNORECASE,
)

MONTHS_MAP = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


def clean_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def date_to_iso(date_str: str) -> str:
    day, mon, year = date_str.split()
    return f"{year}-{MONTHS_MAP[mon.upper()]:02d}-{int(day):02d}"


def parse_nu(pdf_path: str):
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
