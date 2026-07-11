"""
Phase 4.2 derived-column helpers: no parser changes, computed purely from
already-extracted date/description at report-build time (build_report.py).
"""
import re
from datetime import datetime

# Known payment-gateway/processor prefixes that obscure the real merchant
# name, so the same merchant groups together across variants (e.g.
# "MERPAGO*STARBUCKS COYOACAN" and "STARBUCKS SANTA FE" both -> STARBUCKS...).
# Extend this list as new prefixes turn up on statements.
MERCHANT_PREFIX_RE = re.compile(
    r"^(MERPAGO\*|MERPAG0\*|PAYPAL \*|MERCADOPAGO\*|DLO\*)\s*",
    re.IGNORECASE,
)


def normalize_merchant(description: str) -> str:
    """Strips known payment-gateway prefixes and normalizes whitespace/case."""
    cleaned = MERCHANT_PREFIX_RE.sub("", description.strip())
    return re.sub(r"\s+", " ", cleaned).upper()


def day_of_week_info(iso_date: str) -> tuple[str, bool]:
    """Returns (day name, is_weekend) for an ISO YYYY-MM-DD date string."""
    d = datetime.fromisoformat(iso_date)
    return d.strftime("%A"), d.weekday() >= 5
