"""
Statement-level (cover-page) extraction: the numbers a bank prints once per
statement - billing period, cut-off date, balances, limits - as opposed to
parsers/*.py, which extract one row per transaction.

Mirrors validate.py's per-bank dispatch pattern (extract_printed_totals).
Banamex/Invex/Nu/Banorte print the same CONDUSEF-mandated disclosure block on
their cover page, so they share one regex set (_extract_text_bank). Santander
(debit, OCR) and Liverpool (credit, OCR) each print their own layout.

A field a bank doesn't reliably print is left None rather than guessed - see
validate.py's own comment on why Banamex's totals can't be confidently
regexed; the same caution applies here (Banamex prints no previous-balance
line anywhere in the statement).
"""
import re
from pathlib import Path

from validate import _pdf_text
from parsers.base import MONTHS, SPANISH_MONTHS, clean_amount

DATE_TOKEN = rf"(\d{{2}})[-\s]({MONTHS})[-\s](\d{{4}})"

PERIOD_RE = re.compile(rf"Periodo:?\s*{DATE_TOKEN}\s*al\s*{DATE_TOKEN}", re.IGNORECASE)
CUTOFF_RE = re.compile(rf"Fecha de [Cc]orte:?\s*{DATE_TOKEN}", re.IGNORECASE)
LIMIT_RE = re.compile(r"L[íi]mite de cr[ée]dito:?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
# ":?\d*" swallows the disclosure block's footnote superscript, e.g.
# "Pago mínimo:4 $600.00" or "Saldo deudor total:12 $4,227.82".
MIN_PAYMENT_RE = re.compile(r"Pago m[íi]nimo:?\d*\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
NO_INTEREST_RE = re.compile(r"Pago para no generar intereses:?\d*\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
PREV_BALANCE_RE = re.compile(r"Adeudo del periodo anterior\s*=?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
CLOSING_TOTAL_RE = re.compile(r"Saldo deudor total:?\d*\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
CLOSING_REGULAR_RE = re.compile(r"Saldo cargos regulares:?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
CLOSING_INSTALLMENT_RE = re.compile(r"Saldo cargos a meses:?\s*\$?\s*([\d,]+\.\d{2})", re.IGNORECASE)
# Last 4 digits only - never store the full PAN even though some banks'
# statements print it unmasked (e.g. Banorte).
CARD_RE = re.compile(r"[Nn][úu]mero de (?:la )?[Tt]arjeta:?\s*(?:[X\d]{4}[-\s]){3}(\d{4})")

SANTANDER_PERIOD_RE = re.compile(
    r"PERIODO DEL\s*(\d{2})-([A-Z]{3})-(\d{4})\s*AL\s*(\d{2})-([A-Z]{3})-(\d{4})", re.IGNORECASE
)
SANTANDER_CUTOFF_RE = re.compile(r"CORTE AL\s*(\d{2})-([A-Z]{3})-(\d{4})", re.IGNORECASE)
SANTANDER_TOTAL_ROW_RE = re.compile(r"TOTAL\s+([\d,]+\.\d{2})\s+[\d.]+%\s+([\d,]+\.\d{2})", re.IGNORECASE)

LIVERPOOL_PREV_RE = re.compile(r"SALDO ANTERIOR\s+([\d,]+\.\d{2})", re.IGNORECASE)
LIVERPOOL_CHARGES_RE = re.compile(r"COMPRAS Y CARGOS\s+([\d,]+\.\d{2})", re.IGNORECASE)
LIVERPOOL_PAYMENTS_RE = re.compile(r"PAGOS Y ABONOS\s+(-?[\d,]+\.\d{2})", re.IGNORECASE)
LIVERPOOL_COMMISSIONS_RE = re.compile(r"COMISIONES\s+([\d,]+\.\d{2})", re.IGNORECASE)
LIVERPOOL_FILENAME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _num(pattern: re.Pattern, text: str) -> float | None:
    m = pattern.search(text)
    return clean_amount(m.group(1)) if m else None


def _iso(day: str, mon: str, year: str) -> str:
    return f"{year}-{SPANISH_MONTHS[mon.upper()]:02d}-{int(day):02d}"


def _extract_text_bank(text: str) -> dict:
    period_start = period_end = cutoff_date = None
    m = PERIOD_RE.search(text)
    if m:
        period_start = _iso(*m.groups()[0:3])
        period_end = _iso(*m.groups()[3:6])
    m = CUTOFF_RE.search(text)
    if m:
        cutoff_date = _iso(*m.groups())

    closing_balance = _num(CLOSING_TOTAL_RE, text)
    if closing_balance is None and (CLOSING_REGULAR_RE.search(text) or CLOSING_INSTALLMENT_RE.search(text)):
        closing_balance = (_num(CLOSING_REGULAR_RE, text) or 0.0) + (_num(CLOSING_INSTALLMENT_RE, text) or 0.0)

    card_m = CARD_RE.search(text)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "cutoff_date": cutoff_date,
        "prev_balance": _num(PREV_BALANCE_RE, text),
        "closing_balance": closing_balance,
        "min_payment": _num(MIN_PAYMENT_RE, text),
        "no_interest_payment": _num(NO_INTEREST_RE, text),
        "credit_limit": _num(LIMIT_RE, text),
        "card": card_m.group(1) if card_m else None,
    }


def _extract_santander(text: str) -> dict:
    period_start = period_end = cutoff_date = None
    m = SANTANDER_PERIOD_RE.search(text)
    if m:
        period_start = _iso(*m.groups()[0:3])
        period_end = _iso(*m.groups()[3:6])
    m = SANTANDER_CUTOFF_RE.search(text)
    if m:
        cutoff_date = _iso(*m.groups())

    prev_balance = closing_balance = None
    m = SANTANDER_TOTAL_ROW_RE.search(text)
    if m:
        prev_balance = clean_amount(m.group(1))
        closing_balance = clean_amount(m.group(2))

    return {
        "period_start": period_start,
        "period_end": period_end,
        "cutoff_date": cutoff_date,
        "prev_balance": prev_balance,
        "closing_balance": closing_balance,
        "min_payment": None,  # debit account, no credit terms
        "no_interest_payment": None,
        "credit_limit": None,
        "card": None,
    }


def _liverpool_cutoff_from_filename(pdf_path: str) -> str | None:
    # Liverpool's statement never prints a cut-off date anywhere in the PDF
    # (OCR-only, no "Fecha de corte" line) - see README's filename
    # convention: liverpool-YYYY-MM-DD.pdf.
    m = LIVERPOOL_FILENAME_RE.search(Path(pdf_path).stem)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _extract_liverpool(text: str, pdf_path: str) -> dict:
    prev_balance = _num(LIVERPOOL_PREV_RE, text)
    charges = _num(LIVERPOOL_CHARGES_RE, text)
    payments = _num(LIVERPOOL_PAYMENTS_RE, text)
    commissions = _num(LIVERPOOL_COMMISSIONS_RE, text)

    # The printed "Saldo total al corte" OCRs corrupted (garbled digits/
    # letters) on every sample we have, so it's derived from these 4
    # cover-page totals instead - each is its own clean, isolated OCR line
    # (unlike the mangled "Saldo total al corte" line, which sits inside a
    # dense summary block). These are the statement's own whole-period
    # totals (including MSI cargos a meses), not the parsed transaction
    # rows' sum - validate.py already reconciles the rows separately
    # against the "Sub Total" line, a different, narrower figure.
    closing_balance = None
    if None not in (prev_balance, charges, payments, commissions):
        closing_balance = prev_balance + charges + commissions + payments

    return {
        "period_start": None,
        "period_end": None,
        "cutoff_date": _liverpool_cutoff_from_filename(pdf_path),
        "prev_balance": prev_balance,
        "closing_balance": closing_balance,
        "min_payment": None,  # "PAGO MINIMO" table row OCRs garbled, too fragile to regex
        "no_interest_payment": None,
        "credit_limit": None,  # not printed anywhere on the statement
        "card": None,
    }


def extract_statement(bank: str, pdf_path: str, ocr_text: str | None = None) -> dict | None:
    """Returns cover-page fields for one statement, or None for an
    unsupported bank. Any field the bank doesn't reliably print is None."""
    if bank in ("banamex", "invex", "nu", "banorte"):
        return _extract_text_bank(_pdf_text(pdf_path))
    if bank == "santander":
        return _extract_santander(ocr_text or "")
    if bank == "liverpool":
        return _extract_liverpool(ocr_text or "", pdf_path)
    return None
