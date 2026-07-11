"""
Master pipeline: accepts PDFs from any supported bank (mixed together),
detects which bank each one is from, extracts transactions, categorizes
them, and generates a single consolidated Excel workbook with a
transactions view + summary by category + summary by month.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from parsers.liverpool import parse_liverpool
from parsers.banamex import parse_banamex
from parsers.invex import parse_invex
from parsers.nu import parse_nu
from categorize import categorize
import db
import validate

# NOTE: kept in Spanish because these are the literal month abbreviations
# printed on the statements themselves (used as dict keys for lookup).
SPANISH_MONTHS = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}


def detect_bank(pdf_path: str) -> str:
    """Detects the bank first by filename, then falls back to page content."""
    name = Path(pdf_path).stem.upper()
    if "LIVERPOOL" in name:
        return "liverpool"
    if "BANAMEX" in name or "CITIBANAMEX" in name:
        return "banamex"
    if "INVEX" in name or "VOLARIS" in name:
        return "invex"
    # match NU only as a delimited token, so filenames like "NUMERO..." don't
    # false-positive as Nu
    if "NU" in re.split(r"[-_ ]", name):
        return "nu"

    # fallback: scan all pages (the bank logo is usually an image, so we
    # look for the company name that appears as plain text on inner pages)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if "LIVERPOOL" in text.upper():
                    return "liverpool"
                if "BANAMEX" in text.upper():
                    return "banamex"
                if "INVEX" in text.upper() or "VOLARIS" in text.upper():
                    return "invex"
                if "NU MÉXICO FINANCIERA" in text.upper() or "NU MEXICO FINANCIERA" in text.upper():
                    return "nu"
            # last resort: if any page has Banamex's typical transaction
            # pattern (date date description +/- $amount), assume Banamex
            for page in pdf.pages:
                text = page.extract_text() or ""
                if any(re.match(
                    r"^\d{2}-\w{3}-\d{4}\s+\d{2}-\w{3}-\d{4}", line.strip(), re.IGNORECASE
                ) for line in text.split("\n")):
                    return "banamex"
    except Exception:
        pass
    return "unknown"


def liverpool_date_to_iso(date_str: str, year: int) -> str:
    day, mon = date_str.split("-")
    return f"{year:04d}-{SPANISH_MONTHS[mon]:02d}-{int(day):02d}"


def dashed_date_to_iso(date_str: str) -> str:
    # format "27-may-2026"
    day, mon, year = date_str.split("-")
    return f"{year}-{SPANISH_MONTHS[mon.upper()]:02d}-{int(day):02d}"


def guess_year_from_filename(pdf_path: str) -> int:
    # Only Liverpool needs this: its statement dates are "DD-MON" with no year
    # (the other banks' dates already carry YYYY). We take the 4-digit year from
    # the filename, falling back to the current year.
    # Note: a statement straddling a year boundary (Dec rows in a Jan
    # statement) will tag those rows with the statement's year. Include the
    # correct year in the filename to avoid it, or split by cut date if needed.
    fname = Path(pdf_path).stem.replace("_", "-")
    for token in fname.split("-"):
        if token.isdigit() and len(token) == 4:
            return int(token)
    return datetime.now().year


def build_rows(pdf_paths: list[str]) -> list[dict]:
    rows = []
    for pdf_path in pdf_paths:
        bank = detect_bank(pdf_path)
        fname = Path(pdf_path).stem
        ocr_text = None
        file_rows = []

        if bank == "liverpool":
            year = guess_year_from_filename(pdf_path)
            txns, _, ocr_text = parse_liverpool(pdf_path)
            for t in txns:
                cat = categorize(t["description"], t["amount"])
                file_rows.append({
                    "Bank": "Liverpool",
                    "File": fname,
                    "Date": liverpool_date_to_iso(t["date"], year),
                    "Description": t["description"],
                    "Category": cat,
                    "Amount": t["amount"],
                    "Type": t["type"],
                    "Review": "YES" if t["needs_review"] else "",
                })
        elif bank == "banamex":
            txns = parse_banamex(pdf_path)
            for t in txns:
                cat = categorize(t["description"], t["amount"])
                file_rows.append({
                    "Bank": "Banamex",
                    "File": fname,
                    "Date": dashed_date_to_iso(t["date"]),
                    "Description": t["description"],
                    "Category": cat,
                    "Amount": t["amount"],
                    "Type": t["type"],
                    "Review": "YES" if t.get("source") == "ocr_fallback" else "",
                })
        elif bank == "invex":
            txns = parse_invex(pdf_path)
            for t in txns:
                cat = categorize(t["description"], t["amount"])
                file_rows.append({
                    "Bank": "Invex Volaris",
                    "File": fname,
                    "Date": dashed_date_to_iso(t["date"]),
                    "Description": t["description"],
                    "Category": cat,
                    "Amount": t["amount"],
                    "Type": t["type"],
                    "Review": "YES" if t.get("is_installment") else "",
                    "is_installment": t.get("is_installment", False),
                })
        elif bank == "nu":
            txns = parse_nu(pdf_path)
            for t in txns:
                cat = categorize(t["description"], t["amount"])
                file_rows.append({
                    "Bank": "Nu",
                    "File": fname,
                    "Date": t["date"],
                    "Description": t["description"],
                    "Category": cat,
                    "Amount": t["amount"],
                    "Type": t["type"],
                    "Review": "",
                })
        else:
            print(f"⚠️  Could not identify the bank for: {pdf_path} (skipped)")
            continue

        for r in file_rows:
            r["Month"] = r["Date"][:7]  # YYYY-MM

        ok, messages = validate.validate_file(bank, file_rows, pdf_path, ocr_text)
        for m in messages:
            print(f"  {fname}: {m}")
        if ok:
            rows.extend(file_rows)
        else:
            print(f"⛔ {fname}: failed validation, not imported")

    return rows


def write_excel(df: pd.DataFrame, out_path: str):
    wb = Workbook()

    # --- Sheet 1: Transactions ---
    ws = wb.active
    ws.title = "Transactions"
    headers = list(df.columns)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF", name="Arial")
        cell.fill = PatternFill("solid", fgColor="4472C4")
        cell.alignment = Alignment(horizontal="center")

    for _, row in df.iterrows():
        ws.append(list(row))

    amount_col_idx = headers.index("Amount") + 1
    for i, col in enumerate(headers, start=1):
        letter = get_column_letter(i)
        max_len = max([len(str(col))] + [len(str(v)) for v in df[col]]) if len(df) else len(col)
        ws.column_dimensions[letter].width = min(max_len + 2, 45)
        if col == "Amount":
            for r in range(2, len(df) + 2):
                ws[f"{letter}{r}"].number_format = "$#,##0.00;($#,##0.00)"
    ws.freeze_panes = "A2"

    n = len(df) + 1
    category_col = get_column_letter(headers.index("Category") + 1)
    month_col = get_column_letter(headers.index("Month") + 1) if "Month" in headers else None
    amount_col = get_column_letter(amount_col_idx)

    # --- Sheet 2: Summary by category ---
    ws2 = wb.create_sheet("Summary by Category")
    ws2.append(["Category", "Total", "# Transactions"])
    for cell in ws2[1]:
        cell.font = Font(bold=True, color="FFFFFF", name="Arial")
        cell.fill = PatternFill("solid", fgColor="4472C4")

    categories = sorted(df["Category"].unique()) if len(df) else []
    for i, cat in enumerate(categories, start=2):
        ws2.cell(row=i, column=1, value=cat)
        ws2.cell(row=i, column=2,
                  value=f"=SUMIFS(Transactions!{amount_col}2:{amount_col}{n},Transactions!{category_col}2:{category_col}{n},A{i})")
        ws2.cell(row=i, column=2).number_format = "$#,##0.00"
        ws2.cell(row=i, column=3,
                  value=f"=COUNTIF(Transactions!{category_col}2:{category_col}{n},A{i})")
    ws2.column_dimensions["A"].width = 32
    ws2.column_dimensions["B"].width = 16
    ws2.column_dimensions["C"].width = 16

    # --- Sheet 3: Summary by month ---
    if month_col:
        ws3 = wb.create_sheet("Summary by Month")
        ws3.append(["Month", "Total Spent (charges)", "Total Paid (payments)"])
        for cell in ws3[1]:
            cell.font = Font(bold=True, color="FFFFFF", name="Arial")
            cell.fill = PatternFill("solid", fgColor="4472C4")
        months = sorted(df["Month"].unique()) if len(df) else []
        type_col = get_column_letter(headers.index("Type") + 1)
        for i, month in enumerate(months, start=2):
            ws3.cell(row=i, column=1, value=month)
            ws3.cell(row=i, column=2,
                      value=(f'=SUMIFS(Transactions!{amount_col}2:{amount_col}{n},'
                             f'Transactions!{month_col}2:{month_col}{n},A{i},'
                             f'Transactions!{type_col}2:{type_col}{n},"charge")'))
            ws3.cell(row=i, column=2).number_format = "$#,##0.00"
            ws3.cell(row=i, column=3,
                      value=(f'=SUMIFS(Transactions!{amount_col}2:{amount_col}{n},'
                             f'Transactions!{month_col}2:{month_col}{n},A{i},'
                             f'Transactions!{type_col}2:{type_col}{n},"payment")'))
            ws3.cell(row=i, column=3).number_format = "$#,##0.00"
        ws3.column_dimensions["A"].width = 14
        ws3.column_dimensions["B"].width = 22
        ws3.column_dimensions["C"].width = 22

    wb.save(out_path)


if __name__ == "__main__":
    pdf_paths = sys.argv[1:]
    if not pdf_paths:
        # no arguments: process everything in statements/
        folder = Path(__file__).parent / "statements"
        pdf_paths = [str(p) for p in sorted(folder.glob("*.pdf"))]
        if not pdf_paths:
            print(f"No PDFs found in {folder}/ and no file was passed as an argument.")
            print("Usage: python3 build_report.py [file1.pdf file2.pdf ...]")
            sys.exit(1)
        print(f"Processing {len(pdf_paths)} PDF(s) from {folder}/ ...")

    rows = build_rows(pdf_paths)
    conn = db.connect()
    db.init_db(conn)
    n_new = db.insert_transactions(conn, rows)
    df = db.fetch_dataframe(conn)

    out_dir = Path(__file__).parent / "reports"
    out_dir.mkdir(exist_ok=True)
    out = str(out_dir / "consolidated_expense_report.xlsx")
    write_excel(df, out)
    print(f"Imported {n_new} new of {len(rows)} parsed from {len(pdf_paths)} file(s).")
    print(f"Saved to {out}. DB now holds {len(df)} transactions total.")
    if len(df):
        print(df.groupby(["Bank", "Category"])["Amount"].sum().sort_values(ascending=False))
