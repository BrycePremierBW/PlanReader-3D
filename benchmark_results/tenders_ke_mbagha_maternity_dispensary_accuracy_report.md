# PlanReader Accuracy Evaluation Report: Proposed Construction of a Maternity Block at Mbagha Dispensary in Mwatate Sub-County

- **Benchmark ID**: `tenders_ke_mbagha_maternity_dispensary`
- **Organization**: County Government of Taita Taveta
- **Tender Reference**: `2028763-2025/2026`
- **Evaluation Timestamp**: `2026-09-07T08:52:29.832448+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Downloads\mbagha_maternity_dispensary\drawings.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`0.0%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`0.0%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `123` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `16` | Physical architectural takeoff baseline |
| Total Items Compared | `16` | Measurable expected + hallucinated items |
| Exact Matches | `0` | Exactly matched quantities |
| Within 5% Tolerance | `0` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `0` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `7` | Severe discrepancy requiring investigation |
| Missed Items | `9` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `0` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `BOQ-MAT4-A` | 200mm thick natural stone foundation/superstructure walling | `measurable_from_drawings` | 77.00 | 237.76 | SM | +160.76 | 208.8% | `gross_mismatch` | Sheet Page-1 (p. 1) |
| `BOQ-MAT4-B` | 150mm thick natural stone partition walling | `measurable_from_drawings` | 12.00 | - | SM | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT6-D` | 50mm thick Solid panelled door size 900x2100mm | `schedule_extractable` | 3.00 | 1.00 | NO | -2.00 | 66.7% | `gross_mismatch` | Sheet Page-1 (p. 1) |
| `BOQ-MAT6-E` | 50mm thick solid core flush door size 900x2100mm | `schedule_extractable` | 3.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT6-E1` | Heavy duty mild-steel door size 900x2400mm | `schedule_extractable` | 2.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT8-A` | Mild steel casement window size 650 x 900mm | `schedule_extractable` | 3.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT8-B` | Mild steel casement window size 1150 x 1500mm | `schedule_extractable` | 1.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT8-C` | Mild steel casement window size 1200 x 1500mm | `schedule_extractable` | 1.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT8-D` | Mild steel casement window size 1800 x 1500mm | `schedule_extractable` | 1.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT8-E` | Mild steel casement window size 2400 x 1500mm | `schedule_extractable` | 1.00 | - | NO | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT14-B` | 15mm thick cement sand (1:3) Rendering on Gable walls and ringbeam externally | `measurable_from_drawings` | 15.00 | 54.59 | SM | +39.59 | 263.9% | `gross_mismatch` | Sheet Page-1 (p. 1) |
| `BOQ-MAT14-C` | Extra-over ditto for key joints externally | `measurable_from_drawings` | 67.00 | 245.84 | SM | +178.84 | 266.9% | `gross_mismatch` | Sheet Page-1 (p. 1) |
| `BOQ-MAT14-E` | 25mm thick cement sand (1:3) floor screed to receive tiles | `measurable_from_drawings` | 64.00 | 587.35 | SM | +523.35 | 817.7% | `gross_mismatch` | Sheet Page-1 (p. 1) |
| `BOQ-MAT14-F` | 300x 300 x 8mm ceramic floor tiles fixed with approved Adhesive | `measurable_from_drawings` | 64.00 | - | SM | - | - | `missed_in_extraction` | Sheet Page-1 (p. 1) |
| `BOQ-MAT14-A` | 15mm thick cement sand lime (1:1:6) plaster on walls internally | `measurable_from_drawings` | 88.00 | 282.93 | SM | +194.93 | 221.5% | `gross_mismatch` | Sheet Page-1 (p. 1) |
| `BOQ-MAT15-D` | Prepare & apply undercoat and two coats plastic emulsion paint on plastered walls internally | `measurable_from_drawings` | 88.00 | 282.93 | SM | +194.93 | 221.5% | `gross_mismatch` | Sheet Page-1 (p. 1) |

## 4. Gross Mismatches (> 20%)

- **`BOQ-MAT4-A`** (200mm thick natural stone foundation/superstructure walling): Expected `77.0`, Extracted `237.76` (208.8% error). Comparison evaluated against 77.0 SM
- **`BOQ-MAT6-D`** (50mm thick Solid panelled door size 900x2100mm): Expected `3.0`, Extracted `1.0` (66.7% error). Comparison evaluated against 3.0 NO
- **`BOQ-MAT14-B`** (15mm thick cement sand (1:3) Rendering on Gable walls and ringbeam externally): Expected `15.0`, Extracted `54.59` (263.9% error). Comparison evaluated against 15.0 SM
- **`BOQ-MAT14-C`** (Extra-over ditto for key joints externally): Expected `67.0`, Extracted `245.84` (266.9% error). Comparison evaluated against 67.0 SM
- **`BOQ-MAT14-E`** (25mm thick cement sand (1:3) floor screed to receive tiles): Expected `64.0`, Extracted `587.35` (817.7% error). Comparison evaluated against 64.0 SM
- **`BOQ-MAT14-A`** (15mm thick cement sand lime (1:1:6) plaster on walls internally): Expected `88.0`, Extracted `282.93` (221.5% error). Comparison evaluated against 88.0 SM
- **`BOQ-MAT15-D`** (Prepare & apply undercoat and two coats plastic emulsion paint on plastered walls internally): Expected `88.0`, Extracted `282.93` (221.5% error). Comparison evaluated against 88.0 SM

## 5. Missed Items

- **`BOQ-MAT4-B`** (150mm thick natural stone partition walling): Expected `12.0 SM` on Sheet `Page-1`.
- **`BOQ-MAT6-E`** (50mm thick solid core flush door size 900x2100mm): Expected `3.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT6-E1`** (Heavy duty mild-steel door size 900x2400mm): Expected `2.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT8-A`** (Mild steel casement window size 650 x 900mm): Expected `3.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT8-B`** (Mild steel casement window size 1150 x 1500mm): Expected `1.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT8-C`** (Mild steel casement window size 1200 x 1500mm): Expected `1.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT8-D`** (Mild steel casement window size 1800 x 1500mm): Expected `1.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT8-E`** (Mild steel casement window size 2400 x 1500mm): Expected `1.0 NO` on Sheet `Page-1`.
- **`BOQ-MAT14-F`** (300x 300 x 8mm ceramic floor tiles fixed with approved Adhesive): Expected `64.0 SM` on Sheet `Page-1`.
