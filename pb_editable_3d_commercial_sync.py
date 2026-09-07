"""pb_editable_3d_commercial_sync.py — Editable-3D -> Real Commercial Take-off Bridge (PR D.11H).

D.1-D.11G built a complete, self-contained correction/approval lifecycle
(Editable3DCorrectionLedger, TakeoffOutputRow) that has never written to the
app's real commercial take-off table, `takeoff_rows` — every D.11 PR through
D.11G said so explicitly. Separately, and independently, the app already has
a mature, production commercial-authority pipeline for `takeoff_rows` (Phase
6B/6D: pb_commercial_review_v161.py, pb_commercial_export_preflight_v163.py)
with its own row-level authority mechanism for exactly this situation —
"derived geometry that needs explicit, attributable review before it can
enter pricing, quotation, or JobHub publication" — model-surface rows
(pb_takeoff_authority_v164.py: is_model_surface_row / approve_model_surface_row
/ model_surface_authority). That mechanism is reused here verbatim.

This module is the pure logic for that bridge: given an editable-3D object
that D.11G has explicitly approved at its exact current revision, and one of
its current (non-stale) dependent TakeoffOutputRows, decide whether it is
eligible to be copied into `takeoff_rows` as a new model-surface row, and
build the row candidate that pb_takeoff_authority_v164.approve_model_surface_row()
turns into a genuinely, independently commercially-recognized row — never a
UI-only "is_publishable=True" shortcut. No DB access happens here; the
Streamlit panel owns the actual INSERT and the append-only sync-audit table
that makes repeated syncs of the same object/revision/quantity idempotent.

This is strictly additive and one-way: existing `takeoff_rows` rows are never
read back and modified by this module, and a later correction can never
silently rewrite a row this module already created — it only ever creates a
new row, once, for an explicitly approved exact revision.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from pb_editable_3d_correction_model import EditableGeometryObject
from pb_geometry_takeoff_model import AuthorityStatus
from pb_takeoff_authority_v164 import MODEL_SURFACE_ROLE
from pb_takeoff_output_authority import TakeoffOutputRow


def check_sync_eligibility(obj: EditableGeometryObject, row: TakeoffOutputRow) -> List[str]:
    """Fail-closed eligibility check for syncing one dependent quantity of an
    editable-3D object into the real commercial take-off. Every reason
    returned is a real, independent gate — this never overrides or relaxes
    D.11G's own authority rules or pb_takeoff_authority_v164's own
    commercial rules; it only adds the checks specific to crossing from one
    system into the other. Returns an empty list when eligible."""
    reasons: List[str] = []

    if obj.authority_status != AuthorityStatus.FIRM.value or not obj.approved_by:
        reasons.append(
            "Object is not explicitly approved (D.11G) at its current revision."
        )

    if row.revision_hash != obj.revision_hash:
        reasons.append(
            f"Quantity revision {row.revision_hash!r} does not match the "
            f"object's current revision {obj.revision_hash!r} — stale."
        )

    if row.authority_status != AuthorityStatus.USER_APPROVED.value or not row.is_publishable:
        reasons.append("Quantity is not commercially publishable.")

    if row.blocking_reasons:
        reasons.append(f"Quantity has blocking reasons: {', '.join(row.blocking_reasons)}")

    if not math.isfinite(row.value) or row.value < 0.0:
        reasons.append(f"Quantity value is non-finite or negative ({row.value!r}).")

    if obj.source_page is None or not obj.source_sheet:
        reasons.append(
            f"Object is missing source trace (source_page={obj.source_page!r}, "
            f"source_sheet={obj.source_sheet!r})."
        )

    return reasons


def build_model_surface_row_candidate(
    workspace_id: int, obj: EditableGeometryObject, row: TakeoffOutputRow,
) -> Dict[str, Any]:
    """Build the raw takeoff_rows-shaped dict for this quantity — every field
    pb_takeoff_authority_v164._AUTHORITY_BOUND_FIELDS reads is populated
    here so the resulting commercial-authority fingerprint (computed by
    approve_model_surface_row(), not this function) genuinely binds to real,
    traced values, not placeholders. row_role='model_surface' is the
    explicit, primary signal is_model_surface_row() uses to recognize this
    row — the existing Phase 6D pipeline's own classification, not a new one.
    Callers must still call approve_model_surface_row() on the result before
    inserting it — this function alone does not grant commercial authority.
    """
    return {
        "workspace_id": workspace_id,
        "section": "3D Model",
        "element": row.description,
        "location": obj.level_id or obj.object_id,
        "substrate": "",
        "finish_system": "",
        "quantity": row.value,
        "unit": row.unit,
        "quantity_status": "Measured",
        # takeoff_rows.source_page has TEXT column affinity — stringify here
        # so the pre-insert fingerprint (computed on this candidate) exactly
        # matches the value SQLite will actually store and later read back
        # as. Leaving this as obj.source_page's native int would compute a
        # fingerprint that can never match the row post-insert, permanently
        # revoking the very authority this sync just granted.
        "source_page": str(obj.source_page) if obj.source_page is not None else "",
        "source_reference": obj.source_sheet or "",
        "inclusion_status": "INCLUSION",
        "coats": 2,
        "coverage_m2_per_litre": 12,
        "productivity_m2_per_hour": 8,
        "rate_per_unit": 0,
        "confidence": "Verified",
        "notes": (
            f"Synced from Editable 3D Inspector. Object {obj.object_id}, "
            f"revision {obj.revision_hash}, corrected and approved by "
            f"{obj.approved_by} at {obj.approved_at}."
        ),
        "row_role": MODEL_SURFACE_ROLE,
        "ai_baseline_quantity": None,
        "pre_map_quantity": None,
        "pre_map_quantity_status": None,
        "origin": "",
    }
