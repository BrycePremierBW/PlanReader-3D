# PlanReader Accuracy Evaluation Report: Proposed Construction of a Science Laboratory at Ghazi Primary School

- **Benchmark ID**: `tenders_ke_ghazi_science_lab`
- **Organization**: NG-CDF Voi Constituency / Ministry of Public Works
- **Tender Reference**: `NG-CDF/VOI/GZ/34/2023-2024`
- **Evaluation Timestamp**: `2026-09-09T05:19:39.094072+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Documents\PB-PlanReader-3D\benchmarks\sources\1739211305954-tender-document-for-construction-of-science-laboratory-at-ghazi-primary-school.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`15.4%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`0.0%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `70` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `13` | Physical architectural takeoff baseline |
| Total Items Compared | `13` | Measurable expected + hallucinated items |
| Exact Matches | `0` | Exactly matched quantities |
| Within 5% Tolerance | `2` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `0` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `1` | Severe discrepancy requiring investigation |
| Missed Items | `10` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `0` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `GZ-E1-E` | 500 gauge polythene damp proof membrane laid on hardcore under ground floor slab | `measurable_from_drawings` | 160.00 | 162.69 | SM | +2.69 | 1.7% | `within_5_percent` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E3-A` | Bituminous felt damp proof course 190mm thick under all 200mm thick walling | `measurable_from_drawings` | 51.00 | - | LM | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E3-B` | Approved coral block walling in 200mm thick walling externally | `measurable_from_drawings` | 109.00 | 151.20 | SM | +42.20 | 38.7% | `gross_mismatch` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E3-C` | Ditto internally (200mm thick coral block walling) | `measurable_from_drawings` | 41.00 | - | SM | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E3-D` | Ditto gable wall (200mm thick coral block walling) | `measurable_from_drawings` | 12.00 | - | SM | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E3-E` | 75mm diameter G.I column not exceeding 3000mm long | `measurable_from_drawings` | 8.00 | - | NO | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E5-A` | External door overall size 1500 x 2400mm high, unequal double leaf | `schedule_extractable` | 2.00 | - | NO | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E5-B` | 45mm internal quality flush door overall size 850 x 2120mm shutter | `schedule_extractable` | 3.00 | - | NO | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E6-D` | Metal casement window overall size 1800 x 1500mm high with 2No openable | `schedule_extractable` | 7.00 | - | NO | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E8-A` | 20mm thick cement and sand (1:5) plaster steel trowelled to internal walls | `measurable_from_drawings` | 203.00 | - | SM | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E8-C` | Prepare and apply three coats first grade plastic paint to plastered internal walls | `measurable_from_drawings` | 203.00 | - | SM | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E8-D` | 25mm thick cement sand plaster wood float to receive floor paving (floor screed) | `measurable_from_drawings` | 160.00 | 162.69 | SM | +2.69 | 1.7% | `within_5_percent` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |
| `GZ-E8-H` | 10mm chip board ceiling lining on brandering | `measurable_from_drawings` | 160.00 | - | SM | - | - | `missed_in_extraction` | Sheet Design Scheme (Plan) 1 of 3 (p. 167) |

## 4. Gross Mismatches (> 20%)

- **`GZ-E3-B`** (Approved coral block walling in 200mm thick walling externally): Expected `109.0`, Extracted `151.2` (38.7% error). Comparison evaluated against 109.0 SM

## 5. Missed Items

- **`GZ-E3-A`** (Bituminous felt damp proof course 190mm thick under all 200mm thick walling): Expected `51.0 LM` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E3-C`** (Ditto internally (200mm thick coral block walling)): Expected `41.0 SM` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E3-D`** (Ditto gable wall (200mm thick coral block walling)): Expected `12.0 SM` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E3-E`** (75mm diameter G.I column not exceeding 3000mm long): Expected `8.0 NO` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E5-A`** (External door overall size 1500 x 2400mm high, unequal double leaf): Expected `2.0 NO` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E5-B`** (45mm internal quality flush door overall size 850 x 2120mm shutter): Expected `3.0 NO` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E6-D`** (Metal casement window overall size 1800 x 1500mm high with 2No openable): Expected `7.0 NO` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E8-A`** (20mm thick cement and sand (1:5) plaster steel trowelled to internal walls): Expected `203.0 SM` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E8-C`** (Prepare and apply three coats first grade plastic paint to plastered internal walls): Expected `203.0 SM` on Sheet `Design Scheme (Plan) 1 of 3`.
- **`GZ-E8-H`** (10mm chip board ceiling lining on brandering): Expected `160.0 SM` on Sheet `Design Scheme (Plan) 1 of 3`.
