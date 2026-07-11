"""
Synthetic PDF fixtures for the text-only parsers (Nu, Invex) - fake data, real
row/section shape, so the real parsers + validate.py's reconciliation regexes
run end to end in CI with no real statement data.

Liverpool and Banamex are NOT covered here: Liverpool is OCR-only and
Banamex's parser always runs an OCR fallback pass (needs tesseract + poppler),
so a fixture for either would need OCR in CI. Their pure text->rows logic is
already covered by tests/test_parsers.py.

Requires reportlab (dev-only, see requirements-dev.txt).
"""
FIXTURES = {
    "nu": {
        "lines": [
            "NU MEXICO FINANCIERA ESTADO DE CUENTA",
            "CARGOS, ABONOS Y COMPRAS REGULARES",
            "05 MAY 2026 05 MAY 2026 NETFLIX MEXICO | RFC: NET123456AB1 +$199.00",
            "20 MAY 2026 20 MAY 2026 PAGO RECIBIDO GRACIAS | RFC: NUM180626DQ0 -$1000.00",
            "Cargos regulares (no a meses) + $199.00",
            "Pagos y abonos - $1,000.00",
        ],
        "expected_rows": 2,
        "expected_charges": 199.00,
        "expected_payments": -1000.00,
    },
    "invex": {
        "lines": [
            "INVEX VOLARIS ESTADO DE CUENTA",
            "Fecha de corte: 25-may-2026",
            "DESGLOSE DE MOVIMIENTOS",
            "10-may-2026 10-may-2026 UBER EATS MEXICO + $95.50",
            "20-may-2026 20-may-2026 PAGO TARJETA - $500.00",
            "15-may-2026 LAPTOP DELL MSI $12,000.00 $10,000.00 $1,000.00 2 de 12 1.5%",
            "Total cargos + $95.50",
            "Total abonos - $500.00",
        ],
        "expected_rows": 3,
        "expected_charges": 95.50,
        "expected_payments": -500.00,
    },
}


def make_pdf(bank: str, path: str) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path)
    c.setFont("Courier", 10)
    y = 750
    for line in FIXTURES[bank]["lines"]:
        c.drawString(50, y, line)
        y -= 14
    c.save()
