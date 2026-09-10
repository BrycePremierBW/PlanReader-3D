"""Runtime isolation for production-provider extract.

Layer 1 — static AST closure (``pb_provider_gold_isolation``)
    Necessary.  Catches the import shapes we test.  Not mathematically complete.

Layer 2 — staged resource-absent workspace (this module)
    Copy production modules + the supplied source PDF into a mini workspace.
    Do not copy ``benchmarks/``, gold, mappings, ``benchmark_results/``,
    holdout, ``shadow_reports/``, ``pb_shadow_opening_count_eval.py``, or
    evaluator code.  Run the registered provider with ``cwd=stage`` and
    ``PYTHONPATH=stage`` only.  Gold paths *relative to the staged repo*
    fail with ``FileNotFoundError`` / ``ENOENT`` because the files are not
    there — not because a Python hook intercepted them.

Layer 3 — optional Python hooks (insufficient alone)
    Meta-path finder + ``builtins.open`` / ``Path`` wrappers.  A C extension,
    ``os.open``, ``io.open`` (when not routed through the wrapped builtin in
    every interpreter), or native I/O can bypass them.  Kept as defense in
    depth only.  Hooks are NOT the acceptance mechanism.

Limits (honest):

* This is not an OS chroot, container, or seccomp sandbox.
* Absolute paths into the original developer checkout are outside the
  isolation boundary.  A process that opens
  ``/original/checkout/benchmarks/.../expected_boq_summary.json`` can still
  succeed if that file exists on the real filesystem.
* PyMuPDF reads the source PDF via its own I/O; the staged PDF is a
  legitimate source input, not gold.
* Variable-dynamic imports are denied by the walker only for literal names.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
import builtins
import json
import os
from pathlib import Path
import shutil
import subprocess
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

FORBIDDEN_STAGE_PREFIXES = (
    "benchmarks/",
    "tests/benchmarks/",
    "benchmark_results/",
    "shadow_reports/",
)

FORBIDDEN_STAGE_FILENAMES = frozenset(
    {
        "pb_shadow_opening_count_eval.py",
        "expected_boq_summary.json",
        "expected_project.json",
        "item_mappings.json",
        "benchmark_rules.json",
        "expected_quantities.json",
    }
)

FORBIDDEN_LISTING_TOKENS = (
    "expected_boq",
    "expected_project",
    "item_mappings",
    "benchmark_rules",
    "holdout_suite",
    "sealed_holdout",
    "pb_shadow_opening_count_eval",
    "benchmark_results",
    "shadow_reports",
)

# Paths a reviewer / escape test must try relative to the staged repo.
ESCAPE_GOLD_RELATIVE_PATHS = (
    "benchmarks/public_tenders/tenders_ke_kstvet_cbc_classroom/expected_boq_summary.json",
    "pb_shadow_opening_count_eval.py",
    "benchmark_results/headline_accuracy_dashboard.json",
    "shadow_reports/opening_count_shadow_development.json",
)

STAGED_EXTRACT_RUNNER_NAME = "run_staged_opening_count_extract.py"

DEFAULT_STAGED_PROVIDER_MODULES = (
    "pb_opening_count_control_adapter",
    "pb_shadow_opening_count_provider",
)

_STAGED_EXTRACT_RUNNER = '''#!/usr/bin/env python3
"""Extract opening counts inside a staged production-only workspace."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
cleaned: list[str] = [str(ROOT)]
for entry in sys.path:
    if not entry:
        continue
    candidate = Path(entry)
    try:
        resolved = candidate.resolve()
    except OSError:
        cleaned.append(entry)
        continue
    if resolved == ROOT.resolve():
        continue
    if (resolved / "benchmarks" / "public_tenders").is_dir():
        continue
    cleaned.append(entry)
sys.path[:] = cleaned

from pb_opening_count_control_adapter import OpeningCountControlAdapter


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: run_staged_opening_count_extract.py PDF OUT.json", file=sys.stderr)
        return 2
    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2])
    quantities = OpeningCountControlAdapter().extract_quantities(pdf, pages=[0])
    out.write_text(json.dumps([item.to_dict() for item in quantities], sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


class GoldResourceDenied(RuntimeError):
    """Raised when isolated execution touches a forbidden gold/eval resource."""


class ProviderWorkspaceStagingError(RuntimeError):
    """Raised when a production workspace would include gold/eval resources."""


def _module_forbidden(name: str) -> bool:
    lowered = str(name or "").strip()
    return any(lowered == prefix or lowered.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES)


def _path_forbidden(path: object) -> bool:
    text = str(path).replace("\\", "/").lower()
    return any(token.lower() in text for token in FORBIDDEN_PATH_TOKENS)


def _relative_forbidden_to_stage(relative: Path) -> Optional[str]:
    posix = relative.as_posix().replace("\\", "/")
    lowered = posix.lower()
    for prefix in FORBIDDEN_STAGE_PREFIXES:
        if lowered.startswith(prefix) or f"/{prefix}" in f"/{lowered}":
            return f"forbidden staged prefix {prefix}"
    name = relative.name.lower()
    if name in {item.lower() for item in FORBIDDEN_STAGE_FILENAMES}:
        return f"forbidden staged filename {relative.name}"
    for token in FORBIDDEN_LISTING_TOKENS:
        if token.lower() in lowered:
            return f"forbidden staged token {token!r}"
    return None


class GoldDenialFinder(MetaPathFinder):
    def find_spec(self, fullname: str, path: Optional[Sequence[str]] = None, target=None) -> Optional[ModuleSpec]:
        if _module_forbidden(fullname):
            raise GoldResourceDenied(f"isolated execution denied import of {fullname}")
        return None


def install_runtime_gold_denial() -> None:
    """Install insufficient-but-useful Python-layer denials.

    Do not treat this as gold unavailability.  Use
    ``stage_production_provider_workspace`` for resource-absent isolation.
    """
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


@dataclass(frozen=True)
class StagedProviderWorkspace:
    root: Path
    source_pdf: Path
    copied_relative_files: tuple[str, ...]
    extract_runner: Path
    provider_modules: tuple[str, ...]

    def listed_relative_files(self) -> tuple[str, ...]:
        files = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                files.append(path.relative_to(self.root).as_posix())
        return tuple(files)


def stage_production_provider_workspace(
    dest: Path | str,
    source_pdf: Path | str,
    *,
    provider_modules: Sequence[str] = DEFAULT_STAGED_PROVIDER_MODULES,
    repo_root: Optional[Path] = None,
) -> StagedProviderWorkspace:
    """Copy production provider modules + the source PDF into ``dest``.

    Gold, mappings, holdout, benchmark results, evaluator modules, and
    ``shadow_reports/`` are refused.  The staged tree is the isolation
    boundary for *relative* paths only.
    """
    from pb_provider_gold_isolation import REPO_ROOT, local_module_source_files

    dest_root = Path(dest).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    repo = (repo_root or REPO_ROOT).resolve()
    pdf = Path(source_pdf).resolve()
    if not pdf.is_file():
        raise ProviderWorkspaceStagingError(f"source PDF is not a file: {pdf}")

    copied: list[str] = []
    seen: set[Path] = set()
    for module in provider_modules:
        for src in local_module_source_files(module):
            resolved = src.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                relative = resolved.relative_to(repo)
            except ValueError as exc:
                raise ProviderWorkspaceStagingError(
                    f"refusing to stage file outside the repository: {resolved}"
                ) from exc
            reason = _relative_forbidden_to_stage(relative)
            if reason:
                raise ProviderWorkspaceStagingError(
                    f"refusing to stage {relative.as_posix()}: {reason}"
                )
            target = dest_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, target)
            copied.append(relative.as_posix())

    staged_pdf = dest_root / "source.pdf"
    shutil.copy2(pdf, staged_pdf)
    runner = dest_root / STAGED_EXTRACT_RUNNER_NAME
    runner.write_text(_STAGED_EXTRACT_RUNNER, encoding="utf-8")
    manifest = {
        "isolation": "resource_absent_staged_workspace",
        "not_a_chroot": True,
        "developer_absolute_paths_out_of_scope": True,
        "provider_modules": list(provider_modules),
        "copied_files": copied,
        "source_pdf": "source.pdf",
        "extract_runner": STAGED_EXTRACT_RUNNER_NAME,
    }
    (dest_root / "stage_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return StagedProviderWorkspace(
        root=dest_root,
        source_pdf=staged_pdf,
        copied_relative_files=tuple(copied),
        extract_runner=runner,
        provider_modules=tuple(provider_modules),
    )


def assert_staged_workspace_has_no_gold_resources(workspace: StagedProviderWorkspace) -> None:
    listing = "\n".join(workspace.listed_relative_files())
    lowered = listing.lower()
    for token in FORBIDDEN_LISTING_TOKENS:
        if token.lower() in lowered:
            raise ProviderWorkspaceStagingError(
                f"staged workspace listing contains forbidden token {token!r}"
            )
    if (workspace.root / "benchmarks").exists():
        raise ProviderWorkspaceStagingError("staged workspace must not contain benchmarks/")
    for relative in ESCAPE_GOLD_RELATIVE_PATHS:
        if (workspace.root / relative).exists():
            raise ProviderWorkspaceStagingError(
                f"staged workspace unexpectedly contains {relative}"
            )


def run_staged_provider_extract(
    workspace: StagedProviderWorkspace,
    output_path: Path | str,
    *,
    python: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run the registered adapter with cwd/PYTHONPATH equal to the staged root."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace.root)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            python or sys.executable,
            str(workspace.extract_runner),
            str(workspace.source_pdf),
            str(output),
        ],
        cwd=str(workspace.root),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
