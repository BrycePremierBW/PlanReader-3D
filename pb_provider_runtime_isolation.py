"""Runtime denial of benchmark/gold/evaluation resources during provider extract.

Static AST closure analysis is necessary but not mathematically complete: it
cannot see ``importlib.import_module(variable)``, ``exec``, or C-level I/O.

This module adds a second layer for isolated execution:

* meta-path import finder that denies forbidden modules
* wrappers for builtins.open / Path.read_text / Path.read_bytes / Path.open
  that deny gold/benchmark/holdout/eval paths

Limits (honest):

* Not an OS sandbox. A C extension can open files without Python hooks.
* PyMuPDF reads the source PDF via its own I/O; that is allowed because the
  PDF is a legitimate source input, not gold.
* Variable-dynamic imports are denied only when the resolved module name is
  forbidden at import time.
* This does not prove every future helper is gold-free; it proves the
  registered opening-count extract can run with gold paths comprehensively
  denied at the Python layer.
"""
from __future__ import annotations

from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
import builtins
from pathlib import Path
import sys
from typing import Optional, Sequence


FORBIDDEN_MODULE_PREFIXES = (
    "pb_benchmark_accuracy_engine",
    "pb_public_tender_benchmark",
    "pb_benchmark_runner",
    "pb_benchmark_report_set",
    "_pb_benchmark_report_set_impl",
    "pb_holdout_suite_registry",
    "pb_shadow_opening_count_eval",
    "pb_takeoff_learning_ledger",
    "pb_accuracy_benchmark_v130",
    "benchmark_fixtures",
    "benchmarks",
)

FORBIDDEN_PATH_TOKENS = (
    "expected_boq",
    "expected_project",
    "benchmark_rules",
    "item_mappings",
    "holdout_suite",
    "sealed_holdout",
    "expected_quantities",
    "pb_shadow_opening_count_eval",
    "pb_public_tender_benchmark",
    "pb_benchmark_accuracy_engine",
    "/benchmarks/",
    "\\benchmarks\\",
    "tests/benchmarks/",
)


class GoldResourceDenied(RuntimeError):
    """Raised when isolated execution touches a forbidden gold/eval resource."""


def _module_forbidden(name: str) -> bool:
    lowered = str(name or "").strip()
    return any(lowered == prefix or lowered.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES)


def _path_forbidden(path: object) -> bool:
    text = str(path).replace("\\", "/").lower()
    return any(token.lower() in text for token in FORBIDDEN_PATH_TOKENS)


class GoldDenialFinder(MetaPathFinder):
    def find_spec(self, fullname: str, path: Optional[Sequence[str]] = None, target=None) -> Optional[ModuleSpec]:
        if _module_forbidden(fullname):
            raise GoldResourceDenied(f"isolated execution denied import of {fullname}")
        return None


def install_runtime_gold_denial() -> None:
    if any(isinstance(item, GoldDenialFinder) for item in sys.meta_path):
        finder_installed = True
    else:
        sys.meta_path.insert(0, GoldDenialFinder())
        finder_installed = True
    if getattr(builtins.open, "_planreader_gold_denied", False):
        return

    original_open = builtins.open
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes
    original_path_open = Path.open

    def guarded_open(file, *args, **kwargs):
        if _path_forbidden(file):
            raise GoldResourceDenied(f"isolated execution denied file open: {file}")
        return original_open(file, *args, **kwargs)

    def guarded_read_text(self, *args, **kwargs):
        if _path_forbidden(self):
            raise GoldResourceDenied(f"isolated execution denied Path.read_text: {self}")
        return original_read_text(self, *args, **kwargs)

    def guarded_read_bytes(self, *args, **kwargs):
        if _path_forbidden(self):
            raise GoldResourceDenied(f"isolated execution denied Path.read_bytes: {self}")
        return original_read_bytes(self, *args, **kwargs)

    def guarded_path_open(self, *args, **kwargs):
        if _path_forbidden(self):
            raise GoldResourceDenied(f"isolated execution denied Path.open: {self}")
        return original_path_open(self, *args, **kwargs)

    guarded_open._planreader_gold_denied = True  # type: ignore[attr-defined]
    builtins.open = guarded_open
    Path.read_text = guarded_read_text  # type: ignore[method-assign]
    Path.read_bytes = guarded_read_bytes  # type: ignore[method-assign]
    Path.open = guarded_path_open  # type: ignore[method-assign]
    _ = finder_installed
