# PlanReader Accuracy Evaluation Report: Proposed Construction of a Science Laboratory at Murera Senior School

- **Benchmark ID**: `tenders_ke_murera_science_lab`
- **Organization**: Ministry of Education / State Department for Basic Education / County Commissioner Meru
- **Tender Reference**: `MOE/SEEQIP/C012/01/2026-2027`
- **Evaluation Timestamp**: `2026-09-07T10:15:11.828848+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Downloads\murera_senior_school_laboratory\1785347143869-bqs-drawings.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`25.0%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`25.0%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `58` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `10` | Physical architectural takeoff baseline |
| Total Items Compared | `16` | Measurable expected + hallucinated items |
| Exact Matches | `4` | Exactly matched quantities |
| Within 5% Tolerance | `0` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `0` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `4` | Severe discrepancy requiring investigation |
| Missed Items | `2` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `6` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `substructure_surface_bed` | 125mm thick reinforced concrete class 25 surface bed | `measurable_from_drawings` | 196.00 | 43.26 | SM | -152.74 | 77.9% | `gross_mismatch` | Sheet Section A-A / E-E (p. 225) |
| `substructure_bed_dpm` | 1000 gauge polythene damp-proof membrane under bed | `measurable_from_drawings` | 208.00 | 45.90 | SM | -162.10 | 77.9% | `gross_mismatch` | Sheet Section A-A / E-E (p. 225) |
| `substructure_a142_mesh` | Steel mesh fabric reinforcement Ref A142 in floor bed | `measurable_from_drawings` | 208.00 | 45.90 | SM | -162.10 | 77.9% | `gross_mismatch` | Sheet Section A-A / E-E (p. 225) |
| `masonry_external_walling` | 150mm thick natural stone external walling | `measurable_from_drawings` | 132.00 | 31.68 | SM | -100.32 | 76.0% | `gross_mismatch` | Sheet Elevations E-01/E-03 (p. 219) |
| `masonry_piers` | 300 x 300mm masonry piers 4,500mm high | `measurable_from_drawings` | 13.00 | 13.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet Section A-A / Foundation Layout (p. 225) |
| `damp_proof_course` | 150mm wide bituminous felt damp proof course | `measurable_from_drawings` | 67.00 | - | M | - | - | `missed_in_extraction` | Sheet Section A-A (p. 225) |
| `roof_trusses` | Timber roof trusses complete (13 No) | `measurable_from_drawings` | 13.00 | 13.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet Section A-A (TRUSS T1 13 No.S) (p. 225) |
| `brick_vents` | 250mm x 150mm precast/brick vents | `measurable_from_drawings` | 12.00 | 12.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet Elevations E-01/E-03 (p. 219) |
| `steel_casement_windows` | Steel casement windows W1, W2, W3, W4 complete with glazing | `schedule_extractable` | 12.00 | 12.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet Window Schedule (p. 223) |
| `doors_complete` | Single flush doors and double steel casement doors | `schedule_extractable` | 5.00 | - | NO | - | - | `missed_in_extraction` | Sheet Door Schedule (p. 223) |
| `internal_plaster` | Internal plastering to wall surfaces | `hallucinated` | - | 103.85 | SM | - | - | `hallucinated_item` | Sheet E-01 (p. 219) |
| `internal_paint` | Internal vinyl/emulsion paint to wall surfaces | `hallucinated` | - | 103.85 | SM | - | - | `hallucinated_item` | Sheet E-01 (p. 219) |
| `external_key_pointing` | External key pointing to exposed stone/block masonry | `hallucinated` | - | 90.24 | SM | - | - | `hallucinated_item` | Sheet E-01 (p. 219) |
| `external_render` | External render / plinth plastering | `hallucinated` | - | 28.51 | SM | - | - | `hallucinated_item` | Sheet E-01 (p. 219) |
| `W1` | Mild steel casement window 3000 x 1200 mm high (W1) | `hallucinated` | - | 2.00 | NO | - | - | `hallucinated_item` | Sheet J (p. 226) |
| `W2` | Mild steel casement window 2900 x 1200 mm high (W2) | `hallucinated` | - | 3.00 | NO | - | - | `hallucinated_item` | Sheet J (p. 226) |

## 4. Gross Mismatches (> 20%)

- **`substructure_surface_bed`** (125mm thick reinforced concrete class 25 surface bed): Expected `196.0`, Extracted `43.26` (77.9% error). Comparison evaluated against 196.0 SM
- **`substructure_bed_dpm`** (1000 gauge polythene damp-proof membrane under bed): Expected `208.0`, Extracted `45.9` (77.9% error). Comparison evaluated against 208.0 SM
- **`substructure_a142_mesh`** (Steel mesh fabric reinforcement Ref A142 in floor bed): Expected `208.0`, Extracted `45.9` (77.9% error). Comparison evaluated against 208.0 SM
- **`masonry_external_walling`** (150mm thick natural stone external walling): Expected `132.0`, Extracted `31.68` (76.0% error). Comparison evaluated against 132.0 SM

## 5. Missed Items

- **`damp_proof_course`** (150mm wide bituminous felt damp proof course): Expected `67.0 M` on Sheet `Section A-A`.
- **`doors_complete`** (Single flush doors and double steel casement doors): Expected `5.0 NO` on Sheet `Door Schedule`.

## 6. Hallucinated Items

- **`internal_plaster`** (Internal plastering to wall surfaces): Extracted `103.85 SM` with no corresponding BOQ entry.
- **`internal_paint`** (Internal vinyl/emulsion paint to wall surfaces): Extracted `103.85 SM` with no corresponding BOQ entry.
- **`external_key_pointing`** (External key pointing to exposed stone/block masonry): Extracted `90.24 SM` with no corresponding BOQ entry.
- **`external_render`** (External render / plinth plastering): Extracted `28.51 SM` with no corresponding BOQ entry.
- **`W1`** (Mild steel casement window 3000 x 1200 mm high (W1)): Extracted `2.0 NO` with no corresponding BOQ entry.
- **`W2`** (Mild steel casement window 2900 x 1200 mm high (W2)): Extracted `3.0 NO` with no corresponding BOQ entry.
