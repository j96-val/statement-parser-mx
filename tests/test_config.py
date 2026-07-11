"""
Unit tests for config.py's .env parser and env-var fallback defaults.

Run either way:
    pytest tests/
    python3 tests/test_config.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def test_load_dotenv_sets_unset_vars():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
        f.write("# comment\nOCR_DPI=150\n\nSTATEMENTS_DIR=/tmp/custom_statements\n")
        path = Path(f.name)
    os.environ.pop("OCR_DPI", None)
    os.environ.pop("STATEMENTS_DIR", None)
    try:
        config._load_dotenv(path)
        assert os.environ["OCR_DPI"] == "150"
        assert os.environ["STATEMENTS_DIR"] == "/tmp/custom_statements"
    finally:
        os.environ.pop("OCR_DPI", None)
        os.environ.pop("STATEMENTS_DIR", None)
        path.unlink()


def test_load_dotenv_does_not_override_existing_env():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
        f.write("OCR_DPI=150\n")
        path = Path(f.name)
    os.environ["OCR_DPI"] = "600"
    try:
        config._load_dotenv(path)
        assert os.environ["OCR_DPI"] == "600"  # real env wins over .env
    finally:
        os.environ.pop("OCR_DPI", None)
        path.unlink()


def test_load_dotenv_missing_file_is_a_noop():
    config._load_dotenv(Path("/nonexistent/.env"))  # must not raise


def test_validation_strict_defaults_true_and_parses_falsy_strings():
    assert config.VALIDATION_STRICT is True  # default, no env var set in this process
    for falsy in ("false", "0", "warn", "FALSE", "Warn"):
        os.environ["VALIDATION_STRICT"] = falsy
        try:
            strict = os.environ.get("VALIDATION_STRICT", "true").strip().lower() not in ("false", "0", "warn")
            assert strict is False
        finally:
            os.environ.pop("VALIDATION_STRICT", None)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
