"""pb_editable_3d_inspector_panel.py — Editable 3D Inspector Panel (PR D.11A).

A read-only Streamlit panel that surfaces the real editable-3D correction/
approval/quantity backend (D.1-D.10) inside the PlanReader app. No mutation
controls, no database persistence, no new authority logic — this panel only
displays state produced by the actual backend functions:

  pb_editable_3d_correction_model.Editable3DCorrectionLedger / EditableGeometryObject
  pb_editable_3d_quantity_recalculation.recalculate_quantities_for_correction
  pb_takeoff_output_authority.TakeoffOutputRow / create_takeoff_output_row / approve_takeoff_output_row

Because nothing in the application persists editable-3D objects to the
database yet (that's D.11B's job), this panel demonstrates real backend
behaviour via an in-session demo scenario, built entirely from actual backend
calls — not fabricated data, not new logic. Loading the scenario runs one
correction and one approval through the real pipeline once, up front; the
panel itself never calls a correction or approval function in response to a
user action.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from pb_geometry_takeoff_model import AuthorityStatus
from pb_editable_3d_correction_model import (
    CorrectionField,
    CorrectionSource,
    Editable3DCorrectionLedger,
    EditableGeometryObject,
    EditableObjectType,
    approve_corrected_geometry,
)
from pb_editable_3d_quantity_recalculation import (
    RecalculationTarget,
    recalculate_quantities_for_correction,
)
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    approve_takeoff_output_row,
    create_takeoff_output_row,
)

_SESSION_LEDGER_KEY = "_editable_3d_inspector_ledger"
_SESSION_ROWS_KEY = "_editable_3d_inspector_rows"
_SESSION_BLOCK_REASON_KEY = "_editable_3d_inspector_block_reason"

# The ledger has no public "list all registered object ids" accessor (only
# events_for_object/corrected_object_ids, which only cover objects with at
# least one correction). These are exactly the ids this module registers in
# _build_demo_scenario, kept here rather than reaching into the ledger's
# private _objects field.
_DEMO_OBJECT_IDS: List[str] = ["WALL-DEMO-1", "WALL-DEMO-2", "WALL-DEMO-3"]


# ---------------------------------------------------------------------------
# Demo scenario — built entirely from real backend calls
# ---------------------------------------------------------------------------

def _build_demo_scenario() -> tuple[Editable3DCorrectionLedger, Dict[str, TakeoffOutputRow], str]:
    """Exercise the real D.1-D.10 pipeline once to produce inspectable state:
    one object corrected-but-unapproved, one object corrected-and-approved,
    and one untraceable object whose real approval attempt is captured and
    shown verbatim. Nothing here is fabricated data — every field shown in
    the panel comes from an actual EditableGeometryObject/TakeoffOutputRow
    produced by calling the real backend functions.
    """
    ledger = Editable3DCorrectionLedger()
    rows: Dict[str, TakeoffOutputRow] = {}

    # --- Object 1: traceable, corrected, NOT yet approved ------------------
    ledger.register_object(EditableGeometryObject(
        object_id="WALL-DEMO-1", object_type=EditableObjectType.WALL.value,
        source_file_id="FILE-DEMO-001", source_page=4, source_sheet="WD-04",
        source_region="B2:D6", geometry_ref="VEC-WALL-DEMO-1",
        scale_id="SCALE-P4-1_100", dimension_text_ids=["DIM-DEMO-1-LENGTH", "DIM-DEMO-1-HEIGHT"],
        confidence=0.92,
        coordinates_or_measurements={"length": 5.8, "height": 2.7, "openings": []},
        authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS-1",
    ))
    old_row_1 = create_takeoff_output_row(
        quantity_id="QTY-DEMO-1-GROSS", description="Demo Wall 1 — Gross Area", value=15.66,
        unit="m²", trade="painting", source_type=TakeoffSourceType.PDF_SCALED,
        source_page=4, source_sheet="WD-04", geometry_ref="WALL-DEMO-1", scale_id="SCALE-P4-1_100",
        revision_hash="GENESIS-1",
    )
    old_row_1 = approve_takeoff_output_row(old_row_1, approved_by="Estimator A", current_revision_hash="GENESIS-1")
    rows[old_row_1.quantity_id] = old_row_1

    outcome1 = ledger.apply_correction(
        correction_id="CORR-DEMO-1", object_id="WALL-DEMO-1",
        field=CorrectionField.LENGTH.value, new_value=6.0,
        reason="Corrected against site remeasure", actor="Field Estimator Jones",
        source=CorrectionSource.EDITOR_3D.value,
    )
    obj1_after = ledger.get_object("WALL-DEMO-1")
    results1 = recalculate_quantities_for_correction(
        outcome1.event, obj1_after, existing_rows=[old_row_1], ledger=ledger,
    )
    for r in results1:
        if r.old_row is not None:
            rows[r.old_row.quantity_id] = r.old_row
        if r.new_row is not None:
            rows[r.new_row.quantity_id] = r.new_row

    # --- Object 2: traceable, corrected AND approved ------------------------
    ledger.register_object(EditableGeometryObject(
        object_id="WALL-DEMO-2", object_type=EditableObjectType.WALL.value,
        source_file_id="FILE-DEMO-001", source_page=5, source_sheet="WD-05",
        source_region="A1:C5", geometry_ref="VEC-WALL-DEMO-2",
        scale_id="SCALE-P5-1_100", dimension_text_ids=["DIM-DEMO-2-LENGTH"],
        confidence=0.95,
        coordinates_or_measurements={"length": 4.5, "height": 2.7, "openings": []},
        authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS-2",
    ))
    old_row_2 = create_takeoff_output_row(
        quantity_id="QTY-DEMO-2-GROSS", description="Demo Wall 2 — Gross Area", value=12.15,
        unit="m²", trade="painting", source_type=TakeoffSourceType.PDF_SCALED,
        source_page=5, source_sheet="WD-05", geometry_ref="WALL-DEMO-2", scale_id="SCALE-P5-1_100",
        revision_hash="GENESIS-2",
    )
    old_row_2 = approve_takeoff_output_row(old_row_2, approved_by="Estimator A", current_revision_hash="GENESIS-2")
    rows[old_row_2.quantity_id] = old_row_2

    outcome2 = ledger.apply_correction(
        correction_id="CORR-DEMO-2", object_id="WALL-DEMO-2",
        field=CorrectionField.LENGTH.value, new_value=5.0,
        reason="Corrected against site remeasure", actor="Field Estimator Jones",
        source=CorrectionSource.EDITOR_3D.value,
    )
    obj2_after = ledger.get_object("WALL-DEMO-2")
    results2 = recalculate_quantities_for_correction(
        outcome2.event, obj2_after, existing_rows=[old_row_2], ledger=ledger,
    )
    for r in results2:
        if r.old_row is not None:
            rows[r.old_row.quantity_id] = r.old_row
        if r.new_row is not None:
            rows[r.new_row.quantity_id] = r.new_row

    approve_corrected_geometry(
        ledger, object_id="WALL-DEMO-2", approved_by="Lead Estimator Bryce",
        current_revision_hash=obj2_after.revision_hash,
    )
    gross2 = next(r for r in results2 if r.target == RecalculationTarget.WALL_GROSS_AREA.value)
    approved_new_row_2 = approve_takeoff_output_row(
        gross2.new_row, approved_by="Lead Estimator Bryce",
        current_revision_hash=obj2_after.revision_hash,
    )
    rows[approved_new_row_2.quantity_id] = approved_new_row_2

    # --- Object 3: untraceable — approval is attempted and its real failure
    #     message is captured verbatim, not fabricated. --------------------
    ledger.register_object(EditableGeometryObject(
        object_id="WALL-DEMO-3", object_type=EditableObjectType.WALL.value,
        source_file_id=None, source_page=None, source_sheet=None,
        geometry_ref="VEC-WALL-DEMO-3",
        coordinates_or_measurements={"length": 4.0, "height": 2.7, "openings": []},
        authority_status=AuthorityStatus.PROVISIONAL.value, revision_hash="GENESIS-3",
    ))
    block_reason = ""
    try:
        approve_corrected_geometry(
            ledger, object_id="WALL-DEMO-3", approved_by="Estimator A",
            current_revision_hash="GENESIS-3",
        )
    except ValueError as exc:
        block_reason = str(exc)

    return ledger, rows, block_reason


def _ensure_demo_scenario_loaded() -> None:
    if _SESSION_LEDGER_KEY not in st.session_state:
        ledger, rows, block_reason = _build_demo_scenario()
        st.session_state[_SESSION_LEDGER_KEY] = ledger
        st.session_state[_SESSION_ROWS_KEY] = rows
        st.session_state[_SESSION_BLOCK_REASON_KEY] = block_reason


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _authority_badge(status: str) -> str:
    if status == AuthorityStatus.FIRM.value:
        return "\U0001F7E2 FIRM"
    if status == AuthorityStatus.USER_APPROVED.value:
        return "\U0001F7E2 USER_APPROVED"
    if status == AuthorityStatus.PROVISIONAL.value:
        return "\U0001F7E1 PROVISIONAL"
    if status == AuthorityStatus.REVIEW_REQUIRED.value:
        return "\U0001F7E1 REVIEW_REQUIRED"
    if status == AuthorityStatus.BLOCKED.value:
        return "\U0001F534 BLOCKED"
    return f"⚪ {status}"


def _publishable_badge(is_publishable: bool) -> str:
    return "✅ PUBLISHABLE" if is_publishable else "⛔ NOT PUBLISHABLE (provisional/blocked)"


def _render_object_summary(obj: EditableGeometryObject) -> None:
    st.subheader(f"{obj.object_id}  ({obj.object_type})")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption("Source file")
        st.write(obj.source_file_id or "—")
        st.caption("Source page")
        st.write(obj.source_page if obj.source_page is not None else "—")
        st.caption("Source sheet")
        st.write(obj.source_sheet or "—")
    with col2:
        st.caption("Geometry ref (current)")
        st.write(obj.geometry_ref or "—")
        st.caption("Geometry ref (original)")
        st.write(obj.original_geometry_ref or "—")
        st.caption("Scale ID")
        st.write(obj.scale_id or "—")
    with col3:
        st.caption("Dimension text ID(s)")
        st.write(", ".join(obj.dimension_text_ids) if obj.dimension_text_ids else "—")
        st.caption("Confidence")
        st.write(f"{obj.confidence:.2f}")

    is_traceable = bool(obj.source_page is not None and obj.source_sheet)
    if is_traceable:
        st.success("TRACEABLE — source page and sheet are recorded.")
    else:
        st.error("UNTRACEABLE — missing source page/sheet. This object cannot be approved.")

    st.markdown("**Current geometry values**")
    st.json({k: v for k, v in obj.coordinates_or_measurements.items() if k != "openings"})

    st.markdown("**Revision & authority**")
    rcol1, rcol2, rcol3 = st.columns(3)
    with rcol1:
        st.caption("Current revision hash")
        st.code(obj.revision_hash or "—")
    with rcol2:
        st.caption("Authority status")
        st.write(_authority_badge(obj.authority_status))
    with rcol3:
        is_approved = bool(obj.approved_by)
        st.caption("Approval status")
        if is_approved:
            st.success(f"APPROVED by {obj.approved_by}\n\n{obj.approved_at}")
        else:
            corrected = bool(obj.correction_ids)
            if corrected:
                st.warning("CORRECTED ≠ APPROVED — this object has been corrected but has no approver.")
            else:
                st.info("Not yet corrected or approved.")

    st.markdown("**Correction history** (append-only, from the real ledger)")
    if obj.correction_ids:
        st.write(f"correction_ids: {obj.correction_ids}")
    else:
        st.caption("No corrections recorded.")


def _render_correction_events(ledger: Editable3DCorrectionLedger, object_id: str) -> None:
    events = ledger.events_for_object(object_id)
    if not events:
        st.caption("No correction events for this object.")
        return
    for e in events:
        with st.expander(f"{e.correction_id} — {e.field}: {e.old_value} → {e.new_value}"):
            st.write(f"**Reason:** {e.reason}")
            st.write(f"**Actor:** {e.actor}")
            st.write(f"**Source:** {e.source}")
            st.write(f"**Created at:** {e.created_at}")
            st.write(f"**Previous revision hash:** `{e.previous_revision_hash}`")
            st.write(f"**New revision hash:** `{e.new_revision_hash}`")


def _render_linked_quantities(obj: EditableGeometryObject, rows: Dict[str, TakeoffOutputRow]) -> None:
    st.markdown("**Dependent quantities**")
    if not obj.dependent_quantity_ids:
        st.caption("No linked quantities.")
        return
    for qid in obj.dependent_quantity_ids:
        row = rows.get(qid)
        if row is None:
            st.warning(f"{qid} — not found among known rows (would not resolve)")
            continue
        with st.expander(f"{qid} — {row.value} {row.unit} — {_publishable_badge(row.is_publishable)}"):
            c1, c2 = st.columns(2)
            with c1:
                st.caption("Authority status")
                st.write(_authority_badge(row.authority_status))
                st.caption("Revision hash")
                st.code(row.revision_hash or "—")
                st.caption("Correction ID")
                st.write(row.correction_id or "—")
            with c2:
                st.caption("Approved by / at")
                st.write(f"{row.approved_by or '—'} / {row.approved_at or '—'}")
                stale = "stale_after_geometry_correction" in row.blocking_reasons
                st.caption("Current vs stale")
                st.write("\U0001F534 STALE" if stale else "\U0001F7E2 CURRENT")

            st.caption("Blocking reasons")
            st.write(row.blocking_reasons if row.blocking_reasons else "None")
            st.caption("Warnings")
            st.write(row.warnings if row.warnings else "None")


# ---------------------------------------------------------------------------
# Panel entry point
# ---------------------------------------------------------------------------

def render_editable_3d_inspector_panel(workspace: Optional[Dict[str, Any]] = None) -> None:
    """Read-only inspector for the editable-3D correction/approval/quantity
    backend (D.1-D.10). No mutation controls. No database persistence.

    Nothing in the application persists editable-3D objects to the database
    yet, so this panel loads a demo scenario built from real backend calls
    (see _build_demo_scenario) to have real state to display. That call
    happens once per session, not on every rerun, and is not triggered by any
    user interaction with the panel itself.
    """
    st.title("Editable 3D Inspector")
    st.caption(
        "Read-only view of the correction/approval/quantity backend (D.1–D.10). "
        "No corrections or approvals can be made from this panel."
    )
    st.info(
        "This panel currently displays an in-session demo scenario built from real "
        "backend calls (Editable3DCorrectionLedger, recalculate_quantities_for_correction, "
        "approve_corrected_geometry, create_takeoff_output_row) — nothing here is "
        "persisted to the database yet. Wiring real workspace objects is D.11B."
    )

    _ensure_demo_scenario_loaded()
    ledger: Editable3DCorrectionLedger = st.session_state[_SESSION_LEDGER_KEY]
    rows: Dict[str, TakeoffOutputRow] = st.session_state[_SESSION_ROWS_KEY]
    block_reason: str = st.session_state[_SESSION_BLOCK_REASON_KEY]

    selected = st.selectbox("Select an editable 3D object", _DEMO_OBJECT_IDS)
    obj = ledger.get_object(selected)
    if obj is None:
        st.error(f"Object {selected!r} not found in the ledger.")
        return

    _render_object_summary(obj)

    if selected == "WALL-DEMO-3" and block_reason:
        st.error(f"Real approval attempt on this object failed closed:\n\n{block_reason}")

    st.divider()
    st.markdown("### Correction event log")
    _render_correction_events(ledger, selected)

    st.divider()
    _render_linked_quantities(obj, rows)
