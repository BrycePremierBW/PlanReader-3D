# PR B — Geometry & Takeoff Hardening Module Map

## Overview
Detailed architecture mapping of PlanReader's measurement correctness, scale calibration, geometry authority, takeoff formulas, and publication preflight hooks for PR B.

---

## 1. Scale Detection
- **Modules**: `pb_multi_page_scale_v170.py`, `pb_elevation_calibration_v177.py`, `pb_geometry_takeoff_model.py`
- **Functions / Classes**:
  - `extract_scale_ratio_from_text(text: str) -> Optional[int]`: Parses standard drawing scale strings (`1:100`, `1:50`, `1/200 @ A1`) via regex.
  - `ElevationCalibration.measure_graphic_scale_bar`: Vector and pixel measurement of graphic scale bars on elevation drawings.
  - `ScaleCalibration` (in `pb_geometry_takeoff_model.py`): Dataclass capturing `page_no`, `ratio_str`, `px_per_m`, `method`, `is_verified`, and `confidence`.
- **Invariants & Gates**:
  - Calibration is usable for firm measurements ONLY when `is_verified=True`, `px_per_m > 0`, and `px_per_m` is strictly finite.
  - Unknown or unverified scales fail closed.

---

## 2. Page Scale Storage
- **Modules**: `pb_multi_page_scale_v170.py`
- **Classes / Schemas**:
  - `PageScaleRecord`: Tracks `page_id`, `page_label`, `page_type`, `scale_status`, `px_per_m`, `m_per_pt`, `scale_ratio`, `calibration_method`, `confidence`, and evidence flags.
  - `MultiPageScaleRegistry`: Builds workspace scale inventory from SQLite `pages` table (`id`, `page_label`, `page_type`, `px_per_m`, `scale_text`, `page_no`).
- **Scale States**:
  - `CALIBRATED`: Explicit user or calibrated scale.
  - `PROVISIONAL_AUTO`: Derived from title-block text or cross-page inheritance; flags review warning.
  - `UNCALIBRATED`: Drawing page with missing scale calibration; blocks commercial release.
  - `NOT_REQUIRED`: Cover, index, or specification sheets without takeoff elements.

---

## 3. Pixel-to-Real Conversion
- **Modules**: `pb_multi_page_scale_v170.py`, `pb_wall_topology_v174.py`, `pb_geometry_services.py`
- **Functions**:
  - `calculate_m_per_pt_from_px_per_m(px_per_m: float, render_zoom: float = 2.0) -> float`: Native PDF point conversion (`render_zoom / px_per_m`).
  - `compute_polygon_area_and_perimeter(pts, px_per_m) -> Tuple[float, float]`: Converts 2D pixel coordinates to real-world area ($m^2$) and perimeter ($m$) using the Shoelace formula dividing area by $(px\_per\_m)^2$ and perimeter by $px\_per\_m$.

---

## 4. Dimension Text Extraction & Figured Dimension Precedence
- **Modules**: `pb_geometry_takeoff_model.py`, `pb_opening_schedule_v171.py`, `pb_wall_topology_v174.py`
- **Functions / Precedence Engine**:
  - `reconcile_figured_and_scaled(figured_mm, scaled_mm, max_delta_ratio=0.05)`:
    - **Fundamental Rule**: Figured dimensions outrank scaled geometry.
    - When figured dimension is present and agrees with scaled geometry ($\le 5\%$ delta), status is `FIRM` with `scaled_delta_mm` recorded.
    - When discrepancy $> 5\%$, status is set to `REVIEW_REQUIRED` with explicit warning note.
    - When only scaled geometry exists (no figured dimension), status is set to `PROVISIONAL`.
    - When neither is valid, raises `ValueError`.

---

## 5. Wall / Room / Opening Geometry Domain Model
- **Modules**: `pb_geometry_takeoff_model.py`, `pb_mapped_zone_geometry_authority.py`, `pb_wall_topology_v174.py`
- **Domain Objects**:
  - `PlanPage`: Sheet label, canonical role, scale calibration, and revision reference.
  - `Opening`: Opening ID, type (`door`, `window`, `skylight`, `void`), dimensions, area, coordinates, deducts flag, and authority.
  - `Door`: Associated opening, door code, paint treatment, `is_entry`, and `is_excluded`.
  - `Window`: Associated opening, window code, glazing type, and `is_obscure`.
  - `WallSegment`: ID, length, height, gross area, net area, opening list, figured dimension, and delta.
  - `Room`: Room ID, name, floor area, perimeter, wall height, and wall IDs.
  - `Surface`: Substrate, finish tag, gross area, deduction area, net area.
  - `Ceiling`: Room name, area, void deductions, net area, RCP sheet.
  - `FloorArea`: Level name, GFA, internal area.
  - `ElevationSurface`: Facade side, block, finish tag, gross/deduction/net areas.
  - `Soffit`: Location, area, finish tag.
  - `ExclusionZone`: Reason, polygon boundary coordinates.
- **Geometric Invariants**:
  - Real polygon geometry (L-shapes, stepped shapes, internal voids) is strictly preserved (`pb_mapped_zone_geometry_authority.py`).
  - An irregular polygon is never approximated as a bounding box marked `Measured`.

---

## 6. Area / Length Formulas
- **Modules**: `pb_geometry_takeoff_model.py`, `pb_geometry_services.py`
- **Formulas**:
  - `calculate_wall_takeoff(length_m, height_m, openings, standard="AS4041", deduction_threshold_m2=0.5)`:
    $$\text{gross\_area} = \text{round}(\text{length\_m} \times \text{height\_m}, 4)$$
    $$\text{net\_area} = \text{round}(\text{gross\_area} - \text{total\_deductions}, 4)$$
- **Guarantees**:
  - Zero, negative, and non-finite dimensions strictly rejected with `ValueError`.
  - Deductions cannot exceed gross area.
  - Net area $\ge 0.0$.

---

## 7. Opening Deductions
- **Modules**: `pb_geometry_takeoff_model.py`, `pb_opening_evidence_v170.py`, `pb_opening_deduction_v174.py`
- **Deduction Invariants**:
  - Under Australian standard **AS 4041**, openings $> 0.5\text{ m}^2$ are deducted from wall area.
  - Openings $\le 0.5\text{ m}^2$ are NOT deducted unless explicitly configured.
  - Openings with `deducts=False` are never deducted.
  - Overlapping physical openings are deduplicated using spatial clustering and compatibility checks.
  - Factory-finished and non-paint items (garage doors, glazed curtain walls) are excluded or treated as opening voids.

---

## 8. Authority Metadata & Finish Tag Classification
- **Modules**: `pb_geometry_takeoff_model.py`
- **Authority Types (`MeasurementAuthorityType`)**:
  - `DOCUMENTED_DIMENSION`, `SCHEDULE_EXTRACTED`, `PDF_SCALED`, `AI_DETECTED`, `USER_CORRECTED`, `USER_APPROVED`, `MODEL_DERIVED`, `PROVISIONAL`, `EXCLUDED`, `REFERENCE_ONLY`.
- **Authority Statuses (`AuthorityStatus`)**:
  - `FIRM`: Commercial-ready, verified measurement.
  - `PROVISIONAL`: Scaled linework, estimated height, or unverified detection; cannot be published as firm.
  - `REVIEW_REQUIRED`: Discrepancies, unknown finish tags, conflicting scales.
  - `EXCLUDED`: Non-paint trades (e.g. powdercoated aluminium, screed, mastic).
  - `REFERENCE_ONLY`: Informational context (e.g. GFA benchmark comparison).
- **Finish Tag Classification (`classify_finish_tag`)**:
  - `EC01`–`EC04`, `EC1`–`EC4`: Included paintable cladding (Dulux Light Rice, Lexicon Half, Monument).
  - `XF01`–`XF03`, `XP01`: Included external finishes.
  - `P`, `PB01`–`PB05`, `SHD`: Included internal plasterboard finishes.
  - `RBL`: Provisional render (requires specification check).
  - `SL`, `SCR`, `PPT`, `COLORBOND`, `ALUM`: Excluded factory/trade scope.
  - Unknown tags: Fail closed to `REVIEW_REQUIRED`.

---

## 9. Benchmark Quantity Comparison Hooks
- **Modules**: `pb_benchmark_schema.py`, `pb_project_identity.py`, `pb_benchmark_runner.py`
- **Capabilities**:
  - Compares derived quantities against golden manifests (`school_rd_60_62`, `lago_britinya`, `school_rd_92_94`, `king_st_122_126`).
  - Verifies project identity compatibility (`assert_project_compatibility`) before benchmarking or takeoff cross-referencing.
  - Tolerances: 0% tolerance for exact unit/level/schedule counts; configured threshold for GFA and surface areas.

---

## 10. JobHub Publish-Preflight Hooks
- **Modules**: `pb_jobhub_preflight_v162.py`, `pb_jobhub_sync_v162.py`, `pb_takeoff_authority_v164.py`
- **Preflight Gates**:
  - `UNCALIBRATED_SCALE` and `PROVISIONAL_SCALE` block publishing.
  - Non-finite or negative quantities block publishing.
  - Model-derived or AI-detected measurements require estimator sign-off (`USER_APPROVED`).
  - Commercial publish gate fails closed if any critical issues are active.
