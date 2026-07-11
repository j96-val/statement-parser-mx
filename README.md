# statement-parser-mx

Reads your Mexican credit card statements in PDF (Liverpool, Banamex, Invex
Volaris, Nu), extracts the transactions, categorizes them, and generates a
consolidated Excel report with a summary by category and by month.

## Installation

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install Tesseract OCR (needed for Liverpool, whose PDF doesn't expose text)
#    macOS:
brew install tesseract poppler
#    Ubuntu/Debian:
sudo apt install tesseract-ocr poppler-utils
#    Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
#             and poppler from https://github.com/oschwartz10612/poppler-windows
```

## Usage

1. Drop your PDFs into `statements/`
2. Run:

```bash
python3 build_report.py
```

3. The Excel file lands in `reports/consolidated_expense_report.xlsx`

You can also pass specific files as arguments:

```bash
python3 build_report.py path/to/one_statement.pdf path/to/another.pdf
```

The bank for each PDF is auto-detected (by filename or content) — you can
freely mix banks and months in the same run.

## Tests

Unit tests cover the parsing logic (regexes, amount/date handling,
categorization) with synthetic strings — no PDFs required:

```bash
python3 tests/test_parsers.py    # runs with only the requirements.txt deps
# or, if you have pytest:
pytest tests/
```

These catch logic regressions. They do **not** replace **totals
reconciliation** against a real statement, which is the only way to catch
OCR/extraction errors — see "Adding a new bank" below.

## Structure

```
statement-parser-mx/
├── parsers/             # one module per bank: PDF -> list of transactions
│   ├── liverpool.py      # needs OCR (the PDF's font encoding is broken)
│   ├── banamex.py        # direct text + OCR fallback for bold rows
│   ├── invex.py          # direct text, handles MSI (interest-free installments)
│   └── nu.py             # direct text, the simplest of the four
├── categorize.py         # keyword-based categorization rules
├── build_report.py       # master pipeline: detects bank, runs everything, builds the Excel
├── statements/           # (gitignored) your PDFs go here
└── reports/              # (gitignored) generated Excel files land here
```

## Adding a new bank

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full checklist (parser
shape, wiring, totals validation, and the fixture required for CI).

## Categories

Editable in `categorize.py`, matched by keywords found in each
transaction's description. Card payments and merchant refunds are
automatically separated from real spending categories.

Note: the keyword lists in `categorize.py` and the section markers inside
each parser are intentionally left in Spanish, since they need to match
the literal Spanish text printed on Mexican bank statements.

## Configuration

Optional. Copy `.env.example` to `.env` and adjust — every setting has a
default that matches prior hardcoded behavior, so this is only needed to
customize:

- `STATEMENTS_DIR` / `REPORTS_DIR` — input/output folder paths.
- `OCR_DPI` — resolution used to render PDF pages before OCR (Liverpool,
  Banamex's fallback pass).
- `VALIDATION_STRICT` — `true` (default) blocks import on a totals
  mismatch; `false`/`warn` prints the same warning but always imports.

## Privacy notes

Statement PDFs and generated Excel files contain personal financial
information — `.gitignore` excludes them from the repository. The code
itself is safe to share; your statements are not.

## Disclaimer

Esta herramienta no es asesoría financiera, contable ni fiscal. Los montos
se extraen de tus PDFs mediante parsing y OCR automatizados, procesos que
pueden producir errores. Eres responsable de verificar los datos extraídos
contra el estado de cuenta original antes de usarlos para cualquier
decisión. Software provisto "tal cual", sin garantía — ver [LICENSE](LICENSE).
