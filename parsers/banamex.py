"""
Banamex credit card statement parser.
Uses direct text extraction (works well) plus OCR as a fallback for
bold rows the PDF doesn't expose as text (e.g. "SU ABONO...GRACIAS").
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pdfplumber
import pytesseract
from pdf2image import convert_from_path

import config

if TYPE_CHECKING:
    from parsers.base import Transaction

# NOTE: month abbreviations and keywords below are the literal Spanish
# text printed on Banamex statements, so they must stay in Spanish.
MONTHS = "ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic"
ROW_RE = re.compile(
    rf"^(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(.+?)\s*([+-])\s*\$?\s*([\d,]+\.\d{{2}})\s*$",
    re.IGNORECASE,
)


def clean_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def extract_rows_from_text(
    text: str, card_type: str, seen_keys: set, dedup: bool = False
) -> tuple[list[Transaction], str]:
    """Extracts transactions from a block of text (from pdfplumber or OCR).
    Returns (rows, final_card_type) - the card type is updated line by line
    as section headers appear.

    dedup=False (text pass): append every row and record its (date, amount)
    key, so two genuine same-day same-amount charges both survive.
    dedup=True (OCR fallback pass): skip rows whose (date, amount) the text
    pass already captured, so re-read rows aren't duplicated. Matching on
    (date, amount) only, since OCR may read the description slightly
    differently than the text layer.
    """
    rows = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        upper = line.upper()
        if "TARJETA DIGITAL" in upper:
            card_type = "digital"
            continue
        if "TARJETA TITULAR" in upper:
            card_type = "primary"
            continue

        m = ROW_RE.match(line)
        if m:
            op_date, charge_date, description, sign, amount_raw = m.groups()
            amount = clean_amount(amount_raw)
            if sign == "-":
                amount = -amount
            # strip OCR artifacts at the start of the description (e.g. "+ ANTHROPIC...")
            description = re.sub(r"^[+\-]\s*", "", description.strip())
            key = (op_date, round(amount, 2))
            if dedup and key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append({
                "date": op_date,
                "description": description,
                "amount": amount,
                "type": "payment" if amount < 0 else "charge",
                "card": card_type,
                "source": "text",
            })
    return rows, card_type


def parse_banamex(pdf_path: str) -> list[Transaction]:
    all_rows = []
    seen_keys = set()
    card_type = "primary"

    with pdfplumber.open(pdf_path) as pdf:
        movement_pages = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if any(ROW_RE.match(line.strip()) for line in text.split("\n")):
                movement_pages.append(i)

        for i in movement_pages:
            text = pdf.pages[i].extract_text() or ""
            rows, card_type = extract_rows_from_text(text, card_type, seen_keys, dedup=False)
            all_rows.extend(rows)

        # --- OCR fallback, only for the movement pages, to capture bold
        # rows (e.g. payments) that the text layer doesn't expose ---
        if movement_pages:
            images = convert_from_path(
                pdf_path, dpi=config.OCR_DPI,
                first_page=min(movement_pages) + 1,
                last_page=max(movement_pages) + 1,
            )
            card_type = "primary"
            for img in images:
                ocr_text = pytesseract.image_to_string(img, lang="eng")
                rows, card_type = extract_rows_from_text(ocr_text, card_type, seen_keys, dedup=True)
                for r in rows:
                    r["source"] = "ocr_fallback"
                all_rows.extend(rows)

    return all_rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parsers/banamex.py path/to/statement.pdf")
    rows = parse_banamex(sys.argv[1])
    print(f"Total transactions: {len(rows)}")
    charges = sum(r["amount"] for r in rows if r["amount"] > 0)
    payments = sum(r["amount"] for r in rows if r["amount"] < 0)
    for r in rows:
        print(r)
    print(f"\nTotal charges: {charges:.2f}")
    print(f"Total payments: {payments:.2f}")
    print("Reconcile these against the totals printed on the statement.")
