"""
Runtime config: statements/reports paths, OCR DPI, validation strictness.
All overridable via env vars or a `.env` file in the repo root (see
`.env.example`) - falls back to today's hardcoded defaults if neither is set.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

STATEMENTS_DIR = Path(os.environ.get("STATEMENTS_DIR", ROOT / "statements"))
REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", ROOT / "reports"))
OCR_DPI = int(os.environ.get("OCR_DPI", 300))
# strict (default): a totals/reconciliation mismatch blocks import (❌).
# warn-only: same checks run and print, but never block import (⚠️).
VALIDATION_STRICT = os.environ.get("VALIDATION_STRICT", "true").strip().lower() not in ("false", "0", "warn")
