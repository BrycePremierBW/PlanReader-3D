"""pb_holdout_suite_registry.py — Frozen Holdout Suite Registration & Integrity.

The master 99% accuracy target must eventually be validated against a
genuinely unseen frozen holdout suite — real, verified Plan+BOQ projects
whose expected quantities are never inspected while extraction logic is
being written or tuned. KSTVET and Murera are development/diagnostic
projects only (their expected quantities have already been inspected in
this codebase's history) and must never be presented as holdout evidence.

This module does not, and cannot, technically stop a developer from
opening a file. What it CAN do is make three things concrete and
verifiable rather than a matter of unaided discipline:

1. A clear directory/schema separation between development projects
   (benchmarks/public_tenders/) and frozen holdout projects
   (benchmarks/frozen_holdout/), following the identical schema so
   nothing project-specific needs to be invented ad hoc.
2. A registration step that hashes the ground-truth answer file
   (expected_boq_summary.json) at the moment a project is registered,
   and a verification step that proves -- by recomputed checksum -- it
   has not been edited since, e.g. to quietly "improve" a score.
3. A project-level separation check that rejects registering a holdout
   project whose project_number or organization matches an existing
   development project's, since expected quantities for such a project
   may already have been seen indirectly.

Building this registry does not itself require any new project files;
what it unblocks is registering them, with real integrity guarantees,
the moment they become available.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_REQUIRED_FILES: Sequence[str] = (
    "source_manifest.json",
    "benchmark_rules.json",
    "expected_project.json",
    "expected_boq_summary.json",
)

_LOCK_FILENAME = ".holdout_lock.json"


class HoldoutRegistrationError(Exception):
    """A holdout project failed validation and was not registered."""


@dataclass
class HoldoutLockRecord:
    project_id: str
    expected_boq_summary_sha256: str
    source_manifest_sha256: str
    registered_at: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HoldoutVerificationResult:
    project_id: str
    is_untouched: bool
    checked_at: str
    mismatches: List[str] = field(default_factory=list)


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _project_identity(manifest: Dict[str, Any]) -> Optional[tuple]:
    """A (project_name, project_number, client) identity tuple, lower-cased
    and stripped, for cross-project collision checks. Missing fields are
    treated as empty strings rather than failing the whole comparison."""
    return (
        str(manifest.get("project_name", "")).strip().lower(),
        str(manifest.get("project_number", "")).strip().lower(),
        str(manifest.get("client", "")).strip().lower(),
    )


def check_project_level_separation(
    candidate_manifest: Dict[str, Any],
    development_project_dirs: Sequence[Path],
) -> List[str]:
    """Return a list of human-readable collision descriptions between the
    candidate holdout project and any development project's own
    source_manifest.json (matched on project_name/project_number/client).
    An empty list means no collision was found."""
    candidate_identity = _project_identity(candidate_manifest)
    collisions: List[str] = []

    for dev_dir in development_project_dirs:
        dev_manifest_path = dev_dir / "source_manifest.json"
        if not dev_manifest_path.exists():
            continue
        dev_manifest = _read_json(dev_manifest_path)
        dev_identity = _project_identity(dev_manifest)

        for field_name, cand_val, dev_val in zip(
            ("project_name", "project_number", "client"), candidate_identity, dev_identity
        ):
            if cand_val and dev_val and cand_val == dev_val:
                collisions.append(
                    f"{field_name} matches development project "
                    f"{dev_manifest.get('benchmark_id', dev_dir.name)!r} "
                    f"({field_name}={cand_val!r})"
                )
    return collisions


def register_holdout_project(
    project_dir: Path,
    *,
    development_project_dirs: Sequence[Path] = (),
    notes: str = "",
) -> HoldoutLockRecord:
    """Validate and register a frozen holdout project. Requires all
    _REQUIRED_FILES to be present and readable JSON, and (when
    development_project_dirs is given) rejects any project-identity
    collision with a known development project. Writes a lock file
    recording the SHA-256 of the ground-truth answer file, so a later
    call to verify_holdout_untouched() can prove it was never edited
    after this point. Raises HoldoutRegistrationError on any failure --
    never registers a partially-valid project."""
    if not project_dir.is_dir():
        raise HoldoutRegistrationError(f"{project_dir} is not a directory")

    missing = [f for f in _REQUIRED_FILES if not (project_dir / f).exists()]
    if missing:
        raise HoldoutRegistrationError(
            f"{project_dir.name}: missing required file(s): {', '.join(missing)}"
        )

    for f in _REQUIRED_FILES:
        try:
            _read_json(project_dir / f)
        except json.JSONDecodeError as exc:
            raise HoldoutRegistrationError(f"{project_dir.name}: {f} is not valid JSON: {exc}") from exc

    source_manifest = _read_json(project_dir / "source_manifest.json")
    project_id = source_manifest.get("benchmark_id") or project_dir.name

    collisions = check_project_level_separation(source_manifest, development_project_dirs)
    if collisions:
        raise HoldoutRegistrationError(
            f"{project_id}: project-level separation violated -- " + "; ".join(collisions)
        )

    record = HoldoutLockRecord(
        project_id=project_id,
        expected_boq_summary_sha256=_sha256_of_file(project_dir / "expected_boq_summary.json"),
        source_manifest_sha256=_sha256_of_file(project_dir / "source_manifest.json"),
        registered_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )
    (project_dir / _LOCK_FILENAME).write_text(
        json.dumps(record.to_dict(), indent=2), encoding="utf-8"
    )
    return record


def verify_holdout_untouched(project_dir: Path) -> HoldoutVerificationResult:
    """Recompute checksums for a previously-registered holdout project and
    compare against its lock file. is_untouched is False (with details in
    mismatches) if the project was never registered, the lock file is
    missing/corrupt, or either tracked file's content has changed since
    registration."""
    checked_at = datetime.now(timezone.utc).isoformat()
    lock_path = project_dir / _LOCK_FILENAME
    project_id = project_dir.name

    if not lock_path.exists():
        return HoldoutVerificationResult(
            project_id=project_id, is_untouched=False, checked_at=checked_at,
            mismatches=["no lock file -- project was never registered"],
        )

    try:
        lock = _read_json(lock_path)
    except json.JSONDecodeError as exc:
        return HoldoutVerificationResult(
            project_id=project_id, is_untouched=False, checked_at=checked_at,
            mismatches=[f"lock file is not valid JSON: {exc}"],
        )

    project_id = lock.get("project_id", project_id)
    mismatches: List[str] = []

    for field_name, filename in (
        ("expected_boq_summary_sha256", "expected_boq_summary.json"),
        ("source_manifest_sha256", "source_manifest.json"),
    ):
        target_path = project_dir / filename
        if not target_path.exists():
            mismatches.append(f"{filename} is missing")
            continue
        current_hash = _sha256_of_file(target_path)
        recorded_hash = lock.get(field_name)
        if recorded_hash != current_hash:
            mismatches.append(
                f"{filename} checksum changed since registration "
                f"(recorded {recorded_hash}, now {current_hash})"
            )

    return HoldoutVerificationResult(
        project_id=project_id, is_untouched=not mismatches, checked_at=checked_at, mismatches=mismatches,
    )


def list_registered_holdout_projects(holdout_root: Path) -> List[str]:
    """Project ids under holdout_root that carry a valid lock file,
    sorted for stable output. A project directory without a lock file
    (not yet registered) is silently excluded, not an error."""
    if not holdout_root.is_dir():
        return []
    registered = []
    for child in sorted(holdout_root.iterdir()):
        if child.is_dir() and (child / _LOCK_FILENAME).exists():
            registered.append(child.name)
    return registered
