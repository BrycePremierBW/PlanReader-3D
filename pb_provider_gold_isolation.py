"""Transitive gold-isolation integrity for registered production providers.

M3 itself is gold-free.  This module inspects the *transitive local import
closure* of a registered provider so a helper cannot quietly pull in
benchmark, gold, mapping, scoring, or holdout modules.

Inspection is deterministic AST / import-graph analysis.  It does not execute
provider code and does not load expected quantities.

Static AST analysis is necessary and catches the import shapes we test, but it
is NOT mathematically complete runtime isolation.  It cannot see
``importlib.import_module(variable)``, ``exec``/``eval``, or C-level I/O.
Pair this checker with ``pb_provider_runtime_isolation``.
"""
from __future__ import annotations

from dataclasses import dataclass
import ast
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent

FORBIDDEN_MODULES = frozenset(
    {
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
    }
)

FORBIDDEN_NAME_FRAGMENTS = frozenset(
    {
        "expected_boq",
        "expected_project",
        "benchmark_rules",
        "item_mappings",
        "holdout_suite",
        "sealed_holdout",
        "expected_quantities",
        "scoring_tolerance",
        "scoring_rules",
    }
)

FORBIDDEN_PATH_PREFIXES = (
    "benchmarks/",
    "tests/benchmarks/",
)

# Production providers that must stay gold-free at runtime.
REGISTERED_PRODUCTION_PROVIDERS = {
    "shadow_opening_count": "pb_shadow_opening_count_provider",
    "opening_count_control_adapter": "pb_opening_count_control_adapter",
}

_ISOLATION_CACHE: dict[str, ProviderIsolationReport] = {}


class ProviderGoldIsolationError(RuntimeError):
    """Raised when a registered provider's import graph reaches gold/eval code."""


@dataclass(frozen=True)
class ImportGraphFinding:
    module: str
    via: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ProviderIsolationReport:
    provider_id: str
    root_module: str
    visited: tuple[str, ...]
    findings: tuple[ImportGraphFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


def _module_path(module_name: str) -> Optional[Path]:
    if module_name.startswith("pb_"):
        candidate = REPO_ROOT / f"{module_name}.py"
        if candidate.is_file():
            return candidate
    parts = module_name.split(".")
    file_candidate = REPO_ROOT.joinpath(*parts).with_suffix(".py")
    if file_candidate.is_file():
        return file_candidate
    package_candidate = REPO_ROOT.joinpath(*parts) / "__init__.py"
    if package_candidate.is_file():
        return package_candidate
    return None


def _is_local_module(module_name: str) -> bool:
    return _module_path(module_name) is not None


def _forbidden_reason(module_name: str) -> Optional[str]:
    if module_name in FORBIDDEN_MODULES:
        return f"forbidden module {module_name}"
    lowered = module_name.lower()
    if lowered.startswith("benchmarks.") or lowered == "benchmarks":
        return f"forbidden benchmark package {module_name}"
    for fragment in FORBIDDEN_NAME_FRAGMENTS:
        if fragment in lowered:
            return f"forbidden name fragment {fragment!r} in {module_name}"
    return None


def _forbidden_path_reason(path: Path) -> Optional[str]:
    try:
        relative = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return None
    posix = relative.as_posix().lower()
    for prefix in FORBIDDEN_PATH_PREFIXES:
        if posix.startswith(prefix):
            return f"forbidden path {posix}"
    name = path.name.lower()
    for fragment in FORBIDDEN_NAME_FRAGMENTS:
        if fragment in name:
            return f"forbidden filename {path.name}"
    return None


def _imported_names(source: str, *, current_module: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names if alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and current_module:
                base_parts = current_module.split(".")
                if node.level > len(base_parts):
                    parent = ""
                else:
                    parent = ".".join(base_parts[: -node.level] if node.level else base_parts)
                imported = ".".join(part for part in (parent, node.module or "") if part)
            else:
                imported = node.module or ""
            if imported:
                names.append(imported)
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        names.append(f"{imported}.{alias.name}")
            elif node.names:
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        names.append(alias.name)
        elif isinstance(node, ast.Call):
            func = node.func
            is_dynamic = (
                (isinstance(func, ast.Name) and func.id in {"__import__", "import_module"})
                or (isinstance(func, ast.Attribute) and func.attr in {"import_module", "__import__"})
            )
            if is_dynamic and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.append(arg.value)
    return tuple(dict.fromkeys(names))


def walk_local_import_graph(root_module: str) -> tuple[tuple[str, ...], tuple[ImportGraphFinding, ...]]:
    """Return (visited modules, forbidden findings) for one local root."""
    visited: list[str] = []
    findings: list[ImportGraphFinding] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(root_module, (root_module,))]
    seen: set[str] = set()

    while stack:
        module, via = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        visited.append(module)
        reason = _forbidden_reason(module)
        if reason:
            findings.append(ImportGraphFinding(module=module, via=via, reason=reason))
            continue
        path = _module_path(module)
        if path is None:
            continue
        path_reason = _forbidden_path_reason(path)
        if path_reason:
            findings.append(ImportGraphFinding(module=module, via=via, reason=path_reason))
            continue
        imported = _imported_names(path.read_text(encoding="utf-8"), current_module=module)
        for name in imported:
            forbidden = _forbidden_reason(name)
            if forbidden:
                findings.append(ImportGraphFinding(module=name, via=via + (name,), reason=forbidden))
                continue
            if _is_local_module(name):
                stack.append((name, via + (name,)))
    return tuple(visited), tuple(findings)


def local_module_source_files(root_module: str) -> tuple[Path, ...]:
    """Return repository source files in a local import closure, plus package inits.

    Raises if the closure reaches a forbidden gold/eval module.  Used to stage a
    production-only workspace.  This is still AST-complete only for the import
    shapes the walker understands.
    """
    visited, findings = walk_local_import_graph(root_module)
    if findings:
        details = "; ".join(
            f"{item.reason} via {' -> '.join(item.via)}" for item in findings
        )
        raise ProviderGoldIsolationError(
            f"cannot stage module {root_module!r}: {details}"
        )
    files: list[Path] = []
    seen: set[Path] = set()
    repo = REPO_ROOT.resolve()
    for module in visited:
        path = _module_path(module)
        if path is None:
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(repo)
        except ValueError as exc:
            raise ProviderGoldIsolationError(
                f"module {module} resolves outside the repository: {resolved}"
            ) from exc
        candidates = [resolved]
        parent = resolved.relative_to(repo).parent
        while parent != Path("."):
            init = (repo / parent / "__init__.py").resolve()
            if init.is_file():
                candidates.append(init)
            parent = parent.parent
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                files.append(candidate)
    return tuple(files)


def inspect_provider_isolation(provider_id: str, module_name: str) -> ProviderIsolationReport:
    cached = _ISOLATION_CACHE.get(module_name)
    if cached is not None:
        return ProviderIsolationReport(
            provider_id=provider_id,
            root_module=cached.root_module,
            visited=cached.visited,
            findings=cached.findings,
        )
    visited, findings = walk_local_import_graph(module_name)
    report = ProviderIsolationReport(
        provider_id=provider_id,
        root_module=module_name,
        visited=visited,
        findings=findings,
    )
    _ISOLATION_CACHE[module_name] = report
    return report


def assert_provider_gold_free(provider_id: str, module_name: str) -> ProviderIsolationReport:
    report = inspect_provider_isolation(provider_id, module_name)
    if not report.ok:
        details = "; ".join(
            f"{item.reason} via {' -> '.join(item.via)}" for item in report.findings
        )
        raise ProviderGoldIsolationError(
            f"registered provider {provider_id!r} is not gold-isolated: {details}"
        )
    return report


def inspect_registered_production_providers(
    registry: Optional[dict[str, str]] = None,
) -> dict[str, ProviderIsolationReport]:
    mapping = dict(registry or REGISTERED_PRODUCTION_PROVIDERS)
    return {
        provider_id: inspect_provider_isolation(provider_id, module_name)
        for provider_id, module_name in mapping.items()
    }


def assert_registered_providers_gold_free(
    registry: Optional[dict[str, str]] = None,
) -> dict[str, ProviderIsolationReport]:
    reports = inspect_registered_production_providers(registry)
    failures = [report for report in reports.values() if not report.ok]
    if failures:
        raise ProviderGoldIsolationError(
            "registered production providers failed gold isolation: "
            + "; ".join(f"{item.provider_id}: {item.findings[0].reason}" for item in failures)
        )
    return reports
