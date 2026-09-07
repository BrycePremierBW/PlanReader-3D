"""pb_editable_3d_inspector_panel.py — Editable 3D Inspector Panel (PR D.11A-G).

A Streamlit panel that surfaces the real editable-3D correction/approval/
quantity backend (D.1-D.10) inside the PlanReader app. No new authority
logic — every state shown or produced here comes from the actual backend
functions:

  pb_editable_3d_correction_model.Editable3DCorrectionLedger / EditableGeometryObject
  pb_editable_3d_quantity_recalculation.recalculate_quantities_for_correction
  pb_takeoff_output_authority.TakeoffOutputRow / create_takeoff_output_row / approve_takeoff_output_row
  pb_editable_3d_workspace_hydration.hydrate_masses_to_wall_models (D.11B)
  pb_editable_3d_workspace_viewer.build_workspace_3d_figure (D.11C)
  pb_editable_3d_correction_persistence.replay_persisted_corrections (D.11F)

Through D.11D this panel was purely read-only. D.11E added one mutation
control — a length/height correction on a single real wall — kept
session-only at first. D.11F persists it for real (see "Persisted
corrections" below), and D.11F.1 made the corrected object's own geometry
canonically self-consistent before D.11G's approval workflow could safely
build on it. D.11G adds the second and final mutation control: an explicit,
single-object, exact-revision approval (see "Persisted approvals" below).

The panel offers two data sources, switchable at the top of the page:

  - "Demo scenario" (D.11A): an in-session scenario built entirely from real
    backend calls (not fabricated data, not new logic), used to prove the
    four authority distinctions with objects nothing in the app persists yet.
  - "Real workspace objects" (D.11B/D.11C/D.11D): the current workspace's
    actual `model_masses`/`model_openings`/`mapped_zones` rows, hydrated
    fresh on every render via pb_editable_3d_workspace_hydration — no
    caching, no DB writes, always reflecting the live database state —
    rendered as an interactive, read-only 3D scene (orbit/pan/zoom,
    hover-to-identify, real room/floor footprints) alongside the same
    inspector detail view D.11A introduced. Object selection is via the
    dropdown, not by clicking inside the 3D canvas: Plotly.js does not fire
    click/selection events for 3D scatter traces (confirmed empirically —
    hover works reliably, click never reaches Streamlit's on_select), so
    building the "click a wall to select it" flow on top of it would be
    presenting a control that silently does nothing. The dropdown's current
    selection is instead drawn highlighted in the 3D scene itself (D.11D),
    so the selected object is obvious in both places at once.

A "Legend" expander (D.11D) at the top of the page explains what every
color/badge means across both the 3D view and the detail sections below.

Persisted corrections (D.11F): "Real workspace objects" mode has a "Correct
{wall_id}" expander for whichever wall is currently selected. It calls
Editable3DCorrectionLedger.apply_correction() verbatim — no new authority
logic — to correct that one wall's length or height, then writes the
resulting event to `editable_3d_correction_events` (append-only) and upserts
`editable_3d_object_state` (a fast-lookup snapshot, never the thing replay
trusts blindly — see pb_editable_3d_correction_persistence). The original
`model_masses`/`model_openings` rows are only ever read, never written.

On every render, every persisted event for the workspace is replayed — in
the order it was originally recorded — through the exact same
apply_correction() pipeline a live correction uses
(replay_persisted_corrections()), so a correction genuinely survives a page
reload, navigating away and back, and a server restart. A correction always
lands the object at REVIEW_REQUIRED (the ledger's own invariant, not
re-derived here) with its dependent quantities staled/recalculated exactly
like the D.11A demo scenario already proves — the new quantity is real,
current, and explicitly NOT publishable until it is explicitly approved.
Correction is never approval.

Persisted approvals (D.11G): "Real workspace objects" mode also has an
"Approve {object_id}" expander for the selected object. It calls
approve_corrected_geometry() (D.1/D.2) verbatim, targeting the object's
*exact current* revision_hash and nothing else — approving a superseded
revision fails closed, the same as it always has. On success the result is
written to `editable_3d_approval_events` (append-only, a third table
alongside the two D.11F introduced) and `editable_3d_object_state` is
upserted the same way a correction upserts it. Every persisted event for
the workspace — corrections, then approvals — is replayed on every render
(replay_persisted_corrections() then replay_persisted_approvals()), so an
approval genuinely survives a page reload and a server restart exactly like
a correction does. A later correction on the same object clears
approved_by/approved_at and resets authority_status to REVIEW_REQUIRED
automatically (apply_correction()'s own unchanged invariant) — replay never
restores an approval whose revision_hash no longer matches the object's
current, corrected state. Once approved, the object's current dependent
quantity row is promoted through approve_takeoff_output_row() (D.1,
unchanged) and becomes publishable; the old/baseline row stays exactly as
stale and non-publishable as it already was.
"""
from __future__ import annotations

import uuid
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
from pb_editable_3d_model import WallModel
from pb_editable_3d_quantity_recalculation import (
    RecalculationTarget,
    get_affected_targets,
    recalculate_quantities_for_correction,
)
from pb_editable_3d_model_bridge import wall_model_to_editable_geometry_object
from pb_editable_3d_correction_persistence import (
    ReplayWarning,
    approval_result_to_row,
    correction_event_to_row,
    object_state_row,
    replay_persisted_approvals,
    replay_persisted_corrections,
    row_to_correction_event,
    verify_object_state_consistency,
)
from pb_editable_3d_workspace_hydration import HydrationSkip, hydrate_masses_to_wall_models
from pb_editable_3d_workspace_viewer import build_workspace_3d_figure
from pb_takeoff_output_authority import (
    TakeoffOutputRow,
    TakeoffSourceType,
    approve_takeoff_output_row,
    create_takeoff_output_row,
)

_SELECTED_REAL_OBJECT_KEY = "_editable_3d_inspector_selected_real"

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
# Real workspace objects (D.11B) — hydrated fresh from model_masses/model_openings
# on every render, never cached, never written back to the database.
# ---------------------------------------------------------------------------

def _load_real_workspace_objects(
    workspace: Dict[str, Any],
) -> tuple[Editable3DCorrectionLedger, List[WallModel], List[Dict[str, Any]], List[str], List[HydrationSkip]]:
    """Hydrate the current workspace's real `model_masses`/`model_openings` rows
    into WallModel -> EditableGeometryObject and register them into a fresh
    ledger; also fetch `mapped_zones` for the 3D viewer's optional floor/room
    footprints. A local import of `lquery` avoids a circular import at module
    load time (pb_planreader_3d_app imports this module; this function only
    needs pb_planreader_3d_app back once it is already fully loaded and
    running)."""
    from pb_planreader_3d_app import lquery

    workspace_id = int(workspace["id"])
    mass_rows = lquery("SELECT * FROM model_masses WHERE workspace_id=? ORDER BY id", (workspace_id,))
    opening_rows = lquery("SELECT * FROM model_openings WHERE workspace_id=? ORDER BY id", (workspace_id,))
    zone_rows = lquery("SELECT * FROM mapped_zones WHERE workspace_id=? ORDER BY id", (workspace_id,))
    result = hydrate_masses_to_wall_models(mass_rows, opening_rows)

    ledger = Editable3DCorrectionLedger()
    object_ids: List[str] = []
    for wall in result.walls:
        ledger.register_object(wall_model_to_editable_geometry_object(wall))
        object_ids.append(wall.wall_id)

    return ledger, result.walls, zone_rows, object_ids, result.skipped


# ---------------------------------------------------------------------------
# Persisted corrections (D.11F) — real, append-only history in
# editable_3d_correction_events/editable_3d_object_state. Replayed fresh on
# top of live-hydrated geometry on every render (never trusted as a cached
# snapshot); survives reload, navigation, and a server restart. The original
# model_masses/model_openings rows are only ever read, never written.
# ---------------------------------------------------------------------------

_BASELINE_TARGET_INFO = {
    RecalculationTarget.WALL_LENGTH.value: ("length_m", "m", "Length"),
    RecalculationTarget.WALL_GROSS_AREA.value: ("gross_area_m2", "m²", "Gross Area"),
    RecalculationTarget.WALL_NET_AREA.value: ("net_area_m2", "m²", "Net Area"),
}


def _build_baseline_rows(wall: WallModel, targets: List[str]) -> List[TakeoffOutputRow]:
    """Real, currently-hydrated quantity values for the wall, expressed as
    TakeoffOutputRow so recalculate_quantities_for_correction() has something
    real to stale/replace. Never claiming authority the wall doesn't
    actually have: MODEL_DERIVED, unapproved — exactly what such a row would
    be if the app tracked take-off quantities for real workspace geometry
    today (it doesn't yet — there's still no schema link from model_masses
    to takeoff_rows)."""
    rows: List[TakeoffOutputRow] = []
    for target in targets:
        info = _BASELINE_TARGET_INFO.get(target)
        if info is None:
            continue
        attr, unit, label = info
        rows.append(create_takeoff_output_row(
            quantity_id=f"{wall.wall_id}-{target}-BASELINE",
            description=f"Wall {wall.wall_id} — {label}",
            value=getattr(wall, attr), unit=unit, trade="general",
            source_type=TakeoffSourceType.MODEL_DERIVED,
            source_page=wall.source_page_no or None, source_sheet=wall.source_sheet_label or None,
            geometry_ref=wall.wall_id, revision_hash=wall.revision_hash,
        ))
    return rows


def _load_persisted_correction_state(
    workspace_id: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fetch this workspace's persisted correction history. A local import of
    `lquery` avoids a circular import at module load time (see
    _load_real_workspace_objects for the same pattern)."""
    from pb_planreader_3d_app import lquery

    event_rows = lquery(
        "SELECT * FROM editable_3d_correction_events WHERE workspace_id=? ORDER BY id",
        (workspace_id,),
    )
    state_rows = lquery(
        "SELECT * FROM editable_3d_object_state WHERE workspace_id=?",
        (workspace_id,),
    )
    return event_rows, state_rows


def _upsert_object_state(workspace_id: int, obj: EditableGeometryObject) -> None:
    """Upsert the object's current-state snapshot — a fast-lookup cache the
    ledger's own replay always double-checks (see
    verify_object_state_consistency), never a thing hydration trusts
    blindly. Shared by both correction and approval persistence, since both
    actions change this same row."""
    from pb_planreader_3d_app import lexecute

    state = object_state_row(workspace_id, obj)
    lexecute(
        """INSERT INTO editable_3d_object_state(
            workspace_id, object_id, authority_status, approved_by, approved_at,
            revision_hash, correction_ids_json, updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(workspace_id, object_id) DO UPDATE SET
            authority_status=excluded.authority_status,
            approved_by=excluded.approved_by,
            approved_at=excluded.approved_at,
            revision_hash=excluded.revision_hash,
            correction_ids_json=excluded.correction_ids_json,
            updated_at=excluded.updated_at""",
        (
            state["workspace_id"], state["object_id"], state["authority_status"],
            state["approved_by"], state["approved_at"], state["revision_hash"],
            state["correction_ids_json"], state["updated_at"],
        ),
    )


def _save_correction(workspace_id: int, event, obj: EditableGeometryObject) -> None:
    """Append the new correction event and upsert the object's current-state
    snapshot. Two writes, both additive: the event log is genuinely
    append-only (no UPDATE/DELETE), and the object-state row is a fast-lookup
    cache (see _upsert_object_state). Neither statement touches
    model_masses/model_openings."""
    from pb_planreader_3d_app import lexecute

    row = correction_event_to_row(workspace_id, event)
    lexecute(
        """INSERT INTO editable_3d_correction_events(
            workspace_id, correction_id, object_id, object_type, field,
            old_value_json, new_value_json, reason, actor, source,
            previous_revision_hash, new_revision_hash, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["workspace_id"], row["correction_id"], row["object_id"], row["object_type"],
            row["field"], row["old_value_json"], row["new_value_json"], row["reason"],
            row["actor"], row["source"], row["previous_revision_hash"], row["new_revision_hash"],
            row["created_at"],
        ),
    )
    _upsert_object_state(workspace_id, obj)


def _load_persisted_approval_state(workspace_id: int) -> List[Dict[str, Any]]:
    """Fetch this workspace's persisted approval history, in append-only
    (id) order — see _load_persisted_correction_state for the same
    pattern."""
    from pb_planreader_3d_app import lquery

    return lquery(
        "SELECT * FROM editable_3d_approval_events WHERE workspace_id=? ORDER BY id",
        (workspace_id,),
    )


def _save_approval(workspace_id: int, object_type: str, result, obj: EditableGeometryObject) -> None:
    """Append the new approval event and upsert the object's current-state
    snapshot. The approval event log is append-only, exactly like the
    correction event log — an approval is never edited or deleted, only
    ever superseded by a later correction or a later approval event."""
    from pb_planreader_3d_app import lexecute

    row = approval_result_to_row(workspace_id, object_type, result)
    lexecute(
        """INSERT INTO editable_3d_approval_events(
            workspace_id, object_id, object_type, revision_hash,
            approved_by, approved_at, created_at
        ) VALUES(?,?,?,?,?,?,?)""",
        (
            row["workspace_id"], row["object_id"], row["object_type"], row["revision_hash"],
            row["approved_by"], row["approved_at"], row["created_at"],
        ),
    )
    _upsert_object_state(workspace_id, obj)


def _build_dependent_quantity_rows(
    ledger: Editable3DCorrectionLedger,
    original_walls_by_id: Dict[str, WallModel],
    event_rows: List[Dict[str, Any]],
) -> Dict[str, TakeoffOutputRow]:
    """For every object with at least one persisted correction, build the
    baseline (real, original, pre-any-correction) quantity rows and
    recalculate them against the object's final replayed state — the same
    stale-old/current-new pair D.11E already proved, now driven by the real
    persisted correction history instead of session state. Scoped to the
    single-wall-at-a-time acceptance criteria this series has kept to: the
    most recent persisted event's field decides which targets get
    recalculated, not the full cross-product of every field ever corrected.

    Approval (D.11G): if the object is currently approved — obj_after.approved_by
    is set — that approval is, by construction, always for obj_after's exact
    current revision_hash: apply_correction() clears approved_by/approved_at
    on every new correction (D.1's own invariant, unchanged), so a non-None
    approved_by here can never be stale. The newly-recalculated *current* row
    is promoted through approve_takeoff_output_row() (D.1, unchanged) so it
    becomes commercially eligible; the old/baseline row is never touched and
    stays exactly as stale/non-publishable as it already was."""
    rows: Dict[str, TakeoffOutputRow] = {}
    events_by_object: Dict[str, List[Dict[str, Any]]] = {}
    for row in event_rows:
        events_by_object.setdefault(row["object_id"], []).append(row)

    for object_id, db_rows in events_by_object.items():
        original_wall = original_walls_by_id.get(object_id)
        obj_after = ledger.get_object(object_id)
        if original_wall is None or obj_after is None or not db_rows:
            continue

        fields_corrected = {row["field"] for row in db_rows}
        targets: List[str] = []
        for field in fields_corrected:
            for t in get_affected_targets(EditableObjectType.WALL.value, field):
                if t not in targets:
                    targets.append(t)

        baseline_rows = _build_baseline_rows(original_wall, targets)
        for r in baseline_rows:
            rows[r.quantity_id] = r
        # Pre-link the baseline so it's still visible (now stale) after the
        # correction — recalculate_quantities_for_correction() only
        # auto-links the *new* row it produces, never the old one it replaces.
        ledger.link_dependent_quantities(object_id, [r.quantity_id for r in baseline_rows])

        latest_event = row_to_correction_event(db_rows[-1])
        results = recalculate_quantities_for_correction(
            latest_event, obj_after, existing_rows=baseline_rows, ledger=ledger,
        )
        for r in results:
            if r.old_row is not None:
                rows[r.old_row.quantity_id] = r.old_row
            if r.new_row is not None:
                new_row = r.new_row
                if obj_after.approved_by:
                    new_row = approve_takeoff_output_row(
                        new_row, approved_by=obj_after.approved_by,
                        approved_at=obj_after.approved_at,
                        current_revision_hash=obj_after.revision_hash,
                    )
                rows[new_row.quantity_id] = new_row

    return rows


def _render_correction_form(
    workspace_id: int, ledger: Editable3DCorrectionLedger, wall_id: str, wall: Optional[WallModel],
) -> None:
    """The one mutation control in this panel, deliberately narrow: one
    wall, one field (length or height) per submission, reusing
    Editable3DCorrectionLedger.apply_correction() verbatim — no new
    authority logic. A correction always lands REVIEW_REQUIRED (the
    ledger's own invariant, unchanged); there is no approval control here,
    on purpose — correction is never approval. Persisted for real (D.11F):
    written to this workspace's database, appended to a real audit trail
    (correction_id, actor, reason, both revision hashes, timestamp), never
    touching the original model_masses/model_openings rows."""
    existing_count = len(ledger.events_for_object(wall_id))
    label = f"\U0001F527 Correct {wall_id}" + (f" — {existing_count} persisted" if existing_count else "")
    with st.expander(label):
        st.info(
            "**Persisted.** This correction is written to this workspace's "
            "database and stays there — it survives a page reload and a "
            "server restart, unlike D.11E's earlier session-only demo. The "
            "original `model_masses`/`model_openings` rows are never "
            "modified, only read; every correction is an additional, "
            "append-only entry in this object's real correction history."
        )
        if wall is None:
            st.caption("Select a wall above first.")
            return

        field_choice = st.radio(
            "Field to correct", ["Length (m)", "Height (m)"],
            horizontal=True, key=f"_correction_field_{wall_id}",
        )
        field = CorrectionField.LENGTH.value if field_choice.startswith("Length") else CorrectionField.HEIGHT.value
        current_value = wall.length_m if field == CorrectionField.LENGTH.value else wall.height_m
        st.caption(f"Current {field}: {current_value:.2f} m")

        new_value = st.number_input(
            f"New {field_choice}", min_value=0.01, value=max(current_value, 0.01),
            step=0.05, key=f"_correction_value_{wall_id}",
        )
        reason = st.text_input(
            "Reason for this correction", key=f"_correction_reason_{wall_id}",
            placeholder="e.g. corrected against site remeasure",
        )
        actor = st.text_input("Your name", value="Estimator", key=f"_correction_actor_{wall_id}")

        if st.button("Apply correction", key=f"_correction_apply_{wall_id}"):
            if not reason.strip():
                st.error("A reason is required.")
            else:
                outcome = ledger.apply_correction(
                    correction_id=f"CORR-{wall_id}-{uuid.uuid4().hex[:10]}", object_id=wall_id,
                    field=field, new_value=float(new_value),
                    reason=reason.strip(), actor=actor.strip() or "Estimator",
                    source=CorrectionSource.EDITOR_3D.value,
                )
                if not outcome.ok:
                    st.error(f"Correction failed closed: {'; '.join(outcome.blocking_reasons)}")
                else:
                    obj_after = ledger.get_object(wall_id)
                    _save_correction(workspace_id, outcome.event, obj_after)
                    st.success(f"Correction saved to the database ({outcome.event.correction_id}).")
                    st.rerun()


def _render_approval_form(
    workspace_id: int, ledger: Editable3DCorrectionLedger, object_id: str, obj: EditableGeometryObject,
) -> None:
    """The one approval control in this panel (D.11G): explicit, single-object,
    exact-revision approval, reusing approve_corrected_geometry() (D.1/D.2)
    verbatim — no new authority logic. Approval always targets obj's exact
    current revision_hash as of the moment the button is clicked; there is
    no bulk approval, and there is no way to approve a past revision (the
    backend itself rejects a mismatched hash). A subsequent correction
    immediately invalidates this approval — apply_correction() already
    clears approved_by/approved_at and resets authority_status to
    REVIEW_REQUIRED on every new correction (D.1's own invariant, unchanged
    here), so nothing extra is needed to make re-approval mandatory after a
    later correction."""
    label = f"✅ Approve {object_id}"
    if obj.approved_by:
        label += f" — approved by {obj.approved_by}"
    with st.expander(label):
        st.info(
            f"Approves this object at its exact **current revision** only "
            f"(`{obj.revision_hash}`). If it is corrected again afterwards, "
            f"this approval no longer applies — the object automatically "
            f"returns to REVIEW_REQUIRED and must be approved again."
        )
        st.caption(f"Revision being approved: `{obj.revision_hash}`")
        actor = st.text_input(
            "Your name (required)", key=f"_approval_actor_{object_id}",
            placeholder="e.g. Lead Estimator",
        )
        if st.button("Approve current revision", key=f"_approval_apply_{object_id}"):
            if not actor.strip():
                st.error("An actor name is required to approve.")
            else:
                try:
                    result = approve_corrected_geometry(
                        ledger, object_id=object_id, approved_by=actor.strip(),
                        current_revision_hash=obj.revision_hash,
                    )
                except ValueError as exc:
                    st.error(f"Approval failed closed: {exc}")
                else:
                    obj_after = ledger.get_object(object_id)
                    _save_approval(workspace_id, obj.object_type, result, obj_after)
                    st.success(
                        f"Approved by {result.approved_by} at {result.approved_at} "
                        f"(revision `{result.revision_hash}`)."
                    )
                    st.rerun()


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


def _render_trust_legend() -> None:
    with st.expander("Legend — what the colors and statuses mean"):
        st.markdown(
            "**Authority status** (wall panels, markers, badges)\n"
            "- 🟢 FIRM / USER_APPROVED — explicitly approved at this exact "
            "revision (only `approve_corrected_geometry()` grants this, via "
            "the \"Approve {object_id}\" control)\n"
            "- 🟡 PROVISIONAL / REVIEW_REQUIRED — not yet approved; a "
            "correction always resets an object to REVIEW_REQUIRED, never "
            "straight to approved\n"
            "- 🔴 BLOCKED — height (or other authority) isn't known or "
            "trusted; drawn as a footprint outline only in the 3D view, "
            "never extruded to a guessed height\n\n"
            "**Quantity status** (dependent take-off rows — always present "
            "in demo mode; in real workspace objects, only once you've "
            "corrected that wall, since there's still no schema link from "
            "un-corrected building masses to real take-off rows)\n"
            "- 🟢 CURRENT — reflects the object's latest geometry\n"
            "- 🔴 STALE — a correction landed on the object since this "
            "quantity was computed\n"
            "- ✅ PUBLISHABLE / ⛔ NOT PUBLISHABLE — whether the row can "
            "enter commercial pricing right now\n\n"
            "**Room/floor footprints** (3D view, real workspace objects)\n"
            "- 🟢 filled green — an evidence-backed exact rectangle "
            "(Measured)\n"
            "- 🟡 filled amber — a real recorded shape, not yet proven "
            "exact (Provisional or a flagged approximation) — the real "
            "vertices are shown, never straightened into a rectangle they "
            "aren't\n"
            "- ⚪ dotted outline only — the zone has a real internal void; "
            "filling it solid would fabricate over a hole that genuinely "
            "exists\n"
        )


def _render_quick_summary(obj: EditableGeometryObject) -> None:
    """A one-line, at-a-glance summary shown right next to the selection
    control — the full breakdown (source trace, geometry, correction
    history, linked quantities) stays in the detailed sections below."""
    height = obj.coordinates_or_measurements.get("height")
    height_str = f"{height:.2f} m" if isinstance(height, (int, float)) else "—"
    if obj.source_page is not None:
        source = f"{obj.source_sheet or '—'} / p{obj.source_page}"
    else:
        source = obj.source_sheet or "—"
    st.info(
        f"**Selected: {obj.object_id}** ({obj.object_type}) — "
        f"{_authority_badge(obj.authority_status)} · height {height_str} · "
        f"source {source}"
    )


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
    """Inspector for the editable-3D correction/approval/quantity backend
    (D.1-D.10). Two mutation controls, both persisted: a length/height
    correction (D.11F) and an explicit, exact-revision approval (D.11G) on
    a single real wall at a time — see the module docstring.

    Offers two data sources (see module docstring): the D.11A demo scenario,
    cached once per session in st.session_state, and the D.11B real workspace
    objects, hydrated fresh from the database on every render, with any
    persisted corrections and approvals replayed on top.
    """
    st.title("Editable 3D Inspector")
    st.caption(
        "Correction/approval/quantity backend (D.1–D.10). Real workspace "
        "objects support a real, persisted correction and an explicit, "
        "exact-revision approval per wall."
    )

    mode = st.radio(
        "Data source", ["Demo scenario", "Real workspace objects"],
        horizontal=True, key="_editable_3d_inspector_mode",
    )
    _render_trust_legend()

    skipped: List[HydrationSkip] = []
    block_reason = ""

    if mode == "Demo scenario":
        st.info(
            "This is an in-session demo scenario built from real backend calls "
            "(Editable3DCorrectionLedger, recalculate_quantities_for_correction, "
            "approve_corrected_geometry, create_takeoff_output_row) — not real "
            "workspace geometry. Switch to \"Real workspace objects\" to inspect "
            "the current workspace's actual building masses."
        )
        _ensure_demo_scenario_loaded()
        ledger: Editable3DCorrectionLedger = st.session_state[_SESSION_LEDGER_KEY]
        rows: Dict[str, TakeoffOutputRow] = st.session_state[_SESSION_ROWS_KEY]
        block_reason = st.session_state[_SESSION_BLOCK_REASON_KEY]
        object_ids = _DEMO_OBJECT_IDS
    else:
        st.info(
            "Real building masses for this workspace, hydrated fresh from "
            "model_masses/model_openings on every load, with any persisted "
            "corrections and approvals (editable_3d_correction_events, "
            "editable_3d_approval_events) replayed on top, in that order — "
            "model_masses/model_openings themselves are only ever read, never "
            "written. Hydration never grants approval: every object starts "
            "REVIEW_REQUIRED (or BLOCKED if its height isn't actually known — "
            "see the skip/authority notes below), and stays that way until "
            "explicitly approved via \"Approve {object_id}\" below. There is "
            "still no schema link from building masses to real take-off "
            "rows, so a wall only shows dependent quantities once you "
            "correct it — see \"Correct {wall_id}\" below."
        )
        if workspace is None:
            st.warning("Open or create a workspace first.")
            return
        workspace_id = int(workspace["id"])
        ledger, walls, zone_rows, object_ids, skipped = _load_real_workspace_objects(workspace)
        original_walls_by_id = {w.wall_id: w for w in walls}
        event_rows, state_rows = _load_persisted_correction_state(workspace_id)
        walls, replay_warnings = replay_persisted_corrections(ledger, walls, event_rows)
        replay_warnings = replay_warnings + verify_object_state_consistency(ledger, state_rows)
        approval_rows = _load_persisted_approval_state(workspace_id)
        replay_warnings = replay_warnings + replay_persisted_approvals(ledger, approval_rows)
        rows = _build_dependent_quantity_rows(ledger, original_walls_by_id, event_rows)
        if skipped:
            with st.expander(f"{len(skipped)} item(s) skipped during hydration (fail-closed)"):
                for s in skipped:
                    st.warning(f"[{s.kind}] id={s.source_id} ({s.label}): {s.reason}")
        if replay_warnings:
            with st.expander(f"{len(replay_warnings)} correction-replay warning(s)"):
                for w in replay_warnings:
                    st.warning(f"[{w.object_id}] {w.reason}")
        if not object_ids:
            st.info(
                "No building masses recorded for this workspace yet. Add masses on "
                "the \"3D Building Model\" page, or switch to the demo scenario above."
            )
            return

        # Resolve the current selection *before* building the figure, so the
        # selected wall can be drawn highlighted in the scene rather than
        # only described in the text below it.
        if st.session_state.get(_SELECTED_REAL_OBJECT_KEY) not in object_ids:
            st.session_state[_SELECTED_REAL_OBJECT_KEY] = object_ids[0]

        st.markdown("### 3D view")
        st.caption(
            "Read-only — orbit (drag), pan (right-drag/shift-drag), zoom (scroll). "
            "Solid panels are walls with an authoritative height; dashed lines are "
            "walls whose height isn't authoritative (shown at footprint only). "
            "The selected wall (dropdown below) is drawn with a highlighted "
            "outline. Hover a wall's marker dot to see its object id."
        )
        fig = build_workspace_3d_figure(
            walls, zone_rows, selected_wall_id=st.session_state[_SELECTED_REAL_OBJECT_KEY],
        )
        st.plotly_chart(fig, key="_editable_3d_viewer")

    if mode == "Real workspace objects":
        selected = st.selectbox(
            "Select an editable 3D object", object_ids, key=_SELECTED_REAL_OBJECT_KEY,
        )
    else:
        selected = st.selectbox("Select an editable 3D object", object_ids)
    obj = ledger.get_object(selected)
    if obj is None:
        st.error(f"Object {selected!r} not found in the ledger.")
        return

    _render_quick_summary(obj)

    if mode == "Real workspace objects":
        walls_by_id = {w.wall_id: w for w in walls}
        _render_correction_form(workspace_id, ledger, selected, walls_by_id.get(selected))
        _render_approval_form(workspace_id, ledger, selected, obj)

    _render_object_summary(obj)

    if mode == "Demo scenario" and selected == "WALL-DEMO-3" and block_reason:
        st.error(f"Real approval attempt on this object failed closed:\n\n{block_reason}")

    st.divider()
    st.markdown("### Correction event log")
    _render_correction_events(ledger, selected)

    st.divider()
    _render_linked_quantities(obj, rows)
