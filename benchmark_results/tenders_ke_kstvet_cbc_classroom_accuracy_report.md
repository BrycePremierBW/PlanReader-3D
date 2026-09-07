# PlanReader Accuracy Evaluation Report: Proposed Construction of CBC Classroom and Integrated Resource Center

- **Benchmark ID**: `tenders_ke_kstvet_cbc_classroom`
- **Organization**: Kenya School of TVET / Ministry of Education
- **Tender Reference**: `KSTVET/008/24`
- **Evaluation Timestamp**: `2026-09-07T14:16:09.865744+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Downloads\1727358888238-bq-nd-drawing.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`16.7%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`16.7%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `58` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `12` | Physical architectural takeoff baseline |
| Total Items Compared | `12` | Measurable expected + hallucinated items |
| Exact Matches | `2` | Exactly matched quantities |
| Within 5% Tolerance | `0` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `1` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `2` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `5` | Severe discrepancy requiring investigation |
| Missed Items | `2` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `0` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `BOQ-C36-A` | 150 mm Thick concrete block walling | `measurable_from_drawings` | 58.00 | 80.95 | SM | +22.95 | 39.6% | `gross_mismatch` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C36-B` | Ditto gable walling 150mm thick | `measurable_from_drawings` | 13.00 | 9.34 | SM | -3.66 | 28.1% | `gross_mismatch` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C41-B` | Window overall size 3000 x 1200mm High steel casement | `schedule_extractable` | 2.00 | 2.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C41-C` | Window overall size 2900 x 1200mm High steel casement | `schedule_extractable` | 3.00 | 5.00 | NO | +2.00 | 66.7% | `gross_mismatch` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C44-A` | Mild steel panelled double door overall size 1000 x 2100mm High | `schedule_extractable` | 1.00 | 2.00 | NO | +1.00 | 100.0% | `gross_mismatch` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C45-A` | 40 mm Thick cement and sand (1:3) steel trowel smooth with red oxide floor finish | `measurable_from_drawings` | 97.00 | 103.02 | SM | +6.02 | 6.2% | `within_10_percent` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C45-B` | 3200 x 1500mm wide 25mm thick blockboard chalkboard with black bituminous paint | `measurable_from_drawings` | 1.00 | 1.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C46-A` | 12 mm (minimum) two-coat plaster to internal walls | `measurable_from_drawings` | 69.00 | 80.95 | SM | +11.95 | 17.3% | `within_20_percent` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C46-C` | Three coats of premium quality silk vinyl paint to plastered internal walls | `measurable_from_drawings` | 69.00 | 80.95 | SM | +11.95 | 17.3% | `within_20_percent` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C47-A` | Extra over walling for key pointing externally | `measurable_from_drawings` | 60.00 | 80.95 | SM | +20.95 | 34.9% | `gross_mismatch` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C47-B` | 12mm plaster to external walls, beams, columns | `measurable_from_drawings` | 20.00 | - | SM | - | - | `missed_in_extraction` | Sheet KSTVET/08/2024-AD01 (p. 54) |
| `BOQ-C47-D` | 50mm dia x 1.5mm thick CHS pillars to verandah | `measurable_from_drawings` | 4.00 | - | NO | - | - | `missed_in_extraction` | Sheet KSTVET/08/2024-AD01 (p. 54) |

## 4. Gross Mismatches (> 20%)

- **`BOQ-C36-A`** (150 mm Thick concrete block walling): Expected `58.0`, Extracted `80.95` (39.6% error). Comparison evaluated against 58.0 SM
- **`BOQ-C36-B`** (Ditto gable walling 150mm thick): Expected `13.0`, Extracted `9.34` (28.1% error). Comparison evaluated against 13.0 SM
- **`BOQ-C41-C`** (Window overall size 2900 x 1200mm High steel casement): Expected `3.0`, Extracted `5.0` (66.7% error). Comparison evaluated against 3.0 NO
- **`BOQ-C44-A`** (Mild steel panelled double door overall size 1000 x 2100mm High): Expected `1.0`, Extracted `2.0` (100.0% error). Comparison evaluated against 1.0 NO
- **`BOQ-C47-A`** (Extra over walling for key pointing externally): Expected `60.0`, Extracted `80.95` (34.9% error). Comparison evaluated against 60.0 SM

## 5. Missed Items

- **`BOQ-C47-B`** (12mm plaster to external walls, beams, columns): Expected `20.0 SM` on Sheet `KSTVET/08/2024-AD01`.
- **`BOQ-C47-D`** (50mm dia x 1.5mm thick CHS pillars to verandah): Expected `4.0 NO` on Sheet `KSTVET/08/2024-AD01`.
