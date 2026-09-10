"""Fail CI when benchmark-defining files and production code change together.

Development benchmarks may need legitimate administrative corrections, but those
corrections must be reviewed independently from extractor/evaluation changes. A
single PR must not be able to observe a score outcome, change production logic,
and then alter benchmark-defining metadata to sanitize that outcome.

The guard deliberately allows tests, documentation, download/provenance metadata,
and generated benchmark outputs to accompany a benchmark maintenance change. It
also allows production-only changes. It rejects only the risky mixed class:
benchmark-defining assets + production code in one change set.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import sys
from typing import Iterable, Sequence


_BENCHMARK_ROOTS = (
    "benchmarks/public_tenders/",
    "benchmarks/plans/",
)
_BENCHMARK_DEFINING_FILENAMES = {
    "source_manifest.json",
    "benchmark_rules.json",
    "tolerances.json",
    "manifest.json",
}
_PRODUCTION_SUFFIXES = {".py", ".js", ".html"}
_PRODUCTION_EXCLUDED_PREFIXES = (
    "tests/",
    "benchmarks/",
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_benchmark_defining_file(path: str) -> bool:
    normalized = _normalize(path)
    if not normalized.startswith(_BENCHMARK_ROOTS):
        return False
    name = PurePosixPath(normalized).name
    if name.startswith("expected_") and name.endswith(".json"):
        return True
    return name in _BENCHMARK_DEFINING_FILENAMES


def is_production_code_file(path: str) -> bool:
    normalized = _normalize(path)
    if normalized.startswith(_PRODUCTION_EXCLUDED_PREFIXES):
        return False
    return PurePosixPath(normalized).suffix.lower() in _PRODUCTION_SUFFIXES


def find_separation_violation(changed_paths: Sequence[str]) -> tuple[list[str], list[str]]:
    benchmark_files = sorted({p for p in changed_paths if is_benchmark_defining_file(p)})
    production_files = sorted({p for p in changed_paths if is_production_code_file(p)})
    if benchmark_files and production_files:
        return benchmark_files, production_files
    return [], []


def check_paths(changed_paths: Sequence[str]) -> None:
    benchmark_files, production_files = find_separation_violation(changed_paths)
    if not benchmark_files:
        return

    details = [
        "Benchmark-integrity separation gate failed.",
        "Benchmark-defining files and production code must be changed in separate PRs.",
        "This prevents post-score benchmark/gold edits from being bundled with extractor or evaluation changes.",
        "",
        "Benchmark-defining files:",
        *[f"  - {p}" for p in benchmark_files],
        "",
        "Production-code files:",
        *[f"  - {p}" for p in production_files],
        "",
        "Split this into (1) an independently evidenced benchmark-maintenance PR and (2) a production-code PR.",
    ]
    raise SystemExit("\n".join(details))


def _stdin_paths(lines: Iterable[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def main() -> int:
    changed_paths = _stdin_paths(sys.stdin)
    try:
        check_paths(changed_paths)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Benchmark-integrity separation gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
