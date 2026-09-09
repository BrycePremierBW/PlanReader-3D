"""Relative helper that imports gold."""

import pb_public_tender_benchmark as _gold

LEAK = getattr(_gold, "__name__", "pb_public_tender_benchmark")
