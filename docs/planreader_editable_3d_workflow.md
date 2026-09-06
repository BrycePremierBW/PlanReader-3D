# PlanReader Editable 3D Correction Workflow

## Overview
PlanReader's Editable 3D subsystem (`pb_editable_3d_model.py`) transforms detected 2D architectural drawings into an interactive, traceable 3D spatial building model.

Rather than serving solely as a visualization, Editable 3D is designed for **takeoff correction and authority hardening**:
1. Estimators inspect extracted rooms, walls, openings, and surfaces in 3D.
2. Direct user edits (modifying heights, moving walls, adding schedule openings) dynamically recalculate gross and net quantities under **AS 4041** standards.
3. Edits record structured **Correction Events**, promote authority status from `provisional` to `firm` (`user_corrected` / `user_approved`), mutate revision hashes, and invalidate stale preflight hashes.

---

## 1. 2D-to-3D Data Model Hierarchy

```text
BuildingModel
└── LevelModel (elevation, ceiling height, boundary polygon)
    ├── UnitModel (unit number, GFA)
    ├── RoomModel (floor area, perimeter, finish tag)
    ├── WallModel (length, height, authority, gross/net area)
    │   ├── OpeningModel (doors, windows, voids with AS 4041 deductions)
    │   └── SurfaceModel (internal/external faces, paint substrates)
    ├── SoffitModel (balconies, eaves)
    └── RoofModel (type, pitch, finish tag)
```

### Traceability & Non-Orphan Rule
Every 3D entity records:
- `source_page_no`: The exact sheet index in the PDF.
- `source_sheet_label`: Documented drawing title (e.g. `WD-02`).
- `scale_ratio`: Calibration ratio applied (e.g. `1:100`).
- `revision_hash`: Deterministic SHA-256 slice binding geometry to takeoff rows.
- **Rule**: No orphan 3D geometry may ever enter firm commercial publishing without traceable provenance.

---

## 2. Commercial Wall Height Authority

| Height Basis | Category | Publishing Authority | Policy |
|---|---|---|---|
| Documented Ceiling Height | `documented_ceiling_height` | `FIRM` | Explicitly noted on drawings / schedules |
| Section-Derived Height | `section_derived` | `FIRM` | Cross-referenced against structural sections |
| Schedule-Derived Height | `schedule_derived` | `FIRM` | Opening schedule head/sill height references |
| User-Entered Height | `user_entered` | `FIRM` | Estimator verified and approved |
| Model-Estimated Height | `model_estimated` | `PROVISIONAL` | Preliminary AI / heuristic guess; cannot publish as firm |
| Raked / Gable Wall | `raked_wall` | `REVIEW_REQUIRED` | Variable height requires elevation review |
| Stair Void Wall | `stair_wall` | `REVIEW_REQUIRED` | Double-height void requires manual confirmation |
| Unknown Height | `unknown_height` | `BLOCKED` | Fails closed; blocks commercial publication |

---

## 3. Correction Event Pipeline

Correction events are logged as structured audit records:

```json
{
  "correction_id": "corr_01",
  "object_id": "W_101",
  "object_type": "wall",
  "action": "change_height",
  "field_name": "height_m",
  "old_value": 2.7,
  "new_value": 3.0,
  "reason": "Aligned with structural section S-01",
  "actor": "Bryce Curran",
  "created_at": "2026-09-07T00:20:00Z",
  "source": "3d_editor"
}
```

### Supported Correction Actions
- `CHANGE_HEIGHT`: Updates wall height, triggers AS 4041 wall area recalculation.
- `MOVE_WALL` / `SPLIT_WALL` / `MERGE_WALL`: Updates wall length and endpoints.
- `ADD_OPENING` / `DELETE_OPENING`: Updates opening deductions from wall area.
- `CHANGE_FINISH`: Remaps substrate and finish tags.
- `APPROVE_QUANTITY` / `REJECT_QUANTITY`: Transitions authority state between `firm` and `review_required`.

### Preflight Invalidation Guarantee
Any correction event:
1. Re-computes gross and net surface areas.
2. Updates `revision_hash` of the affected wall, level, and building model.
3. Automatically marks previous preflight fingerprints **stale** (`is_preflight_invalidated = True`), requiring a fresh preflight run before commercial publication to JobHub.
