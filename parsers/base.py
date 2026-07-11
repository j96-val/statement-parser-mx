"""
Shared contract every bank parser returns: a list of Transaction dicts.

Amount sign convention: positive = charge, negative = payment/refund.

Some banks attach extra keys beyond this base shape (Liverpool's
"needs_review", Banamex's "card"/"source", Invex's "is_installment") -
build_report.py reads those per-bank when it builds the Review column.

Also holds primitives shared across parser modules and statements.py/
build_report.py: the Spanish month abbreviations printed on every statement,
the DD-mon-YYYY regex fragment, the date-date-description-+/-$amount row
shape (identical across Banamex/Invex/Banorte's regular sections), amount
cleaning, and the tesseract OCR wrapper (Liverpool/Santander).
"""
from typing import TypedDict

import pytesseract
from pdf2image import convert_from_path

import config


class Transaction(TypedDict):
    date: str
    description: str
    amount: float
    type: str  # "charge" | "payment"


MONTHS = "ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic"
SPANISH_MONTHS = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

# date date description +/-$amount - Banamex/Invex(regular)/Banorte(regular) share this exact shape
ROW_REGULAR_RE_SRC = (
    rf"^(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(\d{{2}}-(?:{MONTHS})-\d{{4}})\s+(.+?)\s*([+-])\s*\$?\s*([\d,]+\.\d{{2}})\s*$"
)


def clean_amount(raw: str) -> float:
    """Strips spaces (OCR sometimes splits a number across a stray space,
    e.g. Liverpool's "-1 234.56") and thousands commas, then parses to float."""
    return float(raw.replace(" ", "").replace(",", ""))


def ocr_pdf_pages(pdf_path: str, dpi: int = None, tesseract_config: str = "") -> list[str]:
    """Renders each page to an image and runs OCR. Returns one text block per page."""
    images = convert_from_path(pdf_path, dpi=dpi or config.OCR_DPI)
    return [pytesseract.image_to_string(img, lang="eng", config=tesseract_config) for img in images]
