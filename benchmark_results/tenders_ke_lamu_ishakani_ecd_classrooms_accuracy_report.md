# PlanReader Accuracy Evaluation Report: Proposed Construction of 2No. ECD Classrooms and 2 Doors VIP Toilets at Ishakani Primary School

- **Benchmark ID**: `tenders_ke_lamu_ishakani_ecd_classrooms`
- **Organization**: Lamu County Government, Department of Public Works
- **Tender Reference**: `N/A (no tender reference number printed on this document)`
- **Evaluation Timestamp**: `2026-09-09T07:55:38.567288+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Documents\PB-PlanReader-3D\benchmarks\sources\lamu-ishakani-ecd-classrooms-boq.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`22.2%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`0.0%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `60` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `9` | Physical architectural takeoff baseline |
| Total Items Compared | `9` | Measurable expected + hallucinated items |
| Exact Matches | `0` | Exactly matched quantities |
| Within 5% Tolerance | `2` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `0` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `1` | Severe discrepancy requiring investigation |
| Missed Items | `6` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `0` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `LMU-E3-A` | 200mm thick approved local; machine cut; natural stone walling; bedding, jointing and pointing in cement sand (1:3) mortar | `measurable_from_drawings` | 136.00 | 135.52 | SM | -0.48 | 0.3% | `within_5_percent` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E3-B` | Damp proofing: 200mm wide; B.S. 743 Type A bitumen hessian base, 150mm laps (no allowance made for laps); horizontal, 1No. layer, bedded in cement sand (1:3) mortar | `measurable_from_drawings` | 75.00 | 48.40 | LM | -26.60 | 35.5% | `gross_mismatch` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E3-C` | Damp proofing: Polythene; 1000 gauge, 150mm laps (no allowance made to laps), horizontal; 1No. layer laid on murram blinding | `measurable_from_drawings` | 132.00 | - | SM | - | - | `missed_in_extraction` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E4-A` | Galvanized corrugated sheet roofing, 28 gauge, prepainted; G.C.I roof covering not exceeding 30 degrees from horizontal | `measurable_from_drawings` | 172.00 | - | SM | - | - | `missed_in_extraction` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E5-A` | 50mm thick double panelled door faced and hardwood lipped all round, overall size 1200 x 2400mm high | `schedule_extractable` | 2.00 | - | NO | - | - | `missed_in_extraction` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E7-A` | Wall finishes: 20mm thick cement and sand (1:4) plaster steel trawled to walls | `measurable_from_drawings` | 268.00 | - | SM | - | - | `missed_in_extraction` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E7-C` | Painting and decorations to walls: prepare and apply three coats of first quality plastic emulsion paint to plastered walls and beams | `measurable_from_drawings` | 268.00 | - | SM | - | - | `missed_in_extraction` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E7-D` | Chalk Board: 3200 x 1500mm wide, 25mm thick blockboard plugged to concrete or blockwork, complete with 50 x 25mm thick chamfered frame all round, 3 coats black bituminous paint | `measurable_from_drawings` | 2.00 | - | NO | - | - | `missed_in_extraction` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |
| `LMU-E7-E` | Floor Finishes: 20mm thick cement and sand (1:4) plaster steel trowelled smooth (printed in the source BOQ as "to walls", under the "Floor Finishes" header; quantity 132 SM matches this project's own ground-slab/hardcore quantities exactly, confirming this is the floor finish item despite the printed wording) | `measurable_from_drawings` | 132.00 | 131.20 | SM | -0.80 | 0.6% | `within_5_percent` | Sheet Ground Floor Plan / Elevations (unnumbered) (p. 41) |

## 4. Gross Mismatches (> 20%)

- **`LMU-E3-B`** (Damp proofing: 200mm wide; B.S. 743 Type A bitumen hessian base, 150mm laps (no allowance made for laps); horizontal, 1No. layer, bedded in cement sand (1:3) mortar): Expected `75.0`, Extracted `48.4` (35.5% error). Comparison evaluated against 75.0 LM

## 5. Missed Items

- **`LMU-E3-C`** (Damp proofing: Polythene; 1000 gauge, 150mm laps (no allowance made to laps), horizontal; 1No. layer laid on murram blinding): Expected `132.0 SM` on Sheet `Ground Floor Plan / Elevations (unnumbered)`.
- **`LMU-E4-A`** (Galvanized corrugated sheet roofing, 28 gauge, prepainted; G.C.I roof covering not exceeding 30 degrees from horizontal): Expected `172.0 SM` on Sheet `Ground Floor Plan / Elevations (unnumbered)`.
- **`LMU-E5-A`** (50mm thick double panelled door faced and hardwood lipped all round, overall size 1200 x 2400mm high): Expected `2.0 NO` on Sheet `Ground Floor Plan / Elevations (unnumbered)`.
- **`LMU-E7-A`** (Wall finishes: 20mm thick cement and sand (1:4) plaster steel trawled to walls): Expected `268.0 SM` on Sheet `Ground Floor Plan / Elevations (unnumbered)`.
- **`LMU-E7-C`** (Painting and decorations to walls: prepare and apply three coats of first quality plastic emulsion paint to plastered walls and beams): Expected `268.0 SM` on Sheet `Ground Floor Plan / Elevations (unnumbered)`.
- **`LMU-E7-D`** (Chalk Board: 3200 x 1500mm wide, 25mm thick blockboard plugged to concrete or blockwork, complete with 50 x 25mm thick chamfered frame all round, 3 coats black bituminous paint): Expected `2.0 NO` on Sheet `Ground Floor Plan / Elevations (unnumbered)`.
