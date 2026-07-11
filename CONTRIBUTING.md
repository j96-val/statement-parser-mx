# Contributing

## Setup

See the [README](README.md#installation) for install instructions
(Tesseract + poppler are required for OCR-based parsers).

Run tests before and after your change:

```bash
python3 tests/test_parsers.py   # or: pytest tests/
```

## Adding a new bank

Each parser is a standalone module: `parsers/<bank>.py` exposing
`parse_<bank>(pdf_path)` -> list of `Transaction` dicts (`date`,
`description`, `amount`, `type` - see `parsers/base.py`). Amount sign
convention: **positive = charge, negative = payment/refund** - get this
backwards and every downstream category/summary breaks.

1. **Figure out the extraction method.** Open the PDF and try
   `pdfplumber`'s text extraction first (`page.extract_text()`). If it
   comes back garbled or empty, the bank embeds a broken/custom font and
   you need OCR instead (`pytesseract` + `pdf2image` - see
   `parsers/liverpool.py` for the pattern). Banamex is a hybrid: direct
   text plus an OCR fallback pass for bold rows the text layer skips - see
   `parsers/banamex.py` if your bank does something similar.

2. **Write `parsers/newbank.py`.** Return a plain list of `Transaction`
   dicts (not a tuple) unless you have a real reason not to - Liverpool is
   the one exception (`(txns, review_reasons, ocr_text)`, needed for its
   own validation path). Dates stay in the bank's native format here -
   don't convert to ISO in the parser, that's `build_report.py`'s job (see
   step 3).

3. **Wire it into `build_report.py`.**
   - `detect_bank()`: add a filename check and a page-content fallback
     (bank logos are usually images, so match the company name printed on
     an inner page instead).
   - If your bank's PDF never prints a cut-off date anywhere (OCR-only
     banks are the likely case), require it in the filename instead - see
     Liverpool's `BANK-YYYY-MM-DD.pdf` convention in `README.md` and
     `guess_year_from_filename()` in `build_report.py`. Statement-level
     tracking (duplicate/continuity checks) needs a cut-off date from
     somewhere.
   - `build_dataframe()`: add a branch for your bank. Convert dates to ISO
     here (add a converter if your date format isn't already handled) and
     decide which parser key maps to the `Review` flag - see Liverpool's
     `needs_review`, Banamex's `source == "ocr_fallback"`, Invex's
     `is_installment` for precedent (Nu never flags).

4. **Validate against a real statement - this is the step that matters.**
   Run your parser against an actual PDF and reconcile: sum the charges
   and payments you extracted and compare against the total the statement
   itself prints. This is how every real bug so far was caught (OCR digit
   loss, dropped bold rows, MSI installments landing in the wrong month) -
   unit tests alone won't catch it, they only run against synthetic
   strings. If the bank prints a reliable total line, wire it into
   `validate.py`'s `extract_printed_totals()` so this check runs
   automatically on every future import, not just once by hand.

5. **Add a fixture, so CI catches regressions without your real PDFs.**
   Real statements never go in the repo (`statements/` is gitignored -
   personal financial data). Instead:
   - Add a `FIXTURES["newbank"]` entry to `tests/fixtures.py`: fake data,
     same structural shape (section headers, column layout, any OCR quirks
     that matter) as a real statement, plus the expected row count and
     totals.
   - Add a `test_newbank_fixture_parses_and_reconciles()` to
     `tests/test_fixtures.py`, following the Nu/Invex tests as a template:
     generate the fixture PDF, run your parser, assert the row count and
     totals, then run it through `validate.validate_file()` and assert it
     passes.
   - If your parser needs OCR, a fixture isn't practical in CI yet (no
     tesseract there) - that's the situation Liverpool and Banamex are in
     today; their text->rows logic is covered by `tests/test_parsers.py`
     instead. Note why in a comment, same as `tests/fixtures.py` does for
     those two.

6. **Keep Spanish text in Spanish.** Section markers, `MONTHS` dicts, and
   `categorize.py`'s keyword lists match the literal text printed on
   Mexican statements - don't translate them, including deliberate
   OCR-misread variants if you find one (see `OXX0` in `categorize.py` for
   an example).

## Out of scope

Web UI, authentication, Docker, multi-tenancy, hosted/SaaS mode. This is a
local CLI tool by design - hosting other people's bank statements means
becoming a custodian of sensitive financial data, which isn't a tradeoff
this project takes on.
