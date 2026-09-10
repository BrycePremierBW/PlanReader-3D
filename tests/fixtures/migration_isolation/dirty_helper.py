"""Helper that pulls a forbidden benchmark module. Parsed, not executed, by isolation tests."""

import pb_benchmark_accuracy_engine as _forbidden_gold_loader

LEAK = getattr(_forbidden_gold_loader, "__name__", "pb_benchmark_accuracy_engine")
