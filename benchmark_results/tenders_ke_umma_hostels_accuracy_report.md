# PlanReader Accuracy Evaluation Report: Proposed Student Hostels for Umma University in Kajiado

- **Benchmark ID**: `tenders_ke_umma_hostels`
- **Organization**: Umma University
- **Tender Reference**: `UUT/02/2026`
- **Evaluation Timestamp**: `2026-09-09T05:44:17.751056+00:00`
- **Evaluation Status**: `scored`
- **Source PDF**: `C:\Users\bryce\Documents\PB-PlanReader-3D\benchmarks\sources\umma-university-hostels-builders-work.pdf`

## 1. Executive Headline Metrics

| Metric | Value | Description |
| :--- | :--- | :--- |
| **Overall Accuracy (<= 5% tol)** | **`80.0%`** | Combined exact matches and within 5% tolerance |
| **Strict Exact Accuracy** | **`80.0%`** | Zero-tolerance exact numerical matches only |
| Total BOQ Items | `60` | Complete tender Bill of Quantities schedule lines |
| Measurable Items Evaluated | `15` | Physical architectural takeoff baseline |
| Total Items Compared | `15` | Measurable expected + hallucinated items |
| Exact Matches | `12` | Exactly matched quantities |
| Within 5% Tolerance | `0` | Area/length finishes within 5% tolerance |
| Within 10% Tolerance | `0` | Minor variations (5% to 10%) |
| Within 20% Tolerance | `0` | Moderate variations (10% to 20%) |
| Gross Mismatches (> 20%) | `0` | Severe discrepancy requiring investigation |
| Missed Items | `3` | Measurable items present in BOQ but missing in extraction |
| Hallucinated Items | `0` | Items extracted but absent from drawing / BOQ |

## 2. Non-Penalized Exclusions

Contractor overheads, site preliminaries, and provisional budget allowances are excluded from physical geometric accuracy denominators by design:
- **Preliminaries Excluded**: `0`
- **Provisional Sums Excluded**: `0`
- **Non-Architectural Excluded**: `0`

## 3. Detailed Item Comparison Breakdown

| Item ID | Description | Category | Expected | Extracted | Unit | Delta | % Error | Status | Drawing Trace |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `UUH-WD1` | WD 01 - window panel, 1800x2200mm high, horizontal sliding panels with U-channel frame (4-bed rooms, Locker rooms, Games Room, PWD room) | `schedule_extractable` | 172.00 | - | NO | - | - | `missed_in_extraction` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 160) |
| `UUH-WD2` | WD 02 - window panel, 1800x1800mm high, horizontal sliding panels (All Washrooms) | `schedule_extractable` | 184.00 | - | NO | - | - | `missed_in_extraction` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 160) |
| `UUH-WD3` | WD 03 - window panel, 900x900mm high, horizontal sliding panels (Laundry area) | `schedule_extractable` | 4.00 | - | NO | - | - | `missed_in_extraction` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 160) |
| `UUH-D1` | D-01 double leaf, single swing fire door, 1800x2500mm high (Fire Escape stair) | `schedule_extractable` | 10.00 | 10.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 160) |
| `UUH-D2` | D-02 single leaf, single swing semi-solid flush mahogany door, 900x2100mm high (PWD rooms, 4-bed rooms, Custodian's office, Prayer room) | `schedule_extractable` | 160.00 | 160.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 160) |
| `UUH-D3` | D-03 double leaf, single swing mild steel door, 800x2400mm high (Wet area entrances, Bathrooms) | `schedule_extractable` | 308.00 | 308.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 160) |
| `UUH-D4` | D-04 single leaf, single swing semi-solid flush mahogany door, 900x2500mm high (Toilets) | `schedule_extractable` | 308.00 | 308.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 161) |
| `UUH-D5` | D-05 double leaf, single swing mild steel door, 1400x2500mm high (Ground floor locker room) | `schedule_extractable` | 1.00 | 1.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 161) |
| `UUH-D6` | D-06 double leaf, double mild steel door, 2200x2500mm high (Main entrance) | `schedule_extractable` | 1.00 | 1.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 161) |
| `UUH-D7` | D-07 single leaf, single swing semi-solid flush mahogany door, 900x2500mm high (Duct doors) | `schedule_extractable` | 12.00 | 12.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 161) |
| `UUH-D8` | D-08 single leaf, single swing semi-solid flush mahogany door, 1000x2400mm high (PWD Wet area entrances, PWD Toilets) | `schedule_extractable` | 6.00 | 6.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 161) |
| `UUH-D9` | D-09 double leaf, single swing mild steel door, 1000x2100mm high (First floor locker room) | `schedule_extractable` | 1.00 | 1.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 161) |
| `UUH-D10` | D-10 double leaf, single swing mild steel door, 1800x2250mm high (2nd-4th floors Locker rooms) | `schedule_extractable` | 3.00 | 3.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 162) |
| `UUH-D11` | D-11 double leaf, single swing mild steel door, 1200x2250mm high (Laundromart) | `schedule_extractable` | 1.00 | 1.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 162) |
| `UUH-D12` | D-12 double leaf, double mild steel door, 2000x2250mm high (Roof terrace) | `schedule_extractable` | 2.00 | 2.00 | NO | +0.00 | 0.0% | `exact_match` | Sheet TI-UUH/25/11 rev.02 (Window and Door Schedule) (p. 162) |

## 5. Missed Items

- **`UUH-WD1`** (WD 01 - window panel, 1800x2200mm high, horizontal sliding panels with U-channel frame (4-bed rooms, Locker rooms, Games Room, PWD room)): Expected `172.0 NO` on Sheet `TI-UUH/25/11 rev.02 (Window and Door Schedule)`.
- **`UUH-WD2`** (WD 02 - window panel, 1800x1800mm high, horizontal sliding panels (All Washrooms)): Expected `184.0 NO` on Sheet `TI-UUH/25/11 rev.02 (Window and Door Schedule)`.
- **`UUH-WD3`** (WD 03 - window panel, 900x900mm high, horizontal sliding panels (Laundry area)): Expected `4.0 NO` on Sheet `TI-UUH/25/11 rev.02 (Window and Door Schedule)`.
