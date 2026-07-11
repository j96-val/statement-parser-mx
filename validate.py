"""
Validation gate: runs per file, after parsing, before DB insertion.

Two severities:
- hard fail: the file's rows must NOT be inserted (validate_file returns
  hard_ok=False). Currently: zero rows from a detected bank, or a totals
  mismatch beyond tolerance.
- soft warning: printed for visibility, doesn't block insertion. Currently:
  an outlier amount, or a high share of OCR-fallback rows.

Totals reconciliation compares each bank's own printed total against what we
extracted. Not every bank prints one we can confidently anchor a regex to -
see extract_printed_totals for what's reliable per bank and why. A side we
can't confidently extract is skipped (None), never treated as a mismatch.
"""
import re
import statistics

import pdfplumber

import config
from parsers.liverpool import MONEY_RE, normalize_line, clean_amount as liverpool_clean_amount

TOLERANCE = 1.00  # pesos; absorbs rounding/cents noise, not real discrepancies

NU_CHARGES_RE = re.compile(r"Cargos regulares \(no a meses\)\s*\+\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
NU_PAYMENTS_RE = re.compile(r"Pagos y abonos\s*-\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
INVEX_CHARGES_RE = re.compile(r"Total cargos\s*\+\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
INVEX_PAYMENTS_RE = re.compile(r"Total abonos\s*-\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
BANORTE_CHARGES_RE = re.compile(r"Total cargos\s*\+\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
BANORTE_PAYMENTS_RE = re.compile(r"Total abonos\s*-\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)
# Santander's "Cuenta de cheques." summary block (Depositos/Retiros for the
# checking sub-account) prints before the "Dinero Creciente" (savings)
# sub-account's own Depositos/Retiros recap further down the OCR'd text, so a
# plain first-match search picks the right (checking) numbers.
SANTANDER_CHARGES_RE = re.compile(r"-\s*Retiros\s+([\d,]+\.\d{2})", re.IGNORECASE)
SANTANDER_PAYMENTS_RE = re.compile(r"\+\s*Depositos\s+([\d,]+\.\d{2})", re.IGNORECASE)


def check_empty(bank: str, rows: list[dict]) -> str | None:
    """Hard fail: a known bank detected but zero rows parsed (section/regex broke)."""
    if bank != "unknown" and not rows:
        return f"{bank}: 0 transactions extracted - section detection or regex likely broke"
    return None


def check_outliers(rows: list[dict], k: int = 20) -> list[str]:
    """Soft warn: a charge k times the file's median charge (likely an OCR digit
    corruption, e.g. a missing thousands separator)."""
    charges = [r["Amount"] for r in rows if r["Amount"] > 0]
    if len(charges) < 2:
        return []
    med = statistics.median(charges)
    if med <= 0:
        return []
    return [
        f"{r['Amount']:.2f} ({r['Description']!r}) is {r['Amount'] / med:.0f}x the file's median charge"
        for r in rows if r["Amount"] > med * k
    ]


def check_review_ratio(rows: list[dict], threshold: float = 0.2) -> str | None:
    """Soft warn: a high share of rows needed an OCR fallback/reconstruction path -
    signals the bank may have changed its PDF format."""
    if not rows:
        return None
    flagged = sum(1 for r in rows if r.get("Review") == "YES")
    ratio = flagged / len(rows)
    if ratio > threshold:
        return f"{flagged}/{len(rows)} rows ({ratio:.0%}) flagged for review"
    return None


def reconcile(rows: list[dict], printed: dict) -> list[str]:
    """Hard-fail messages for any side whose printed total we could confidently
    extract and that diverges beyond TOLERANCE. A None side is skipped."""
    messages = []
    # Invex's printed "Total cargos" covers regular (non-installment) charges
    # only - installment rows carry is_installment=True and are excluded here
    # so they're not double-counted against a total that never included them.
    charges = sum(r["Amount"] for r in rows if r["Amount"] > 0 and not r.get("is_installment"))
    payments = sum(r["Amount"] for r in rows if r["Amount"] < 0)

    if printed.get("charges") is not None:
        diff = charges - printed["charges"]
        if abs(diff) > TOLERANCE:
            messages.append(
                f"charges mismatch: extracted {charges:.2f} vs printed {printed['charges']:.2f} (diff {diff:+.2f})"
            )
    if printed.get("payments") is not None:
        diff = payments - printed["payments"]
        if abs(diff) > TOLERANCE:
            messages.append(
                f"payments mismatch: extracted {payments:.2f} vs printed {printed['payments']:.2f} (diff {diff:+.2f})"
            )
    return messages


def _pdf_text(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _search(pattern: re.Pattern, text: str, negate: bool = False) -> float | None:
    m = pattern.search(text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    return -val if negate else val


def _liverpool_subtotal(ocr_text: str) -> dict:
    # The printed grand "TOTAL" line includes an "cargos a meses" (installment)
    # breakdown parse_liverpool doesn't capture, so it never matches. The
    # "Sub Total" line printed right after the regular-movements section does
    # match what we actually parse - it's the first "SUB TOTAL" line with
    # exactly two amounts (charges, then signed payments).
    for raw in ocr_text.split("\n"):
        line = normalize_line(raw)
        if "SUB TOTAL" in line.upper():
            amounts = MONEY_RE.findall(line)
            if len(amounts) == 2:
                return {
                    "charges": liverpool_clean_amount(amounts[0]),
                    "payments": liverpool_clean_amount(amounts[1]),
                }
    return {"charges": None, "payments": None}


def extract_printed_totals(bank: str, pdf_path: str, ocr_text: str | None = None) -> dict:
    """Returns {"charges": float|None, "payments": float|None}."""
    if bank == "nu":
        text = _pdf_text(pdf_path)
        return {
            "charges": _search(NU_CHARGES_RE, text),
            "payments": _search(NU_PAYMENTS_RE, text, negate=True),
        }
    if bank == "invex":
        text = _pdf_text(pdf_path)
        return {
            "charges": _search(INVEX_CHARGES_RE, text),
            "payments": _search(INVEX_PAYMENTS_RE, text, negate=True),
        }
    if bank == "banorte":
        text = _pdf_text(pdf_path)
        return {
            "charges": _search(BANORTE_CHARGES_RE, text),
            "payments": _search(BANORTE_PAYMENTS_RE, text, negate=True),
        }
    if bank == "liverpool":
        return _liverpool_subtotal(ocr_text or "")
    if bank == "santander":
        text = ocr_text or ""
        return {
            "charges": _search(SANTANDER_CHARGES_RE, text),
            "payments": _search(SANTANDER_PAYMENTS_RE, text, negate=True),
        }
    # Banamex: no reliably labeled total line. The numbers that would let us
    # reconcile ("Cargos regulares (no a meses)") only match by coincidence -
    # it excludes interest/commission charges the movement rows do include,
    # and the one place the real total appears is an unlabeled balance-formula
    # table row ("- +$8,124.91 +$0.00 ..."). Too fragile to regex confidently.
    # ponytail: skip both sides; row-level checks still cover Banamex files.
    return {"charges": None, "payments": None}


def validate_file(bank: str, rows: list[dict], pdf_path: str, ocr_text: str | None = None) -> tuple[bool, list[str]]:
    """hard_ok gates DB insertion. In warn-only mode (config.VALIDATION_STRICT
    is False) hard-fail conditions still run and print, but never block."""
    hard_reasons = []

    empty_msg = check_empty(bank, rows)
    if empty_msg:
        hard_reasons.append(empty_msg)

    printed = extract_printed_totals(bank, pdf_path, ocr_text)
    hard_reasons.extend(reconcile(rows, printed))

    icon = "❌" if config.VALIDATION_STRICT else "⚠️ "
    messages = [f"{icon} {m}" for m in hard_reasons]
    messages.extend(f"⚠️  {w}" for w in check_outliers(rows))
    ratio_msg = check_review_ratio(rows)
    if ratio_msg:
        messages.append(f"⚠️  {ratio_msg}")

    hard_ok = not hard_reasons or not config.VALIDATION_STRICT
    return hard_ok, messages
