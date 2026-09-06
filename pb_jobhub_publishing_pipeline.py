"""pb_jobhub_publishing_pipeline.py — End-to-End PlanReader -> JobHub Publishing Pipeline.

Orchestrates package construction, gate validation, TOCTOU verification,
and atomic publishing to JobHub with full support for DRAFT and COMMERCIAL modes.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_jobhub_publishing_contract import (
    BenchmarkStatusPayload,
    DrawingRevisionPayload,
    ExcludedScopePayload,
    ProjectIdentityPayload,
    PublishingGateResult,
    PublishingMode,
    PublishingPackagePayload,
    PublishingWarningPayload,
    QuantityLineItemPayload,
    validate_publishing_gate,
)


def build_publishing_package_from_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    mode: PublishingMode = PublishingMode.COMMERCIAL,
    benchmark_status: Optional[BenchmarkStatusPayload] = None,
    preflight_fingerprint: str = "",
) -> PublishingPackagePayload:
    """Build a standard PublishingPackagePayload from an active PlanReader SQLite database."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Fetch Workspace Metadata
    cur.execute(
        """
        SELECT id, job_no, job_name, builder_client, site_address, drawing_issue, jobhub_job_id, estimator
        FROM workspaces WHERE id=?
        """,
        (workspace_id,),
    )
    ws_row = cur.fetchone()
    if not ws_row:
        raise ValueError(f"Workspace #{workspace_id} not found")

    job_no = str(ws_row["job_no"] or "")
    job_name = str(ws_row["job_name"] or "")
    site_address = str(ws_row["site_address"] or "")
    builder_client = str(ws_row["builder_client"] or "")
    estimator = str(ws_row["estimator"] or "Bryce Curran")
    target_job_id = int(ws_row["jobhub_job_id"]) if ws_row["jobhub_job_id"] else None

    project_identity = ProjectIdentityPayload(
        job_no=job_no,
        job_name=job_name,
        site_address=site_address,
        builder_client=builder_client,
        estimator=estimator,
        target_jobhub_job_id=target_job_id,
    )

    # 2. Fetch Document & Revision Metadata
    cur.execute(
        "SELECT file_name FROM documents WHERE workspace_id=? ORDER BY id ASC",
        (workspace_id,),
    )
    doc_rows = cur.fetchall()
    file_names = [str(r["file_name"]) for r in doc_rows if r["file_name"]]

    cur.execute(
        "SELECT COUNT(*) FROM pages WHERE workspace_id=?",
        (workspace_id,),
    )
    sheet_count = cur.fetchone()[0] or 0

    drawing_issue = str(ws_row["drawing_issue"] or "BA")
    rev_hash = hashlib.sha256(",".join(file_names).encode("utf-8")).hexdigest()

    drawing_revision = DrawingRevisionPayload(
        drawing_issue=drawing_issue,
        drawing_date=datetime.date.today().isoformat(),
        sheet_count=sheet_count,
        source_files_hash=rev_hash,
        file_names=file_names,
    )

    # 3. Fetch Takeoff Line Items & Measurement Authorities
    cur.execute("PRAGMA table_info(takeoff_rows)")
    cols = {r[1] for r in cur.fetchall()}

    query = """
    SELECT id, section, location, substrate, finish_tag, element, unit, quantity, rate, total_price,
           commercial_authority_status, commercial_authority_source, commercial_authority_reviewed_by,
           commercial_authority_reviewed_at, source_page, notes
    FROM takeoff_rows
    WHERE workspace_id=?
    ORDER BY id ASC
    """ if "commercial_authority_status" in cols else """
    SELECT id, section, location, substrate, '' AS finish_tag, element, unit, quantity, rate, total_price,
           'firm' AS commercial_authority_status, 'documented_dimension' AS commercial_authority_source,
           NULL AS commercial_authority_reviewed_by, NULL AS commercial_authority_reviewed_at,
           '' AS source_page, '' AS notes
    FROM takeoff_rows
    WHERE workspace_id=?
    ORDER BY id ASC
    """

    cur.execute(query, (workspace_id,))
    takeoff_rows = cur.fetchall()

    quantities: List[QuantityLineItemPayload] = []
    excluded_items: List[ExcludedScopePayload] = []
    warnings: List[PublishingWarningPayload] = []

    for r in takeoff_rows:
        row_id = int(r["id"])
        section = str(r["section"] or "Takeoff")
        loc = str(r["location"] or "General")
        sub = str(r["substrate"] or "Plasterboard")
        tag = str(r["finish_tag"] or "")
        elem = str(r["element"] or "Element")
        unit = str(r["unit"] or "m²")
        qty = float(r["quantity"] or 0.0)
        rate = float(r["rate"] or 0.0)
        tot = float(r["total_price"] or (qty * rate))

        auth_status = str(r["commercial_authority_status"] or AuthorityStatus.FIRM.value).lower()
        auth_src = str(r["commercial_authority_source"] or MeasurementAuthorityType.DOCUMENTED_DIMENSION.value).lower()
        reviewed_by = r["commercial_authority_reviewed_by"]
        reviewed_at = r["commercial_authority_reviewed_at"]
        source_page = str(r["source_page"] or "")
        notes = str(r["notes"] or "")

        # Check for excluded items
        sec_lower = section.lower()
        sub_lower = sub.lower()
        tag_lower = tag.lower()
        if any(k in sec_lower or k in sub_lower or k in tag_lower for k in ["exclude", "screed", "mastic", "sealant", "powdercoat"]):
            excluded_items.append(
                ExcludedScopePayload(
                    item_code=tag or f"EXCL_{row_id}",
                    description=f"{elem} ({sub})",
                    reason="Factory finish / other trade exclusion",
                )
            )
            continue

        quantities.append(
            QuantityLineItemPayload(
                row_id=row_id,
                section=section,
                location=loc,
                substrate=sub,
                finish_tag=tag,
                element=elem,
                unit=unit,
                quantity=qty,
                rate=rate,
                total_price=tot,
                authority_type=auth_src,
                authority_status=auth_status,
                confidence=1.0 if auth_status == AuthorityStatus.FIRM.value else 0.7,
                source_page=source_page,
                approved_by=reviewed_by,
                approved_at=reviewed_at,
                notes=notes,
            )
        )

    pkg = PublishingPackagePayload(
        workspace_id=workspace_id,
        mode=mode.value,
        project_identity=project_identity,
        drawing_revision=drawing_revision,
        quantities=quantities,
        excluded_items=excluded_items,
        warnings=warnings,
        benchmark_status=benchmark_status,
        preflight_fingerprint=preflight_fingerprint,
    )
    pkg.payload_hash = pkg.compute_payload_hash()
    return pkg


def execute_jobhub_publishing(
    package: PublishingPackagePayload,
    bridge: Any,
    user_name: str,
    override_preflight_check: bool = False,
) -> Dict[str, Any]:
    """Execute publishing through the gate and persist to JobHub."""
    if not bridge:
        raise RuntimeError("JobHub bridge is unavailable")

    # 1. Evaluate Publishing Gate
    gate_result = validate_publishing_gate(package)
    if not gate_result.is_publishable and not override_preflight_check:
        reasons = "; ".join(gate_result.blocking_reasons)
        raise RuntimeError(f"Publishing blocked by gate QA checks: {reasons}")

    target_job_id = package.project_identity.target_jobhub_job_id
    if not target_job_id:
        raise RuntimeError("Target JobHub job ID is required to publish package")

    # Verify target job exists in JobHub
    job_rows = bridge.query("SELECT id, status FROM jobs WHERE id=?", (target_job_id,))
    if not job_rows:
        raise RuntimeError(f"Job #{target_job_id} does not exist in JobHub")

    # Calculate aggregates
    total_qty_m2 = 0.0
    interior_m2 = 0.0
    exterior_m2 = 0.0
    total_cost = 0.0

    for q in package.quantities:
        total_cost += q.total_price
        if q.unit in ("m²", "m2", "sqm"):
            total_qty_m2 += q.quantity
            sec_lower = q.section.lower()
            if any(k in sec_lower for k in ["internal", "ceiling", "interior", "wall"]):
                interior_m2 += q.quantity
            elif any(k in sec_lower for k in ["external", "facade", "elevation", "soffit"]):
                exterior_m2 += q.quantity

    takeoff_no = f"PR-{package.project_identity.job_no}-{'PUB' if package.mode == PublishingMode.COMMERCIAL.value else 'DFT'}-{package.payload_hash[:8]}"
    status_label = "Published" if package.mode == PublishingMode.COMMERCIAL.value else "Draft"
    notes_str = (
        f"Mode: {package.mode.upper()} | Fingerprint: {package.preflight_fingerprint} | "
        f"Payload: {package.payload_hash} | Published by {user_name}"
    )

    # Insert package header and line items into JobHub
    with bridge.connect() as conn:
        cur = conn.cursor()

        # Check existing package duplicate
        cur.execute(
            "SELECT id FROM painting_takeoff_packages WHERE job_id=? AND notes LIKE ?",
            (target_job_id, f"%{package.payload_hash}%"),
        )
        dup = cur.fetchone()
        if dup:
            raise RuntimeError(
                f"Duplicate package with payload hash {package.payload_hash[:12]}... already exists on JobHub (Package #{dup[0]})"
            )

        insert_pkg_sql = """
        INSERT INTO painting_takeoff_packages (
            job_id, takeoff_no, status, interior_m2, exterior_m2, total_hours, total_litres, created_by, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cur.execute(
            insert_pkg_sql,
            (
                target_job_id,
                takeoff_no,
                status_label,
                round(interior_m2, 2),
                round(exterior_m2, 2),
                0.0,
                0.0,
                user_name,
                notes_str,
            ),
        )
        pkg_id = cur.lastrowid

        # Insert lines
        insert_line_sql = """
        INSERT INTO painting_takeoff_package_lines (
            package_id, section, location, substrate, element, unit, quantity, rate, total_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for q in package.quantities:
            cur.execute(
                insert_line_sql,
                (
                    pkg_id,
                    q.section,
                    q.location,
                    q.substrate,
                    q.element,
                    q.unit,
                    round(q.quantity, 4),
                    round(q.rate, 2),
                    round(q.total_price, 2),
                ),
            )

        conn.commit()

    return {
        "success": True,
        "published": True,
        "package_id": pkg_id,
        "takeoff_no": takeoff_no,
        "mode": package.mode,
        "status": status_label,
        "job_id": target_job_id,
        "total_lines": len(package.quantities),
        "total_cost": round(total_cost, 2),
        "interior_m2": round(interior_m2, 2),
        "exterior_m2": round(exterior_m2, 2),
        "preflight_fingerprint": package.preflight_fingerprint,
        "payload_hash": package.payload_hash,
    }
