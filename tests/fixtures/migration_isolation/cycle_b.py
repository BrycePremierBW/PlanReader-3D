"""Cycle member B imports A and a forbidden gold module."""

from tests.fixtures.migration_isolation import cycle_a  # noqa: F401
import pb_public_tender_benchmark as _gold

LEAK = getattr(_gold, "__name__", "pb_public_tender_benchmark")
