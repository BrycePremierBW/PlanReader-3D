"""Shared Tesseract/pytesseract availability probe for OCR-dependent tests.

A handful of mutation tests exercise real OCR recovery end-to-end rather
than mocking it, so they need an actual usable Tesseract backend (the
`pytesseract` package AND the `tesseract` binary on PATH) to produce a
meaningful result. Neither is installed in CI. This module runs one real,
trivial OCR call once at import time and exposes the result so those tests
can skip themselves rather than fail on an environment gap that has nothing
to do with the code under test.
"""
from __future__ import annotations


def _probe_ocr_backend() -> bool:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return False
    try:
        pytesseract.image_to_data(
            Image.new("RGB", (10, 10), "white"), output_type=pytesseract.Output.DICT
        )
    except Exception:
        return False
    return True


OCR_AVAILABLE = _probe_ocr_backend()
