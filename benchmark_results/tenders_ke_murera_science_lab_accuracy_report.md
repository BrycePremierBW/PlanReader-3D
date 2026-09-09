# PlanReader Accuracy Evaluation Report: Proposed Construction of a Science Laboratory at Murera Senior School

- **Benchmark ID**: `tenders_ke_murera_science_lab`
- **Organization**: Ministry of Education / State Department for Basic Education / County Commissioner Meru
- **Tender Reference**: `MOE/SEEQIP/C012/01/2026-2027`
- **Evaluation Timestamp**: `2026-09-09T18:35:43.873629+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Documents\PB-PlanReader-3D\benchmarks\sources\1785347143869-bqs-drawings.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`9.1%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`9.1%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `58` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `10` | Physical architectural takeoff baseline |
| Total Items Compared | `11` | Measurable expected + hallucinated items |
| Exact Matches | `1` | Exactly matched quantities |
| Within 5% Tolerance | `0` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `0` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `6` | Severe discrepancy requiring investigation |
| Missed Items | `3` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `1` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `substructure_surface_bed` | 125mm thick reinforced concrete class 25 surface bed | `measurable_from_drawings` | 196.00 | 149.26 | SM | -46.74 | 23.9% | `gross_mismatch` | Sheet Section A-A / E-E (p. 225) |
| `substructure_bed_dpm` | 1000 gauge polythene damp-proof membrane under bed | `measurable_from_drawings` | 208.00 | 149.26 | SM | -58.74 | 28.2% | `gross_mismatch` | Sheet Section A-A / E-E (p. 225) |
| `substructure_a142_mesh` | Steel mesh fabric reinforcement Ref A142 in floor bed | `measurable_from_drawings` | 208.00 | 149.26 | SM | -58.74 | 28.2% | `gross_mismatch` | Sheet Section A-A / E-E (p. 225) |
| `masonry_external_walling` | 150mm thick natural stone external walling | `measurable_from_drawings` | 132.00 | 166.32 | SM | +34.32 | 26.0% | `gross_mismatch` | Sheet Elevations E-01/E-03 (p. 219) |
| `masonry_piers` | 300 x 300mm masonry piers 4,500mm high | `measurable_from_drawings` | 13.00 | - | NO | - | - | `missed_in_extraction` | Sheet Section A-A / Foundation Layout (p. 225) |
| `damp_proof_course` | 150mm wide bituminous felt damp proof course | `measurable_from_drawings` | 67.00 | 52.80 | M | -14.20 | 21.2% | `gross_mismatch` | Sheet Section A-A (p. 225) |
| `roof_trusses` | Timber roof trusses complete (13 No) | `measurable_from_drawings` | 13.00 | 13.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet Section A-A (TRUSS T1 13 No.S) (p. 225) |
| `brick_vents` | 250mm x 150mm precast/brick vents | `measurable_from_drawings` | 12.00 | 6.00 | NO | -6.00 | 50.0% | `gross_mismatch` | Sheet Elevations E-01/E-03 (p. 219) |
| `steel_casement_windows` | Steel casement windows W1, W2, W3, W4 complete with glazing | `schedule_extractable` | 12.00 | - | NO | - | - | `missed_in_extraction` | Sheet Window Schedule (p. 223) |
| `doors_complete` | Single flush doors and double steel casement doors | `schedule_extractable` | 5.00 | - | NO | - | - | `missed_in_extraction` | Sheet Door Schedule (p. 223) |
| `external_key_pointing` | External key pointing to exposed stone/block masonry | `hallucinated` | - | 166.32 | SM | - | - | `hallucinated_item` | Sheet E-04 (p. 220) |

## 4. Gross Mismatches (> 20%)

- **`substructure_surface_bed`** (125mm thick reinforced concrete class 25 surface bed): Expected `196.0`, Extracted `149.26` (23.9% error). Comparison evaluated against 196.0 SM
- **`substructure_bed_dpm`** (1000 gauge polythene damp-proof membrane under bed): Expected `208.0`, Extracted `149.26` (28.2% error). Comparison evaluated against 208.0 SM
- **`substructure_a142_mesh`** (Steel mesh fabric reinforcement Ref A142 in floor bed): Expected `208.0`, Extracted `149.26` (28.2% error). Comparison evaluated against 208.0 SM
- **`masonry_external_walling`** (150mm thick natural stone external walling): Expected `132.0`, Extracted `166.32` (26.0% error). Comparison evaluated against 132.0 SM
- **`damp_proof_course`** (150mm wide bituminous felt damp proof course): Expected `67.0`, Extracted `52.8` (21.2% error). Comparison evaluated against 67.0 M
- **`brick_vents`** (250mm x 150mm precast/brick vents): Expected `12.0`, Extracted `6.0` (50.0% error). Comparison evaluated against 12.0 NO

## 5. Missed Items

- **`masonry_piers`** (300 x 300mm masonry piers 4,500mm high): Expected `13.0 NO` on Sheet `Section A-A / Foundation Layout`.
- **`steel_casement_windows`** (Steel casement windows W1, W2, W3, W4 complete with glazing): Expected `12.0 NO` on Sheet `Window Schedule`.
- **`doors_complete`** (Single flush doors and double steel casement doors): Expected `5.0 NO` on Sheet `Door Schedule`.

## 6. Hallucinated Items

- **`external_key_pointing`** (External key pointing to exposed stone/block masonry): Extracted `166.32 SM` with no corresponding BOQ entry.
