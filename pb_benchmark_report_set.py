"""Atomic, run-scoped benchmark report publication and consumption.

A combined dashboard and every project-level report from one evaluation
must share one run ID, one evaluated commit, and one scoring-policy
identifier.  Consumers treat ``current.json`` as the only published
pointer and reject incomplete, mixed, stale, or hash-invalid sets.

This module is a reporting/publication layer.  It does not score,
map, re-denominator, or re-tolerate quantities.  Extractor/runtime
modules must not import it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence


REPORT_SET_SCHEMA_VERSION = "1.0.0"
EVALUATOR_VERSION = "pb_benchmark_accuracy_engine.v1"
SCORING_POLICY_IDENTIFIER = "public_tender_exact_or_within_5pct_v1"
SOURCE_HASH_ALGORITHM = "sha256"
SUPPORTED_SCHEMA_VERSIONS = frozenset({REPORT_SET_SCHEMA_VERSION})

CLASSIFICATION_DEVELOPMENT = "development"
CLASSIFICATION_DIAGNOSTIC = "diagnostic"
CLASSIFICATION_UNTOUCHED_HOLDOUT = "untouched_holdout"
VALID_CLASSIFICATIONS = frozenset(
    {
        CLASSIFICATION_DEVELOPMENT,
        CLASSIFICATION_DIAGNOSTIC,
        CLASSIFICATION_UNTOUCHED_HOLDOUT,
    }
)

RUNS_DIRNAME = "runs"
PROJECTS_DIRNAME = "projects"
RUN_MANIFEST_NAME = "run_manifest.json"
COMBINED_SUMMARY_NAME = "combined_summary.json"
CURRENT_POINTER_NAME = "current.json"
LOCK_FILENAME = ".report_set.lock"

_HOLDOUT_ID_NAMESPACE = "planreader-untouched-holdout-id:"
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_GOLD_QUANTITY_KEYS = frozenset(
    {
        "expected_quantity",
        "expected_quantities",
        "sample_measurable_items",
        "expected_boq_summary",
    }
)
_ALLOWED_RUN_METADATA_KEYS = frozenset(
    {
        "run_id",
        "started_at",
        "completed_at",
        "generated_at",
        "published_at",
        "timestamp",
        "report_artifact_hashes",
        "generated_artifacts",
        "required_artifacts",
        "source_hashes",
    }
)

_thread_lock = threading.Lock()


class ReportSetError(Exception):
    """Base error for report-set publication or consumption."""


class IncompleteReportSetError(ReportSetError):
    """Required artifacts are missing or completion_state is not complete."""


class MixedRunIdError(ReportSetError):
    """Artifacts in a run directory do not share one run ID."""


class MixedCommitError(ReportSetError):
    """Artifacts in a run directory do not share one evaluated commit."""


class StaleReportError(ReportSetError):
    """A consumer-facing artifact does not match the published current run."""


class SourceHashInvalidationError(ReportSetError):
    """Source-document hashes no longer match the hashes recorded for the run."""


class ArtifactHashMismatchError(ReportSetError):
    """A generated artifact's bytes do not match the recorded content hash."""


class UnsupportedSchemaError(ReportSetError):
    """schema_version is missing or not in the supported set."""


class MalformedTimestampError(ReportSetError):
    """A timestamp is missing, not ISO-8601, or lacks a timezone."""


class ClassificationMixError(ReportSetError):
    """Development and untouched-holdout outputs were combined incorrectly."""


class MissingSourceDocumentError(ReportSetError):
    """A required source PDF or drawing document is absent."""


class MissingLocalGoldError(ReportSetError):
    """A required local gold/expected file is absent."""


class UnexpectedArtifactError(ReportSetError):
    """An unexpected extra report artifact is present in the run directory."""


class PointerIncompleteError(ReportSetError):
    """Attempted to publish current.json against an incomplete run."""


@dataclass(frozen=True)
class ReportRunContext:
    """Identity metadata shared by every artifact in one evaluation run."""

    run_id: str
    evaluated_commit_sha: str
    started_at: str
    scoring_policy_identifier: str = SCORING_POLICY_IDENTIFIER
    schema_version: str = REPORT_SET_SCHEMA_VERSION
    evaluator_version: str = EVALUATOR_VERSION


@dataclass
class ProjectReportSpec:
    """One project report to include in an atomic report set.

    ``source_hashes`` is keyed by a stable document role (not a filesystem
    path) so renaming a file with identical bytes does not change hashes
    or score content.  ``report_payload`` is the public-safe project
    document written under ``projects/<project_id>.json``.
    """

    project_id: str
    classification: str
    report_payload: Dict[str, Any]
    source_hashes: Dict[str, str] = field(default_factory=dict)
    required_source_documents: Dict[str, Path] = field(default_factory=dict)
    required_gold_files: Dict[str, Path] = field(default_factory=dict)
    raw_benchmark_id: Optional[str] = None


def new_run_id() -> str:
    """Return a unique run identifier (32 hex characters)."""
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with timezone."""
    return datetime.now(timezone.utc).isoformat()


def validate_timestamp(value: Any, *, field_name: str = "timestamp") -> str:
    """Require a timezone-aware ISO-8601 timestamp string."""
    if not isinstance(value, str) or not value.strip():
        raise MalformedTimestampError(f"{field_name} is missing or empty")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MalformedTimestampError(
            f"{field_name} is not a valid ISO-8601 timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise MalformedTimestampError(
            f"{field_name} must include a timezone: {value!r}"
        )
    return value


def validate_schema_version(value: Any) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaError(
            f"Unsupported report-set schema_version: {value!r}"
        )
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def opaque_holdout_project_id(raw_benchmark_id: str) -> str:
    """Return a non-identifying project id for untouched holdouts."""
    digest = hashlib.sha256(
        f"{_HOLDOUT_ID_NAMESPACE}{raw_benchmark_id}".encode("utf-8")
    ).hexdigest()[:16]
    return f"holdout_{digest}"


def classify_from_status(
    status: str,
    *,
    is_holdout: bool = False,
    is_headline_eligible: bool = False,
) -> str:
    """Map evaluator status onto report-set classifications."""
    if is_holdout:
        return CLASSIFICATION_UNTOUCHED_HOLDOUT
    if is_headline_eligible or status in {
        "scored",
        "verified_scored_benchmark",
        "verified_public_benchmark",
    }:
        return CLASSIFICATION_DEVELOPMENT
    return CLASSIFICATION_DIAGNOSTIC


def resolve_evaluated_commit_sha(repo_root: Optional[Path] = None) -> str:
    """Resolve the git commit being evaluated. Fail closed if unavailable."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    sha = (result.stdout or "").strip().lower()
    if result.returncode != 0 or not _COMMIT_SHA.fullmatch(sha):
        raise ReportSetError(
            "Unable to resolve evaluated commit SHA via git rev-parse HEAD"
        )
    return sha


def public_item_record(
    item: Mapping[str, Any],
    *,
    classification: str,
) -> Dict[str, Any]:
    """Project-item record with gold quantities stripped."""
    record: Dict[str, Any] = {
        "status": item.get("status"),
        "tolerance_tier": item.get("tolerance_tier"),
    }
    if classification != CLASSIFICATION_UNTOUCHED_HOLDOUT:
        if "item_id" in item:
            record["item_id"] = item.get("item_id")
        if "extracted_quantity" in item:
            record["extracted_quantity"] = item.get("extracted_quantity")
    return record


def _contains_gold_quantity(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in _GOLD_QUANTITY_KEYS:
                return True
            if _contains_gold_quantity(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_gold_quantity(item) for item in value)
    return False


def assert_public_safe(payload: Mapping[str, Any], *, label: str) -> None:
    """Fail closed if a public-safe document contains raw expected quantities."""
    if _contains_gold_quantity(payload):
        raise ReportSetError(
            f"Public-safe document {label} contains raw expected quantities"
        )


def assert_holdout_identity_hidden(
    payload: Mapping[str, Any],
    raw_benchmark_id: str,
    *,
    label: str,
) -> None:
    blob = json.dumps(payload, default=str)
    if raw_benchmark_id and raw_benchmark_id in blob:
        raise ReportSetError(
            f"Protected holdout identifier leaked in {label}"
        )


def score_content(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return score-bearing fields, stripping allowed run metadata."""

    def _strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: _strip(val)
                for key, val in node.items()
                if key not in _ALLOWED_RUN_METADATA_KEYS
            }
        if isinstance(node, list):
            return [_strip(item) for item in node]
        return node

    return _strip(dict(payload))


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    """Write a single file via temp-file + os.replace (POSIX atomic rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, _json_dumps(payload))


@contextmanager
def exclusive_publish_lock(output_dir: Path) -> Iterator[None]:
    """Process-level lock so concurrent writers cannot mix a report set."""
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / LOCK_FILENAME
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    with _thread_lock:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def run_directory(output_dir: Path, run_id: str) -> Path:
    return Path(output_dir) / RUNS_DIRNAME / run_id


def current_pointer_path(output_dir: Path) -> Path:
    return Path(output_dir) / CURRENT_POINTER_NAME


def _require_hex_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise ArtifactHashMismatchError(f"{label} is not a SHA-256 hex digest")
    return value


def _check_required_inputs(spec: ProjectReportSpec, *, require_sources: bool, require_gold: bool) -> None:
    if require_sources:
        for role, path in spec.required_source_documents.items():
            if path is None or not Path(path).is_file():
                raise MissingSourceDocumentError(
                    f"Missing required source document for {spec.project_id} role={role}: {path}"
                )
    if require_gold:
        for role, path in spec.required_gold_files.items():
            if path is None or not Path(path).is_file():
                raise MissingLocalGoldError(
                    f"Missing required local gold file for {spec.project_id} role={role}: {path}"
                )


def _assert_classifications(specs: Sequence[ProjectReportSpec]) -> None:
    classes = {spec.classification for spec in specs}
    unknown = classes - VALID_CLASSIFICATIONS
    if unknown:
        raise ClassificationMixError(f"Unknown project classification(s): {sorted(unknown)}")
    has_holdout = CLASSIFICATION_UNTOUCHED_HOLDOUT in classes
    has_development = CLASSIFICATION_DEVELOPMENT in classes
    if has_holdout and has_development:
        raise ClassificationMixError(
            "Development and untouched-holdout reports cannot be combined in one report set"
        )


def _decorate_payload(
    payload: Mapping[str, Any],
    *,
    context: ReportRunContext,
    generated_at: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    decorated = dict(payload)
    decorated.update(
        {
            "schema_version": context.schema_version,
            "evaluator_version": context.evaluator_version,
            "run_id": context.run_id,
            "evaluated_commit_sha": context.evaluated_commit_sha,
            "scoring_policy_identifier": context.scoring_policy_identifier,
            "generated_at": generated_at,
        }
    )
    if extra:
        decorated.update(dict(extra))
    return decorated


def _relative_artifact(path: Path, run_dir: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _list_generated_files(run_dir: Path) -> List[Path]:
    files: List[Path] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != LOCK_FILENAME:
            files.append(path)
    return files


def validate_report_set_directory(run_dir: Path) -> Dict[str, Any]:
    """Validate a fully written run directory.  Does not consult current.json."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / RUN_MANIFEST_NAME
    combined_path = run_dir / COMBINED_SUMMARY_NAME
    projects_dir = run_dir / PROJECTS_DIRNAME

    if not manifest_path.is_file():
        raise IncompleteReportSetError(f"Missing {RUN_MANIFEST_NAME} in {run_dir}")
    if not combined_path.is_file():
        raise IncompleteReportSetError(f"Missing {COMBINED_SUMMARY_NAME} in {run_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    combined = json.loads(combined_path.read_text(encoding="utf-8"))

    validate_schema_version(manifest.get("schema_version"))
    validate_schema_version(combined.get("schema_version"))
    validate_timestamp(manifest.get("started_at"), field_name="started_at")
    validate_timestamp(manifest.get("completed_at"), field_name="completed_at")
    validate_timestamp(combined.get("generated_at"), field_name="combined.generated_at")

    if manifest.get("completion_state") != "complete":
        raise IncompleteReportSetError(
            f"Run {manifest.get('run_id')} completion_state="
            f"{manifest.get('completion_state')!r} is not complete"
        )

    run_id = manifest.get("run_id")
    commit = manifest.get("evaluated_commit_sha")
    policy = manifest.get("scoring_policy_identifier")
    if not run_id or not isinstance(run_id, str):
        raise MixedRunIdError("run_manifest.json is missing run_id")
    if not isinstance(commit, str) or not _COMMIT_SHA.fullmatch(str(commit).lower()):
        raise MixedCommitError(
            f"run_manifest.json has invalid evaluated_commit_sha: {commit!r}"
        )
    if not isinstance(policy, str) or not policy:
        raise ReportSetError("run_manifest.json is missing scoring_policy_identifier")
    if combined.get("run_id") != run_id:
        raise MixedRunIdError("combined_summary.json run_id does not match run_manifest.json")
    if combined.get("evaluated_commit_sha") != commit:
        raise MixedCommitError(
            "combined_summary.json evaluated_commit_sha does not match run_manifest.json"
        )
    if combined.get("scoring_policy_identifier") != policy:
        raise ReportSetError("combined_summary.json scoring_policy_identifier mismatch")

    assert_public_safe(combined, label="combined_summary.json")
    if combined.get("evaluator_version") != manifest.get("evaluator_version"):
        raise ReportSetError("combined_summary.json evaluator_version mismatch")

    required = list(manifest.get("required_artifacts") or [])
    generated = list(manifest.get("generated_artifacts") or [])
    if not required:
        raise IncompleteReportSetError("run_manifest.json has empty required_artifacts")

    present_rel = {_relative_artifact(p, run_dir) for p in _list_generated_files(run_dir)}
    required_set = set(required)
    generated_set = set(generated)
    if required_set != generated_set:
        raise IncompleteReportSetError(
            "required_artifacts and generated_artifacts diverge: "
            f"missing={sorted(required_set - generated_set)} "
            f"extra={sorted(generated_set - required_set)}"
        )
    missing = required_set - present_rel
    if missing:
        raise IncompleteReportSetError(f"Missing required artifacts: {sorted(missing)}")
    extra = present_rel - required_set
    if extra:
        raise UnexpectedArtifactError(
            f"Unexpected extra artifacts in run directory: {sorted(extra)}"
        )

    project_files = sorted((projects_dir).glob("*.json")) if projects_dir.is_dir() else []
    project_payloads: List[Dict[str, Any]] = []
    for path in project_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_schema_version(payload.get("schema_version"))
        validate_timestamp(payload.get("generated_at"), field_name=f"{path.name}.generated_at")
        if payload.get("run_id") != run_id:
            raise MixedRunIdError(
                f"{path.name} run_id {payload.get('run_id')!r} != {run_id!r}"
            )
        if payload.get("evaluated_commit_sha") != commit:
            raise MixedCommitError(
                f"{path.name} evaluated_commit_sha does not match the run"
            )
        if payload.get("scoring_policy_identifier") != policy:
            raise ReportSetError(
                f"{path.name} scoring_policy_identifier does not match the run"
            )
        classification = payload.get("classification")
        if classification not in VALID_CLASSIFICATIONS:
            raise ClassificationMixError(
                f"{path.name} has invalid classification {classification!r}"
            )
        assert_public_safe(payload, label=path.name)
        project_payloads.append(payload)

    classifications = {p.get("classification") for p in project_payloads}
    if (
        CLASSIFICATION_DEVELOPMENT in classifications
        and CLASSIFICATION_UNTOUCHED_HOLDOUT in classifications
    ):
        raise ClassificationMixError(
            "Development and untouched-holdout reports cannot share one run"
        )

    artifact_hashes = manifest.get("report_artifact_hashes") or {}
    hashed_expected = required_set - {RUN_MANIFEST_NAME}
    if set(artifact_hashes) != hashed_expected:
        raise ArtifactHashMismatchError(
            "report_artifact_hashes keys must match every required artifact except run_manifest.json"
        )
    for rel, expected_hash in artifact_hashes.items():
        _require_hex_digest(expected_hash, label=rel)
        actual = sha256_file(run_dir / rel)
        if actual != expected_hash:
            raise ArtifactHashMismatchError(
                f"Artifact content hash mismatch for {rel}"
            )

    source_hashes = manifest.get("source_hashes") or {}
    for key, digest in source_hashes.items():
        _require_hex_digest(digest, label=f"source_hashes[{key}]")

    if manifest.get("source_hash_algorithm") != SOURCE_HASH_ALGORITHM:
        raise ReportSetError("source_hash_algorithm must be sha256")

    return {
        "manifest": manifest,
        "combined": combined,
        "projects": project_payloads,
        "run_dir": run_dir,
    }


def load_current_pointer(output_dir: Path) -> Dict[str, Any]:
    path = current_pointer_path(output_dir)
    if not path.is_file():
        raise IncompleteReportSetError(f"No published current pointer at {path}")
    pointer = json.loads(path.read_text(encoding="utf-8"))
    validate_schema_version(pointer.get("schema_version"))
    validate_timestamp(pointer.get("published_at"), field_name="published_at")
    if pointer.get("completion_state") != "complete":
        raise PointerIncompleteError(
            "current.json must not point at an incomplete run"
        )
    run_id = pointer.get("run_id")
    run_dir_value = pointer.get("run_dir")
    if not run_id or not run_dir_value:
        raise IncompleteReportSetError("current.json is missing run_id or run_dir")
    return pointer


def load_and_validate_current_report_set(
    output_dir: Path,
    *,
    expected_commit_sha: Optional[str] = None,
    current_source_hashes: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Load the published pointer and reject incomplete / mixed / stale sets."""
    output_dir = Path(output_dir)
    pointer = load_current_pointer(output_dir)
    run_dir = output_dir / str(pointer["run_dir"])
    if not run_dir.is_dir():
        raise IncompleteReportSetError(f"Published run directory missing: {run_dir}")

    validated = validate_report_set_directory(run_dir)
    manifest = validated["manifest"]
    if pointer.get("run_id") != manifest.get("run_id"):
        raise MixedRunIdError("current.json run_id does not match the run directory")
    if pointer.get("evaluated_commit_sha") != manifest.get("evaluated_commit_sha"):
        raise MixedCommitError("current.json commit does not match the run directory")
    if expected_commit_sha and manifest.get("evaluated_commit_sha") != expected_commit_sha:
        raise MixedCommitError(
            "Published report set was produced from a different evaluated commit"
        )
    if current_source_hashes:
        recorded = manifest.get("source_hashes") or {}
        for key, digest in current_source_hashes.items():
            if recorded.get(key) != digest:
                raise SourceHashInvalidationError(
                    f"Source hash changed for {key}; prior reports are invalid"
                )
        extra_recorded = set(recorded) - set(current_source_hashes)
        missing_recorded = set(current_source_hashes) - set(recorded)
        if extra_recorded or missing_recorded:
            raise SourceHashInvalidationError(
                "Source hash inventory changed relative to the published run"
            )
    return {**validated, "pointer": pointer}


def detect_stale_legacy_reports(
    output_dir: Path,
    *,
    legacy_report_paths: Sequence[Path],
) -> None:
    """Reject leftover project/combined files that do not match current.json."""
    validated = load_and_validate_current_report_set(output_dir)
    run_id = validated["manifest"]["run_id"]
    commit = validated["manifest"]["evaluated_commit_sha"]
    for path in legacy_report_paths:
        target = Path(path)
        if not target.is_file():
            raise StaleReportError(f"Expected legacy report missing: {target}")
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("run_id") != run_id:
            raise StaleReportError(
                f"{target.name} run_id does not match the published current run"
            )
        if payload.get("evaluated_commit_sha") != commit:
            raise StaleReportError(
                f"{target.name} evaluated_commit_sha does not match the published current run"
            )


def publish_report_set(
    output_dir: Path,
    *,
    context: ReportRunContext,
    project_specs: Sequence[ProjectReportSpec],
    combined_summary: Mapping[str, Any],
    require_source_documents: bool = False,
    require_local_gold: bool = False,
) -> Dict[str, Any]:
    """Write one complete run directory and atomically publish current.json.

    Interrupted writers leave ``current.json`` pointing at the previous
    complete run.  The pointer is replaced only after every required
    artifact exists and validates.
    """
    output_dir = Path(output_dir)
    validate_schema_version(context.schema_version)
    validate_timestamp(context.started_at, field_name="started_at")
    if not _COMMIT_SHA.fullmatch(context.evaluated_commit_sha.lower()):
        raise MixedCommitError(
            f"Invalid evaluated_commit_sha: {context.evaluated_commit_sha!r}"
        )
    _assert_classifications(project_specs)

    for spec in project_specs:
        _check_required_inputs(
            spec,
            require_sources=require_source_documents,
            require_gold=require_local_gold,
        )
        if spec.classification == CLASSIFICATION_UNTOUCHED_HOLDOUT and spec.raw_benchmark_id:
            assert_holdout_identity_hidden(
                spec.report_payload,
                spec.raw_benchmark_id,
                label=f"project {spec.project_id}",
            )

    with exclusive_publish_lock(output_dir):
        completed_at = utc_now_iso()
        generated_at = completed_at
        run_dir = run_directory(output_dir, context.run_id)
        projects_dir = run_dir / PROJECTS_DIRNAME
        projects_dir.mkdir(parents=True, exist_ok=True)

        decorated_projects: Dict[str, Dict[str, Any]] = {}
        for spec in project_specs:
            payload = _decorate_payload(
                spec.report_payload,
                context=context,
                generated_at=generated_at,
                extra={
                    "project_id": spec.project_id,
                    "classification": spec.classification,
                },
            )
            assert_public_safe(payload, label=f"projects/{spec.project_id}.json")
            if spec.classification == CLASSIFICATION_UNTOUCHED_HOLDOUT and spec.raw_benchmark_id:
                assert_holdout_identity_hidden(
                    payload,
                    spec.raw_benchmark_id,
                    label=f"projects/{spec.project_id}.json",
                )
            target = projects_dir / f"{spec.project_id}.json"
            atomic_write_json(target, payload)
            decorated_projects[spec.project_id] = payload

        combined_payload = _decorate_payload(
            combined_summary,
            context=context,
            generated_at=generated_at,
        )
        assert_public_safe(combined_payload, label=COMBINED_SUMMARY_NAME)
        combined_path = run_dir / COMBINED_SUMMARY_NAME
        atomic_write_json(combined_path, combined_payload)

        source_hashes: Dict[str, str] = {}
        for spec in project_specs:
            for role, digest in spec.source_hashes.items():
                _require_hex_digest(digest, label=f"{spec.project_id}:{role}")
                source_hashes[f"{spec.project_id}:{role}"] = digest

        project_classification = {
            spec.project_id: spec.classification for spec in project_specs
        }

        hashed_artifacts = [COMBINED_SUMMARY_NAME] + [
            f"{PROJECTS_DIRNAME}/{spec.project_id}.json" for spec in project_specs
        ]
        required_artifacts = hashed_artifacts + [RUN_MANIFEST_NAME]
        artifact_hashes = {
            COMBINED_SUMMARY_NAME: sha256_file(combined_path),
        }
        for spec in project_specs:
            rel = f"{PROJECTS_DIRNAME}/{spec.project_id}.json"
            artifact_hashes[rel] = sha256_file(projects_dir / f"{spec.project_id}.json")

        manifest = {
            "schema_version": context.schema_version,
            "evaluator_version": context.evaluator_version,
            "run_id": context.run_id,
            "evaluated_commit_sha": context.evaluated_commit_sha,
            "started_at": context.started_at,
            "completed_at": completed_at,
            "completion_state": "complete",
            "project_classification": project_classification,
            "source_hash_algorithm": SOURCE_HASH_ALGORITHM,
            "source_hashes": source_hashes,
            "report_artifact_hashes": artifact_hashes,
            "required_artifacts": required_artifacts,
            "generated_artifacts": required_artifacts,
            "scoring_policy_identifier": context.scoring_policy_identifier,
        }
        manifest_path = run_dir / RUN_MANIFEST_NAME
        atomic_write_json(manifest_path, manifest)

        return _publish_current_pointer_unlocked(output_dir, run_dir)


def publish_current_pointer(output_dir: Path, run_dir: Path) -> Dict[str, Any]:
    """Atomically point current.json at an already-written run directory.

    Refuses incomplete or invalid runs so a pointer can never target a
    partial generation.
    """
    output_dir = Path(output_dir)
    run_dir = Path(run_dir)
    with exclusive_publish_lock(output_dir):
        return _publish_current_pointer_unlocked(output_dir, run_dir)


def _publish_current_pointer_unlocked(output_dir: Path, run_dir: Path) -> Dict[str, Any]:
    validated = validate_report_set_directory(run_dir)
    manifest = validated["manifest"]
    if manifest.get("completion_state") != "complete":
        raise PointerIncompleteError(
            "Refusing to publish current.json against an incomplete run"
        )
    pointer = {
        "schema_version": manifest.get("schema_version", REPORT_SET_SCHEMA_VERSION),
        "run_id": manifest["run_id"],
        "evaluated_commit_sha": manifest["evaluated_commit_sha"],
        "run_dir": f"{RUNS_DIRNAME}/{manifest['run_id']}",
        "published_at": utc_now_iso(),
        "completion_state": "complete",
        "scoring_policy_identifier": manifest["scoring_policy_identifier"],
    }
    atomic_write_json(current_pointer_path(output_dir), pointer)
    return load_and_validate_current_report_set(output_dir)


def write_incomplete_run_for_tests(
    output_dir: Path,
    *,
    context: ReportRunContext,
    combined_summary: Mapping[str, Any],
    project_specs: Sequence[ProjectReportSpec],
    omit_project_ids: Sequence[str] = (),
    extra_project_payload: Optional[Mapping[str, Any]] = None,
    extra_filename: Optional[str] = None,
    completion_state: str = "incomplete",
) -> Path:
    """Test helper: write a run directory without publishing current.json."""
    output_dir = Path(output_dir)
    run_dir = run_directory(output_dir, context.run_id)
    projects_dir = run_dir / PROJECTS_DIRNAME
    projects_dir.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now_iso()

    omitted = set(omit_project_ids)
    for spec in project_specs:
        if spec.project_id in omitted:
            continue
        payload = _decorate_payload(
            spec.report_payload,
            context=context,
            generated_at=generated_at,
            extra={
                "project_id": spec.project_id,
                "classification": spec.classification,
            },
        )
        atomic_write_json(projects_dir / f"{spec.project_id}.json", payload)

    if extra_project_payload is not None:
        extra_name = extra_filename or "unexpected.json"
        atomic_write_json(projects_dir / extra_name, dict(extra_project_payload))

    combined_payload = _decorate_payload(
        combined_summary, context=context, generated_at=generated_at
    )
    atomic_write_json(run_dir / COMBINED_SUMMARY_NAME, combined_payload)

    required = [COMBINED_SUMMARY_NAME] + [
        f"{PROJECTS_DIRNAME}/{spec.project_id}.json" for spec in project_specs
    ]
    generated = [COMBINED_SUMMARY_NAME] + [
        f"{PROJECTS_DIRNAME}/{spec.project_id}.json"
        for spec in project_specs
        if spec.project_id not in omitted
    ]
    if extra_project_payload is not None:
        generated.append(f"{PROJECTS_DIRNAME}/{extra_filename or 'unexpected.json'}")

    hashed = [rel for rel in generated if rel != RUN_MANIFEST_NAME]
    artifact_hashes = {rel: sha256_file(run_dir / rel) for rel in hashed}

    manifest = {
        "schema_version": context.schema_version,
        "evaluator_version": context.evaluator_version,
        "run_id": context.run_id,
        "evaluated_commit_sha": context.evaluated_commit_sha,
        "started_at": context.started_at,
        "completed_at": generated_at,
        "completion_state": completion_state,
        "project_classification": {
            spec.project_id: spec.classification for spec in project_specs
        },
        "source_hash_algorithm": SOURCE_HASH_ALGORITHM,
        "source_hashes": {},
        "report_artifact_hashes": artifact_hashes,
        "required_artifacts": required + [RUN_MANIFEST_NAME],
        "generated_artifacts": generated + [RUN_MANIFEST_NAME],
        "scoring_policy_identifier": context.scoring_policy_identifier,
    }
    atomic_write_json(run_dir / RUN_MANIFEST_NAME, manifest)
    return run_dir


def public_combined_summary_from_projects(
    project_payloads: Sequence[Mapping[str, Any]],
    *,
    headline_classifications: Iterable[str] = (CLASSIFICATION_DEVELOPMENT,),
) -> Dict[str, Any]:
    """Build a public-safe combined summary from already-scored project payloads.

    Counts are copied, not recomputed from gold.  This function never
    reads expected quantities.
    """
    headline = [
        p for p in project_payloads if p.get("classification") in set(headline_classifications)
    ]
    diagnostic = [
        p
        for p in project_payloads
        if p.get("classification") == CLASSIFICATION_DIAGNOSTIC
    ]
    holdout = [
        p
        for p in project_payloads
        if p.get("classification") == CLASSIFICATION_UNTOUCHED_HOLDOUT
    ]
    if headline and holdout:
        raise ClassificationMixError(
            "Development and untouched-holdout reports cannot be combined"
        )

    def _sum(field: str) -> int:
        return int(sum(int(p.get("summary", {}).get(field, 0) or 0) for p in headline))

    tot_compared = _sum("total_items_compared")
    tot_exact = _sum("exact_matches")
    tot_w5 = _sum("within_5_percent")
    accepted = tot_exact + tot_w5
    overall = round((accepted / tot_compared) * 100.0, 2) if tot_compared else 0.0
    strict = round((tot_exact / tot_compared) * 100.0, 2) if tot_compared else 0.0

    def _project_row(payload: Mapping[str, Any]) -> Dict[str, Any]:
        summary = payload.get("summary") or {}
        return {
            "project_id": payload.get("project_id"),
            "classification": payload.get("classification"),
            "is_scored": payload.get("is_scored"),
            "is_headline_eligible": payload.get("is_headline_eligible"),
            "status": payload.get("status"),
            "exact_matches": summary.get("exact_matches", 0),
            "within_5_percent": summary.get("within_5_percent", 0),
            "within_10_percent": summary.get("within_10_percent", 0),
            "within_20_percent": summary.get("within_20_percent", 0),
            "gross_mismatches": summary.get("gross_mismatches", 0),
            "missed_items": summary.get("missed_items", 0),
            "hallucinated_items": summary.get("hallucinated_items", 0),
            "total_items_compared": summary.get("total_items_compared", 0),
            "overall_accuracy_percentage": summary.get("overall_accuracy_percentage"),
        }

    return {
        "headline_metrics": {
            "overall_accuracy_percentage": overall,
            "strict_exact_accuracy_percentage": strict,
            "total_headline_projects": len(headline),
            "exact_matches": tot_exact,
            "within_5_percent": tot_w5,
            "within_10_percent": _sum("within_10_percent"),
            "within_20_percent": _sum("within_20_percent"),
            "gross_mismatches": _sum("gross_mismatches"),
            "missed_items": _sum("missed_items"),
            "hallucinated_items": _sum("hallucinated_items"),
            "total_items_compared": tot_compared,
        },
        "projects": [_project_row(p) for p in project_payloads],
        "diagnostic_project_count": len(diagnostic),
        "untouched_holdout_project_count": len(holdout),
    }


def project_payload_from_accuracy_report(
    report: Any,
    *,
    classification: str,
    project_id: str,
) -> Dict[str, Any]:
    """Convert an in-memory accuracy report into a public-safe project payload.

    Score counts are copied from the evaluator; they are not recomputed.
    """
    item_results = [
        public_item_record(it.to_dict() if hasattr(it, "to_dict") else dict(it), classification=classification)
        for it in getattr(report, "item_results", [])
    ]
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "classification": classification,
        "status": getattr(report, "status", None),
        "is_scored": getattr(report, "is_scored", False),
        "is_headline_eligible": getattr(report, "is_headline_eligible", False),
        "summary": {
            "total_boq_items": getattr(report, "total_boq_items", 0),
            "total_measurable_expected": getattr(report, "total_measurable_expected", 0),
            "total_items_compared": getattr(report, "total_items_compared", 0),
            "exact_matches": getattr(report, "exact_matches", 0),
            "within_5_percent": getattr(report, "within_5_percent", 0),
            "within_10_percent": getattr(report, "within_10_percent", 0),
            "within_20_percent": getattr(report, "within_20_percent", 0),
            "gross_mismatches": getattr(report, "gross_mismatches", 0),
            "missed_items": getattr(report, "missed_items", 0),
            "hallucinated_items": getattr(report, "hallucinated_items", 0),
            "overall_accuracy_percentage": getattr(report, "overall_accuracy_percentage", None),
            "strict_exact_accuracy_percentage": getattr(report, "strict_exact_accuracy_percentage", None),
        },
        "item_results": item_results,
        "errors": list(getattr(report, "errors", []) or []),
    }
    if classification != CLASSIFICATION_UNTOUCHED_HOLDOUT:
        payload["legacy_benchmark_id"] = getattr(report, "benchmark_id", None)
    return payload


def attach_run_metadata(
    payload: Mapping[str, Any],
    *,
    context: ReportRunContext,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Copy run identity onto a legacy compatibility document."""
    decorated = dict(payload)
    decorated["run_id"] = context.run_id
    decorated["evaluated_commit_sha"] = context.evaluated_commit_sha
    decorated["scoring_policy_identifier"] = context.scoring_policy_identifier
    decorated["schema_version"] = context.schema_version
    decorated["evaluator_version"] = context.evaluator_version
    decorated["generated_at"] = generated_at or utc_now_iso()
    return decorated
