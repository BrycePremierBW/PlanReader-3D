"""pb_commercial_export_preflight_v163.py — Phase 6D Commercial Export Preflight & JobHub Publish Integrity.

Phase 6D Authority:
  - Consumes Phase 6B `collect_commercial_review_signals` from `pb_commercial_review_v161.py`.
  - Single Review & Export Preflight Authority: NO separate scale scanner, quantity scanner,
    or readiness database. Phase 6D consumes Phase 6B.
  - Fail-Closed Source Availability: If any required source family (takeoff, register, scale)
    is unavailable or incomplete, preflight_status is forced to BLOCKED.
  - Complete Canonical Review Fingerprint: Hashes source_coverage + full normalized signal content.
  - Consequential Payload Hash: Hashes all takeoff pricing, quantity, substrate, finish, rates,
    and metadata fields affecting JobHub packages and quotation exports.
  - TOCTOU Safety: Immediately before consequential final JobHub publish, re-derives
    Phase 6B review and fresh Phase 6D preflight, verifying exact fingerprint & payload match.
  - Server-Level Duplicate Guard: Checks existing JobHub package receipts for matching preflight fingerprint.
"""
from __future__ import annotations

import dataclasses
import hashlib
import html
import inspect
import json
import math
import sqlite3
from typing import Any

from pb_commercial_review_v161 import (
    REQUIRED_FAMILIES,
    SEVERITY_BLOCKER,
    SEVERITY_INFO,
    SEVERITY_REVIEW,
    CommercialReviewResult,
    collect_commercial_review_signals,
)
from pb_opening_production_v175 import (
    PAGES_INDEX_KEY,
    SETTING_PREFIX,
    _is_authorised_b5_automatic,
    _is_valid_positive_int,
)
from pb_takeoff_authority_v164 import (
    is_excluded_takeoff_row,
    is_floor_reference_row,
    takeoff_row_publishability,
)


@dataclasses.dataclass(frozen=True)
class CommercialPreflightResult:
    workspace_id: int
    job_no: str
    job_name: str
    drawing_issue: str
    jobhub_job_id: int | None
    preflight_status: str              # AVAILABLE | AVAILABLE_WITH_WARNING | BLOCKED | UNAVAILABLE
    blocker_count: int
    warning_count: int
    info_count: int
    total_review_items: int
    required_coverage_complete: bool
    unavailable_required_sources: list[str]
    internal_download_state: str        # AVAILABLE | AVAILABLE_WITH_WARNING | UNAVAILABLE
    draft_handoff_state: str           # AVAILABLE | AVAILABLE_WITH_WARNING | UNAVAILABLE
    final_publish_state: str           # AVAILABLE | AVAILABLE_WITH_WARNING | BLOCKED | UNAVAILABLE
    blocking_reasons: list[str]
    warnings: list[str]
    review_fingerprint: str
    preflight_fingerprint: str
    payload_hash: str
    total_takeoff_rows: int
    publishable_takeoff_rows: int
    excluded_takeoff_rows: int
    floor_reference_rows: int
    measured_zero_rows: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "job_no": html.escape(self.job_no or ""),
            "job_name": html.escape(self.job_name or ""),
            "drawing_issue": html.escape(self.drawing_issue or ""),
            "jobhub_job_id": self.jobhub_job_id,
            "preflight_status": self.preflight_status,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "total_review_items": self.total_review_items,
            "required_coverage_complete": self.required_coverage_complete,
            "unavailable_required_sources": [html.escape(s) for s in self.unavailable_required_sources],
            "internal_download_state": self.internal_download_state,
            "draft_handoff_state": self.draft_handoff_state,
            "final_publish_state": self.final_publish_state,
            "blocking_reasons": [html.escape(r) for r in self.blocking_reasons],
            "warnings": [html.escape(w) for w in self.warnings],
            "review_fingerprint": self.review_fingerprint,
            "preflight_fingerprint": self.preflight_fingerprint,
            "payload_hash": self.payload_hash,
            "total_takeoff_rows": self.total_takeoff_rows,
            "publishable_takeoff_rows": self.publishable_takeoff_rows,
            "excluded_takeoff_rows": self.excluded_takeoff_rows,
            "floor_reference_rows": self.floor_reference_rows,
            "measured_zero_rows": self.measured_zero_rows,
        }


def _db_query(conn_or_app: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if hasattr(conn_or_app, "lquery"):
        raw = conn_or_app.lquery(sql, params)
        if isinstance(raw, list):
            return [dict(r) for r in raw]
        if hasattr(raw, "to_dict"):
            return [dict(r) for r in raw.to_dict("records")]
    if hasattr(conn_or_app, "execute") or hasattr(conn_or_app, "cursor"):
        conn = conn_or_app
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    return []


def _get_workspace_meta(conn_or_app: Any, workspace_id: int) -> dict[str, Any]:
    rows = _db_query(conn_or_app, "SELECT id, job_no, job_name, drawing_issue, jobhub_job_id FROM workspaces WHERE id=?", (workspace_id,))
    if not rows:
        raise ValueError(f"Workspace #{workspace_id} does not exist.")
    row = rows[0]
    return {
        "id": row.get("id"),
        "job_no": str(row.get("job_no") or ""),
        "job_name": str(row.get("job_name") or ""),
        "drawing_issue": str(row.get("drawing_issue") or ""),
        "jobhub_job_id": row.get("jobhub_job_id"),
    }


def _safe_finite_float(val: Any) -> float | None:
    """Parse numeric float safely, rejecting non-finite numbers (NaN/inf) and booleans."""
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _get_takeoff_row_stats(conn_or_app: Any, workspace_id: int) -> tuple[int, int, int, int, int, str]:
    """Retrieves row statistics and payload fingerprint for a workspace across all consequential publish fields."""
    rows = _db_query(
        conn_or_app,
        "SELECT * FROM takeoff_rows WHERE workspace_id=? ORDER BY id",
        (workspace_id,)
    )
    total = len(rows)
    publishable = 0
    excluded = 0
    floor_ref = 0
    measured_zero = 0

    pub_payload_items = []

    for r in rows:
        r_id = r.get("id")
        unit_str = str(r.get("unit") or "")
        qty = r.get("quantity")
        inclusion_str = str(r.get("inclusion_status") or "").lower()
        role_str = str(r.get("row_role") or "").lower()

        is_excluded = is_excluded_takeoff_row(r)
        is_floor = is_floor_reference_row(r)
        is_publishable, _ = takeoff_row_publishability(r)

        if is_floor:
            floor_ref += 1
        elif is_excluded:
            excluded += 1
        if is_publishable:
            publishable += 1

        qty_clean = _safe_finite_float(qty)
        qty_status_str = str(r.get("quantity_status") or "").strip().lower()
        if qty_clean is not None and qty_clean == 0.0 and qty_status_str in ("measured", "confirmed", "allowance"):
            measured_zero += 1

        # Build comprehensive payload dict of consequential export fields
        pub_payload_items.append({
            "id": r_id,
            "section": str(r.get("section") or ""),
            "element": str(r.get("element") or ""),
            "location": str(r.get("location") or ""),
            "substrate": str(r.get("substrate") or ""),
            "unit": unit_str,
            "quantity": qty_clean,
            "coats": _safe_finite_float(r.get("coats")),
            "rate_per_unit": _safe_finite_float(r.get("rate_per_unit")),
            "labour_hours": _safe_finite_float(r.get("labour_hours")),
            "paint_litres": _safe_finite_float(r.get("paint_litres")),
            "value_ex_gst": _safe_finite_float(r.get("value_ex_gst")),
            "finish_system": str(r.get("finish_system") or ""),
            "coverage_m2_per_litre": _safe_finite_float(r.get("coverage_m2_per_litre")),
            "productivity_m2_per_hour": _safe_finite_float(r.get("productivity_m2_per_hour")),
            "inclusion_status": inclusion_str,
            "row_role": role_str,
            "notes": str(r.get("notes") or ""),
            "confidence": str(r.get("confidence") or ""),
            "source_reference": str(r.get("source_reference") or ""),
            "commercial_authority_status": str(r.get("commercial_authority_status") or ""),
            "commercial_authority_source": str(r.get("commercial_authority_source") or ""),
            "commercial_authority_reviewed_by": str(r.get("commercial_authority_reviewed_by") or ""),
            "commercial_authority_reviewed_at": str(r.get("commercial_authority_reviewed_at") or ""),
            "commercial_authority_fingerprint": str(r.get("commercial_authority_fingerprint") or ""),
        })

    # Sort payload deterministically by row ID
    sorted_payload = sorted(pub_payload_items, key=lambda x: str(x.get("id") or ""))
    payload_json = json.dumps(sorted_payload, sort_keys=True, allow_nan=False)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    return total, publishable, excluded, floor_ref, measured_zero, payload_hash


def compute_canonical_review_fingerprint(review_res: CommercialReviewResult) -> str:
    """Computes a deterministic, canonical SHA-256 fingerprint of the complete Phase 6B Review state."""
    coverage_dict = dict(getattr(review_res, "source_coverage", {}))
    signals = list(getattr(review_res, "signals", getattr(review_res, "items", [])))

    canonical_signals = []
    for sig in signals:
        reasons_val = getattr(sig, "reasons", ())
        if isinstance(reasons_val, (list, tuple)):
            reasons_tuple = tuple(str(x) for x in reasons_val)
        else:
            reasons_tuple = (str(reasons_val),)

        sig_dict = {
            "signal_id": str(getattr(sig, "signal_id", "")),
            "source_family": str(getattr(sig, "source_family", "")),
            "source_type": str(getattr(sig, "source_type", "")),
            "source_id": str(getattr(sig, "source_id", "")),
            "category": str(getattr(sig, "category", "")),
            "severity": str(getattr(sig, "severity", "")),
            "title": str(getattr(sig, "title", "")),
            "summary": str(getattr(sig, "summary", "")),
            "reasons": reasons_tuple,
            "status": str(getattr(sig, "status", "")),
            "location": str(getattr(sig, "location", "") or ""),
            "element": str(getattr(sig, "element", "") or ""),
            "unit": str(getattr(sig, "unit", "") or ""),
            "quantity": _safe_finite_float(getattr(sig, "quantity", None)),
            "inclusion_status": str(getattr(sig, "inclusion_status", "") or ""),
        }
        canonical_signals.append(sig_dict)

    # Sort signals deterministically by (severity, category, source_family, source_id, signal_id)
    sorted_signals = sorted(
        canonical_signals,
        key=lambda s: (s["severity"], s["category"], s["source_family"], s["source_id"], s["signal_id"])
    )

    review_state_structure = {
        "source_coverage": coverage_dict,
        "signals": sorted_signals,
    }
    raw_json = json.dumps(review_state_structure, sort_keys=True, allow_nan=False)
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


def _verify_b5_opening_evidence(conn_or_app: Any, workspace_id: int) -> tuple[list[str], list[str]]:
    """Verify persisted B5 opening deduction evidence for the workspace.
    Fails closed on pipeline errors, conflicts, orphaned pages, workspace replays, or invalid deductions.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    raw_index = None
    if hasattr(conn_or_app, "workspace_setting") and callable(conn_or_app.workspace_setting):
        raw_index = conn_or_app.workspace_setting(workspace_id, PAGES_INDEX_KEY, "[]")
    elif hasattr(conn_or_app, "get_workspace_setting") and callable(conn_or_app.get_workspace_setting):
        raw_index = conn_or_app.get_workspace_setting(workspace_id, PAGES_INDEX_KEY, "[]")
    else:
        try:
            rows = _db_query(conn_or_app, "SELECT value FROM workspace_settings WHERE workspace_id=? AND key=?", (workspace_id, PAGES_INDEX_KEY))
            if rows:
                raw_index = rows[0].get("value")
        except (sqlite3.OperationalError, sqlite3.DatabaseError, TypeError, ValueError):
            raw_index = None

    if not raw_index:
        return blockers, warnings

    try:
        page_ids = json.loads(raw_index) if isinstance(raw_index, str) else raw_index
        if not isinstance(page_ids, list):
            page_ids = []
    except (json.JSONDecodeError, TypeError, ValueError):
        blockers.append("B5 opening evidence index corrupted or unparseable")
        return blockers, warnings

    for pid in page_ids:
        if not _is_valid_positive_int(pid):
            blockers.append(f"Invalid page identity in B5 opening evidence index: {pid}")
            continue

        page_rows = _db_query(conn_or_app, "SELECT id, workspace_id FROM pages WHERE id=?", (int(pid),))
        if not page_rows:
            blockers.append(f"Orphaned B5 opening evidence for non-existent page #{pid}")
            continue

        live_page = page_rows[0]
        live_ws = live_page.get("workspace_id")
        if int(live_ws or 0) != int(workspace_id):
            blockers.append(f"Cross-workspace replay: B5 evidence page #{pid} belongs to workspace #{live_ws}, not #{workspace_id}")
            continue

        raw_payload = None
        key = f"{SETTING_PREFIX}{int(pid)}"
        if hasattr(conn_or_app, "workspace_setting") and callable(conn_or_app.workspace_setting):
            raw_payload = conn_or_app.workspace_setting(workspace_id, key, "{}")
        elif hasattr(conn_or_app, "get_workspace_setting") and callable(conn_or_app.get_workspace_setting):
            raw_payload = conn_or_app.get_workspace_setting(workspace_id, key, "{}")
        else:
            try:
                rows = _db_query(conn_or_app, "SELECT value FROM workspace_settings WHERE workspace_id=? AND key=?", (workspace_id, key))
                if rows:
                    raw_payload = rows[0].get("value")
            except (sqlite3.OperationalError, sqlite3.DatabaseError, TypeError, ValueError):
                raw_payload = None

        if not raw_payload:
            continue

        try:
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            if not isinstance(payload, dict):
                blockers.append(f"Malformed B5 opening evidence payload on page #{pid}")
                continue
        except (json.JSONDecodeError, TypeError, ValueError):
            blockers.append(f"Unparseable B5 opening evidence payload on page #{pid}")
            continue

        pl_ws = payload.get("workspace_id")
        if pl_ws is not None and int(pl_ws) != int(workspace_id):
            blockers.append(f"Cross-workspace replay: B5 payload on page #{pid} claims workspace #{pl_ws}, expected #{workspace_id}")
            continue

        pl_pid = payload.get("page_id")
        if pl_pid is not None and int(pl_pid) != int(pid):
            blockers.append(f"Page mismatch: B5 payload claims page #{pl_pid}, expected #{pid}")
            continue

        st = str(payload.get("status") or "").lower()
        if st == "error" or payload.get("error"):
            err_msg = payload.get("error") or "pipeline error"
            blockers.append(f"B5 opening analysis error on page #{pid}: {err_msg}")
            continue

        conflicts = payload.get("conflicts") or []
        if conflicts:
            blockers.append(f"Unresolved B5 opening conflicts on page #{pid} ({len(conflicts)} conflict(s))")

        for inst in payload.get("instances") or []:
            if not isinstance(inst, dict):
                blockers.append(f"Malformed opening instance on page #{pid}")
                continue
            is_deduct = inst.get("deduct")
            if is_deduct and not _is_authorised_b5_automatic(inst) and not inst.get("manual_override_confirmed"):
                tag = inst.get("tag") or inst.get("opening_instance_id") or inst.get("opening_id") or "unnamed"
                blockers.append(f"Unauthorized B5 opening deduction on page #{pid} ('{tag}'): missing required proof bundle or invalid evidence")

    return blockers, warnings


def derive_export_preflight(conn_or_app: Any, workspace_id: int, bridge_available: bool = True) -> CommercialPreflightResult:
    """Derives a normalized read-only Phase 6D Commercial Preflight Result by consuming Phase 6B."""
    meta = _get_workspace_meta(conn_or_app, workspace_id)

    # Call Phase 6B collector (Single Review Authority)
    workspace_dict = {"id": workspace_id, "job_no": meta["job_no"], "job_name": meta["job_name"], "drawing_issue": meta["drawing_issue"]}
    review_res: CommercialReviewResult = collect_commercial_review_signals(conn_or_app, workspace_dict)

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    unavailable_sources: list[str] = []

    try:
        total_rows, pub_rows, excl_rows, floor_rows, zero_rows, payload_hash = _get_takeoff_row_stats(conn_or_app, workspace_id)
    except (sqlite3.OperationalError, sqlite3.DatabaseError, TypeError, ValueError) as exc:
        total_rows, pub_rows, excl_rows, floor_rows, zero_rows, payload_hash = 0, 0, 0, 0, 0, "error"
        blocking_reasons.append(f"Take-off query error: {exc}")
        unavailable_sources.append("takeoff")

    # Fail-Closed Required Sources & Coverage Check
    signals = getattr(review_res, "signals", getattr(review_res, "items", []))
    source_coverage = getattr(review_res, "source_coverage", {})
    
    required_coverage_complete = True
    for fam in REQUIRED_FAMILIES:
        st_val = source_coverage.get(fam, "UNAVAILABLE")
        if st_val != "AVAILABLE":
            required_coverage_complete = False
            msg = f"Required source '{fam}' is {st_val}"
            blocking_reasons.append(msg)
            unavailable_sources.append(fam)

    # Process Phase 6B review signals
    blocker_count = getattr(review_res, "blocker_count", 0)
    warning_count = getattr(review_res, "review_count", 0)
    info_count = getattr(review_res, "info_count", 0)

    for sig in signals:
        sev = getattr(sig, "severity", SEVERITY_INFO)
        cat = getattr(sig, "category", "Review")
        summary = getattr(sig, "summary", getattr(sig, "message", "Signal"))
        src_fam = getattr(sig, "source_family", "")

        # Strict scale boundary: provisional or uncalibrated scale must ALWAYS block final publication!
        if src_fam == "scale" and (
            "provisional" in summary.lower()
            or "uncalibrated" in summary.lower()
            or "provisional" in cat.lower()
            or sev == SEVERITY_BLOCKER
        ):
            blocking_reasons.append(f"{cat}: {summary}")
            continue

        if sev == SEVERITY_BLOCKER:
            blocking_reasons.append(f"{cat}: {summary}")
        elif sev == SEVERITY_REVIEW:
            warnings.append(f"{cat}: {summary}")

    # Fail-Closed B5 Opening Deduction Evidence Check
    b5_blockers, b5_warnings = _verify_b5_opening_evidence(conn_or_app, workspace_id)
    blocking_reasons.extend(b5_blockers)
    warnings.extend(b5_warnings)

    # Publishable row count gate
    if pub_rows == 0:
        blocking_reasons.append("Zero publishable take-off rows present in workspace.")

    # Determine Preflight Status
    if blocking_reasons:
        preflight_status = "BLOCKED"
    elif warnings:
        preflight_status = "AVAILABLE_WITH_WARNING"
    else:
        preflight_status = "AVAILABLE"

    # Internal Downloads (Excel/ZIP) availability
    if total_rows > 0:
        if preflight_status == "BLOCKED" or not required_coverage_complete or blocker_count > 0 or warning_count > 0:
            internal_download_state = "AVAILABLE_WITH_WARNING"
        else:
            internal_download_state = "AVAILABLE"
    else:
        internal_download_state = "UNAVAILABLE"

    # JobHub Draft Handoff availability: requires bridge, job ID, publishable rows, complete coverage, and unblocked preflight
    if (
        bridge_available
        and meta["jobhub_job_id"]
        and pub_rows > 0
        and required_coverage_complete
        and preflight_status != "BLOCKED"
    ):
        draft_handoff_state = "AVAILABLE_WITH_WARNING" if (blocker_count > 0 or warning_count > 0) else "AVAILABLE"
    else:
        draft_handoff_state = "UNAVAILABLE"

    # Final JobHub Publish Policy: STRICT GATES
    if not bridge_available or not meta["jobhub_job_id"]:
        final_publish_state = "UNAVAILABLE"
    elif preflight_status == "BLOCKED":
        final_publish_state = "BLOCKED"
    elif preflight_status == "AVAILABLE_WITH_WARNING":
        final_publish_state = "AVAILABLE_WITH_WARNING"
    else:
        final_publish_state = "AVAILABLE"

    # Compute Deterministic Canonical Review & Preflight Fingerprints
    review_fp = compute_canonical_review_fingerprint(review_res)

    fingerprint_data = {
        "workspace_id": workspace_id,
        "job_no": meta["job_no"],
        "drawing_issue": meta["drawing_issue"],
        "review_fingerprint": review_fp,
        "preflight_status": preflight_status,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "blocking_reasons": blocking_reasons,
        "pub_rows": pub_rows,
        "payload_hash": payload_hash,
    }
    raw_json = json.dumps(fingerprint_data, sort_keys=True, allow_nan=False)
    preflight_fingerprint = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    return CommercialPreflightResult(
        workspace_id=workspace_id,
        job_no=meta["job_no"],
        job_name=meta["job_name"],
        drawing_issue=meta["drawing_issue"],
        jobhub_job_id=meta["jobhub_job_id"],
        preflight_status=preflight_status,
        blocker_count=blocker_count,
        warning_count=warning_count,
        info_count=info_count,
        total_review_items=len(signals),
        required_coverage_complete=required_coverage_complete,
        unavailable_required_sources=unavailable_sources,
        internal_download_state=internal_download_state,
        draft_handoff_state=draft_handoff_state,
        final_publish_state=final_publish_state,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
        review_fingerprint=review_fp,
        preflight_fingerprint=preflight_fingerprint,
        payload_hash=payload_hash,
        total_takeoff_rows=total_rows,
        publishable_takeoff_rows=pub_rows,
        excluded_takeoff_rows=excl_rows,
        floor_reference_rows=floor_rows,
        measured_zero_rows=zero_rows,
    )


def verify_toctou_and_publish_jobhub(
    conn_or_app: Any,
    workspace_id: int,
    bridge: Any,
    user_name: str,
    expected_fingerprint: str,
    acknowledgement_confirmed: bool,
    publish_fn: Any
) -> dict[str, Any]:
    """Time-Of-Check / Time-Of-Use (TOCTOU) Protected JobHub Final Publish Gate.

    Re-derives Phase 6B review, fresh Phase 6D preflight, and payload hash immediately prior to calling downstream
    final publish. Raises RuntimeError if state changed, payload mutated, or blocked.
    Checks server/downstream level for existing duplicate package to enforce true double-submit safety.
    """
    if not bridge:
        raise RuntimeError("JobHub bridge unavailable for final publish.")

    preflight = derive_export_preflight(conn_or_app, workspace_id, bridge_available=True)

    if preflight.final_publish_state == "BLOCKED":
        reasons_str = "; ".join(preflight.blocking_reasons)
        raise RuntimeError(f"Final publish blocked by preflight QA gate: {reasons_str}")

    if preflight.final_publish_state == "UNAVAILABLE":
        raise RuntimeError("Final publish is unavailable. Link workspace to a valid JobHub job.")

    if preflight.preflight_fingerprint != expected_fingerprint:
        raise RuntimeError("Project QA/export state changed. Review the updated preflight before publishing.")

    if preflight.preflight_status == "AVAILABLE_WITH_WARNING" and not acknowledgement_confirmed:
        raise RuntimeError("Typed acknowledgement required to publish a project with REVIEW warnings.")

    # Server / Downstream Level Duplicate Guard: Check existing JobHub packages for matching preflight fingerprint in notes
    job_id = preflight.jobhub_job_id
    if job_id:
        try:
            from pb_planreader_3d_app import ensure_jobhub_takeoff_tables
            ensure_jobhub_takeoff_tables(bridge)
        except Exception:
            pass
        try:
            query_sql = "SELECT id, takeoff_no, notes FROM painting_takeoff_packages WHERE job_id=? AND status='Published' ORDER BY id DESC"
            existing_pkgs = bridge.query(query_sql, (job_id,))
            for pkg in existing_pkgs:
                notes_str = str(pkg.get("notes") or "")
                if preflight.preflight_fingerprint in notes_str or preflight.payload_hash in notes_str:
                    raise RuntimeError(f"Package for preflight fingerprint {preflight.preflight_fingerprint[:12]}... has already been published to JobHub for job #{job_id} (Package #{pkg.get('id')}).")
        except RuntimeError:
            raise
        except (sqlite3.OperationalError, sqlite3.DatabaseError, TypeError, ValueError, AttributeError) as exc:
            if "no such table" not in str(exc).lower():
                raise RuntimeError(f"Duplicate verification failed closed: unable to query existing JobHub packages ({exc}).") from exc

    # Safely determine signature BEFORE invocation to prevent double-invocation on internal TypeError
    supports_kwargs = True
    try:
        sig = inspect.signature(publish_fn)
        params = sig.parameters
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        supports_kwargs = has_var_keyword or ("preflight_fingerprint" in params and "payload_hash" in params)
    except (ValueError, TypeError):
        # Fall back to modern call if signature cannot be inspected (e.g. built-in/extension)
        supports_kwargs = True

    if supports_kwargs:
        result = publish_fn(
            workspace_id,
            bridge,
            user_name,
            preflight_fingerprint=preflight.preflight_fingerprint,
            payload_hash=preflight.payload_hash
        )
    else:
        result = publish_fn(workspace_id, bridge, user_name)
    if not isinstance(result, dict) or not result.get("package_id"):
        raise RuntimeError("Downstream final publish failed to generate a valid JobHub package receipt.")

    # Ensure partial failures bubble up cleanly
    if not result.get("published", True):
        raise RuntimeError(f"Final publish partially failed on JobHub job #{result.get('job_id')}. Details: {result}")

    result["preflight_fingerprint"] = preflight.preflight_fingerprint
    result["review_fingerprint"] = preflight.review_fingerprint
    result["payload_hash"] = preflight.payload_hash
    return result
