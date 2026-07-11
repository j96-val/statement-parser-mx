"""
Liverpool credit card statement parser (PDF -> classified transactions).
Liverpool statements embed text with a broken/custom font encoding, so
direct text extraction fails and OCR is required instead.
"""
import re
import sys

import pytesseract
from pdf2image import convert_from_path

MONTHS = "ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC"
DATE_RE = re.compile(rf"^\s*(\d{{1,2}})\s*[-\s]\s*({MONTHS})\b", re.IGNORECASE)
# Allow ungrouped digits: OCR frequently drops thousands separators, so a
# strict \d{1,3}(?:,\d{3})* pattern would truncate "11131.00" to "131.00".
MONEY_RE = re.compile(r"-?\s?\d[\d,]*\.\d{2}")

STOP_MARKERS = [
    "TARJETAS ADICIONALES",   # additional-cardholder section, excluded
    "RESUMEN DE PLANES",
    "TOTAL DE INTERESES",
]

# NOTE: these phrases are the literal Spanish text printed on Liverpool
# statements, so they must stay in Spanish for the matching to work.
PAYMENT_KEYWORDS = ("GRACIAS POR SU PAGO", "SU PAGO SPEI", "SU PAGO EN")


def ocr_pdf_pages(pdf_path: str, dpi: int = 300) -> list[str]:
    """Renders each page to an image and runs OCR. Returns one text block per page."""
    images = convert_from_path(pdf_path, dpi=dpi)
    pages_text = []
    for img in images:
        text = pytesseract.image_to_string(img, lang="eng")
        pages_text.append(text)
    return pages_text


def clean_amount(raw: str) -> float:
    raw = raw.replace(" ", "").replace(",", "")
    return float(raw)


def normalize_line(line: str) -> str:
    # common OCR fixes
    line = line.replace("|", "1").replace("O1-", "01-")
    # merges numbers OCR split with a stray space, e.g. "-1 1,131.00" -> "-11,131.00"
    line = re.sub(r"(-\s*\d{1,3})\s+(\d{1,3}(?:,\d{3})*\.\d{2})", r"\1\2", line)
    # OCR sometimes misreads the final decimal point as a comma, e.g. "-11,725,00" -> "-11,725.00"
    line = re.sub(r"(\d),(\d{2})(?!\d)", r"\1.\2", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def parse_liverpool(pdf_path: str, primary_cardholder_only: bool = True):
    pages_text = ocr_pdf_pages(pdf_path)
    full_text = "\n".join(pages_text)
    lines = full_text.split("\n")

    transactions = []
    in_movements_section = False
    in_additional_card_section = False
    review_needed = []

    for raw_line in lines:
        line = normalize_line(raw_line)
        if not line:
            continue

        upper = line.upper()

        if "DETALLE DE MOVIMIENTOS TARJETAS ADICIONALES" in upper:
            in_additional_card_section = True
            in_movements_section = True
            continue
        if "DETALLE DE MOVIMIENTOS DEL" in upper and "ADICIONALES" not in upper:
            in_movements_section = True
            in_additional_card_section = False
            continue
        if any(marker in upper for marker in STOP_MARKERS):
            if "TARJETAS ADICIONALES" not in upper:
                in_movements_section = False
                in_additional_card_section = False
            continue
        if "SUB TOTAL" in upper or upper.startswith("TOTAL"):
            continue
        if "FECHA SEGMENTO CONCEPTO" in upper or "FECHA" == upper.strip():
            continue

        if not in_movements_section:
            continue
        if primary_cardholder_only and in_additional_card_section:
            continue

        m = DATE_RE.match(line)
        if not m:
            continue

        day, mon = m.group(1), m.group(2).upper()
        rest = line[m.end():].strip()

        amounts = MONEY_RE.findall(rest)
        fallback_used = False

        if not amounts:
            # OCR sometimes drops the decimal point entirely (e.g. "32329" instead of "323.29")
            fb = re.search(r"(-?\d{3,7})\s*$", rest)
            if not fb:
                continue
            digits = fb.group(1)
            sign = "-" if digits.startswith("-") else ""
            digits = digits.lstrip("-")
            reconstructed = f"{sign}{digits[:-2]}.{digits[-2:]}"
            amounts = [reconstructed]
            fallback_used = True

        # description = everything before the first amount
        if fallback_used:
            first_amount_pos = rest.rfind(digits)
        else:
            first_amount_pos = rest.find(amounts[0])
        description_raw = rest[:first_amount_pos].strip()

        # strip the leading numeric segment code (e.g. "001") and "PRESUPUESTO"
        description_raw = re.sub(r"^\d{2,3}\s+", "", description_raw)
        description_clean = re.sub(
            r"\bPRESUPUESTO\b.*$", "", description_raw, flags=re.IGNORECASE
        ).strip()
        if not description_clean:
            description_clean = description_raw.strip()

        amount = clean_amount(amounts[0])

        if any(kw in description_clean.upper() for kw in PAYMENT_KEYWORDS):
            amount = -abs(amount)

        flag = len(amounts) > 1 or fallback_used

        transactions.append(
            {
                "date": f"{day.zfill(2)}-{mon}",
                "description": description_clean,
                "amount": amount,
                "type": "payment" if amount < 0 else "charge",
                "needs_review": flag,
            }
        )
        if flag:
            review_needed.append(line)

    return transactions, review_needed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 parsers/liverpool.py path/to/statement.pdf")
    txns, review = parse_liverpool(sys.argv[1])
    print(f"Total transactions extracted: {len(txns)}")
    for t in txns:
        print(t)
    print(f"\nLines that need manual review (multiple amounts): {len(review)}")
    for r in review:
        print(" -", r)
