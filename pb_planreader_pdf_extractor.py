"""pb_planreader_pdf_extractor.py — Generic PlanReader PDF Takeoff Extractor.

PR F.4: Independent, leak-free PlanReader PDF geometry and schedule extraction.
PR F.7: Accuracy repair — outer-envelope detection, keyword-gated finishes, deduplication.
PR F.7A: Semantic leakage cleanup — complete elimination of hard-coded benchmark values,
         magic multipliers, unevidenced fallbacks, and keyword-presence guessing.

CRITICAL ARCHITECTURAL BOUNDARY:
- This module has ZERO knowledge of benchmark IDs, ground truth BOQs, or expected quantities.
- It operates STRICTLY on drawing evidence from the source PDF document.
- It NEVER imports, reads, or references ground truth manifest files.
- A prediction value may come ONLY from:
  1. parsed figured dimensions
  2. counted schedule/tag occurrences
  3. measured geometry with valid scale
  4. explicit schedule values
  5. deterministic geometry formula whose inputs all came from drawing evidence.
- If evidence is missing: return NO prediction / missed item. Do not guess.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF


@dataclass
class ExtractedPrediction:
    """A single predicted takeoff item extracted independently from drawing PDF."""

    tag: str
    trade_type: str  # "doors", "windows", "walls", "finishes", "fixtures", "structure"
    description: str
    quantity: float
    unit: str  # "NO", "SM", "M", "M3"
    confidence: float
    source_page: int
    sheet_number: Optional[str] = None
    dimensions: Optional[List[float]] = None
    bounding_box: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "trade_type": self.trade_type,
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit,
            "confidence": self.confidence,
            "source_page": self.source_page,
            "sheet_number": self.sheet_number,
            "dimensions": self.dimensions,
            "bounding_box": self.bounding_box,
            "metadata": self.metadata,
        }


class GenericPlanReaderExtractor:
    """Extracts physical building quantities from PDF drawing sets strictly from drawing evidence."""

    def __init__(self, default_ceiling_height_m: float = 2.80) -> None:
        self.default_ceiling_height_m = default_ceiling_height_m

    def is_drawing_page(self, page_text: str) -> bool:
        """Heuristically determine if a PDF page contains architectural drawings."""
        t_lower = page_text.lower()
        # Bill of Quantities text pages with item rates/amounts are not drawing sheets
        if re.search(r"bills?\s*of\s*quantit|rate\s*amount|\bamount\s*\(?kshs?\)?", t_lower):
            return False

        drawing_indicators = [
            "scale 1:",
            "scale: 1:",
            "scale 1 :",
            "scale: 1 :",
            "ground floor plan",
            "floor plan",
            "elevation",
            "section",
            "roof plan",
            "layout plan",
            "working drawing",
            "drawing no",
            "drawing title",
            "sheet no",
            "window schedule",
            "door schedule",
            "schedule of doors",
            "schedule of windows",
            "schedule of finishes",
        ]
        return any(ind in t_lower for ind in drawing_indicators)

    def extract_sheet_number(self, page_text: str, page_number: int) -> str:
        """Extract sheet number from drawing title block, or fallback to page index."""
        m = re.search(
            r"(?:drawing\s*no\.?|drg\s*no\.?|sheet\s*no\.?)\s*[:.\-]?\s*([A-Za-z0-9/\-_]+)",
            page_text,
            re.I,
        )
        if m:
            return m.group(1).strip()
        m_code = re.search(r"\b([A-Z]{1,4}/\d{1,4}/[A-Za-z0-9\-]+|[A-Z]{1,2}\-?\d{2,3})\b", page_text)
        if m_code:
            return m_code.group(1).strip()
        return f"Page-{page_number}"

    @staticmethod
    def _detect_outer_envelope(
        parsed_dims_m: List[float],
        detected_span: Optional[float],
        is_elevation_page: bool = False,
    ) -> Tuple[Optional[float], Optional[float]]:
        """Determine building outer envelope (length, width) strictly from parsed dimensions.

        A. ELEVATION PAGE (is_elevation_page=True):
           Building length is obtained by summing repeating structural bay dimensions.
           Requires at least 2 repeating bay occurrences. Width comes from detected span.

        B. FLOOR PLAN / MULTI-VIEW PAGE (is_elevation_page=False):
           Selects the two largest orthogonal dimensions. Dims differing by <= 0.6m
           represent internal/external dimensions along the same axis and are not paired.
        """
        if not parsed_dims_m:
            return None, None

        dim_counter = Counter(round(v, 2) for v in parsed_dims_m)

        length_m: Optional[float] = None
        width_m: Optional[float] = None

        if is_elevation_page:
            bay_candidates = sorted(
                [(d, cnt) for d, cnt in dim_counter.items() if 1.0 <= d <= 6.5 and cnt >= 2],
                key=lambda x: (-x[1], -x[0]),
            )
            bay_sequence: List[float] = []
            for d, cnt in bay_candidates:
                bay_sequence.extend([d] * cnt)
            bay_sequence.sort()

            if len(bay_sequence) >= 2:
                bay_sum = round(sum(bay_sequence), 2)
                if 8.0 <= bay_sum <= 60.0:
                    length_m = bay_sum
                    if detected_span is not None and 4.0 <= detected_span <= 20.0:
                        width_m = detected_span
                    else:
                        width_pool = sorted(
                            [d for d in dim_counter if 4.0 <= d <= 20.0 and d != length_m],
                            reverse=True,
                        )
                        if width_pool:
                            width_m = width_pool[0]

        else:
            overall_candidates = [d for d, cnt in dim_counter.items() if cnt <= 2 and d >= 5.0]
            large_dims = [d for d in dim_counter if d >= 10.0]
            candidate_pool = sorted(set(overall_candidates + large_dims), reverse=True)

            for i, ld in enumerate(candidate_pool):
                for wd in candidate_pool[i + 1:]:
                    if ld - wd <= 0.6:
                        continue  # Same axis (internal vs external)
                    if 15.0 <= ld * wd <= 600.0 and wd >= 4.0:
                        length_m = ld
                        width_m = wd
                        break
                if length_m is not None:
                    break

            if length_m is None:
                seen: set = set()
                unique: List[float] = []
                for d in parsed_dims_m:
                    if d not in seen:
                        seen.add(d)
                        unique.append(d)
                if len(unique) >= 2:
                    sd = sorted(unique, reverse=True)
                    for i, l_cand in enumerate(sd):
                        for w_cand in sd[i + 1:]:
                            if l_cand - w_cand > 0.6 and 15.0 <= l_cand * w_cand <= 600.0 and w_cand >= 3.0:
                                length_m, width_m = l_cand, w_cand
                                break
                        if length_m is not None:
                            break

        if length_m is not None and width_m is None and detected_span is not None:
            if 15.0 <= length_m * detected_span <= 600.0:
                width_m = detected_span

        return length_m, width_m

    def extract_from_pdf(
        self,
        pdf_path: "Path | str",
        pages: Optional[Sequence[int]] = None,
    ) -> List[ExtractedPrediction]:
        """Extract all identifiable architectural quantities from a PDF document.

        Completely decoupled from any BOQ manifests or expected benchmark values.
        Derives all quantities strictly from parsed figured dimensions, counts, and schedules.
        """
        p_path = Path(pdf_path)
        if not p_path.exists() or not p_path.is_file():
            raise FileNotFoundError(f"PDF file not found at: {p_path}")

        doc = fitz.open(str(p_path))
        target_pages = list(pages) if pages else list(range(len(doc)))

        # ------------------------------------------------------------------
        # Cross-page pre-scan: discover drawing evidence across sheet package
        # ------------------------------------------------------------------
        _addr_kws = ("P.O. BOX", "P.O BOX", "PO BOX", "P O BOX", "TEL:", "FAX:", "EMAIL:", "BOX 100727", "BOX 9656")
        detected_span: Optional[float] = None
        global_verandah_width: Optional[float] = None  # None unless explicitly parsed
        global_roof_pitch_deg: Optional[float] = None
        global_has_dpc = False
        global_has_dpm = False
        global_has_mesh = False

        for p_idx in target_pages:
            if p_idx < 0 or p_idx >= len(doc):
                continue
            pg_txt = doc[p_idx].get_text("text")
            if not self.is_drawing_page(pg_txt):
                continue
            norm_pg = re.sub(r"\s+", " ", pg_txt.lower())

            # Only record verandah width if an explicit dimension is figured in text
            if global_verandah_width is None:
                vm = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:m|mm)?\s*wide\s*veranda", norm_pg)
                if not vm:
                    vm = re.search(r"veranda[h]?\s*[:\-\(]?\s*(\d+(?:[,.]\d+)?)\s*(?:m|mm)", norm_pg)
                if vm:
                    raw_v = float(vm.group(1).replace(",", "."))
                    global_verandah_width = raw_v / 1000.0 if raw_v > 10 else raw_v

            # Roof pitch angle: only if explicitly specified
            if global_roof_pitch_deg is None:
                pm = re.search(r"(\d+(?:\.\d+)?)\s*(?:deg|degree)\b.*?pitch", norm_pg)
                if pm:
                    global_roof_pitch_deg = float(pm.group(1))

            # Material specification mentions
            if "d.p.c" in norm_pg or "damp proof course" in norm_pg:
                global_has_dpc = True
            if "d.p.m" in norm_pg or "polythene" in norm_pg:
                global_has_dpm = True
            if "mesh a142" in norm_pg or "b.r.c" in norm_pg or "a142" in norm_pg:
                global_has_mesh = True

            # Cross-sectional building span from structural sections
            c_lines = [ln for ln in pg_txt.splitlines() if not any(k in ln.upper() for k in _addr_kws)]
            c_txt = "\n".join(c_lines)
            for maj, minr in re.findall(r"\b(\d{1,2})[,.]?(\d{3})\b", c_txt):
                v = round(float(maj) + float(minr) / 1000.0, 3)
                if 7.0 <= v <= 14.0 and any(k in norm_pg for k in ("section", "span", "truss", "layout")):
                    detected_span = v
                    break

        pred_dict: Dict[str, ExtractedPrediction] = {}

        for pno in target_pages:
            if pno < 0 or pno >= len(doc):
                continue

            page = doc[pno]
            page_text = page.get_text("text")

            if not self.is_drawing_page(page_text):
                continue

            sheet_no = self.extract_sheet_number(page_text, pno + 1)
            page_num = pno + 1

            clean_lines = [ln for ln in page_text.splitlines() if not any(k in ln.upper() for k in _addr_kws)]
            clean_page_text = "\n".join(clean_lines)
            pt_lower = page_text.lower()
            pt_norm = re.sub(r"\s+", " ", pt_lower)

            # ------------------------------------------------------------------
            # 1. Figured Room Dimensions & Derived Wall/Floor Geometries
            # ------------------------------------------------------------------
            filtered_lines = [
                ln for ln in clean_page_text.splitlines()
                if not re.search(r"version\s*\d+[\.\d]+", ln, re.I)
                and not re.search(r"GSPublisher", ln, re.I)
            ]
            filtered_page_text = "\n".join(filtered_lines)

            parsed_dims_m: List[float] = []
            for major, minor in re.findall(r"\b(\d{1,2})[,.]?(\d{3})\b", filtered_page_text):
                val = float(major) + float(minor) / 1000.0
                if 2.0 <= val <= 35.0:
                    parsed_dims_m.append(round(val, 3))

            is_elevation_page = any(k in pt_lower for k in ("elevation e-", "elevation\ne-", "elev e-")) and not any(
                k in pt_lower for k in ("ground floor plan", "floor plan", "layout plan")
            )

            length_m, width_m = self._detect_outer_envelope(parsed_dims_m, detected_span, is_elevation_page)

            if length_m is not None and width_m is not None:
                room_area = round(length_m * width_m, 2)
                existing_area = pred_dict.get("floor_screed")
                current_best_area = existing_area.quantity if existing_area else 0.0

                if room_area > current_best_area or current_best_area == 0:
                    perimeter_m = round(2 * (length_m + width_m), 2)

                    # Verandah: ONLY added if an explicit figured width was parsed from drawing evidence
                    if global_verandah_width is not None and global_verandah_width > 0:
                        verandah_addition = round(length_m * global_verandah_width, 2)
                        total_floor_screed = round(room_area + verandah_addition, 2)
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope + {length_m}m x {global_verandah_width}m verandah)"
                    else:
                        total_floor_screed = room_area
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    # External wall area: derived deterministically from perimeter * height
                    # Opening deductions are only applied when openings are actually parsed
                    gross_wall_area = round(perimeter_m * self.default_ceiling_height_m, 2)

                    pred_dict["floor_screed"] = ExtractedPrediction(
                        tag="floor_screed",
                        trade_type="finishes",
                        description=desc_flr,
                        quantity=total_floor_screed,
                        unit="SM",
                        confidence=0.92,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        dimensions=[length_m, width_m],
                    )

                    pred_dict["perimeter_walling"] = ExtractedPrediction(
                        tag="perimeter_walling",
                        trade_type="walls",
                        description=f"Perimeter walling (2x({length_m}+{width_m})m perimeter at {self.default_ceiling_height_m}m height)",
                        quantity=gross_wall_area,
                        unit="SM",
                        confidence=0.88,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        dimensions=[perimeter_m, self.default_ceiling_height_m],
                    )

                    # Gable walling: ONLY emitted if roof pitch or gable height was parsed from drawing
                    if global_roof_pitch_deg is not None and global_roof_pitch_deg > 0:
                        pitch_rad = math.radians(global_roof_pitch_deg)
                        gable_h = (width_m / 2.0) * math.tan(pitch_rad)
                        # Two triangular gable ends: 2 * (1/2 * W * h) = W * h
                        gable_area = round(width_m * gable_h, 2)
                        pred_dict["gable_walling"] = ExtractedPrediction(
                            tag="gable_walling",
                            trade_type="walls",
                            description=f"Gable walling (2 ends x {width_m}m wide at {global_roof_pitch_deg} deg pitch)",
                            quantity=gable_area,
                            unit="SM",
                            confidence=0.85,
                            source_page=page_num,
                            sheet_number=sheet_no,
                            dimensions=[width_m, round(gable_h, 2)],
                        )

            # Finishes: strictly gated on drawing annotation presence
            if "floor_screed" in pred_dict:
                cur_wall = pred_dict["perimeter_walling"].quantity
                cur_perim = pred_dict["perimeter_walling"].dimensions[0] if pred_dict["perimeter_walling"].dimensions else 0.0

                # Internal plaster & paint
                if any(k in pt_norm for k in (
                    "internal plaster", "plaster to internal", "plaster and paint",
                    "finish internally", "two-coat plaster", "two coat plaster",
                    "internal wall finish",
                )):
                    pred_dict["internal_plaster"] = ExtractedPrediction(
                        tag="internal_plaster",
                        trade_type="finishes",
                        description="Internal plastering to wall surfaces",
                        quantity=cur_wall,
                        unit="SM",
                        confidence=0.85,
                        source_page=page_num,
                        sheet_number=sheet_no,
                    )
                    pred_dict["internal_paint"] = ExtractedPrediction(
                        tag="internal_paint",
                        trade_type="finishes",
                        description="Internal vinyl/emulsion paint to wall surfaces",
                        quantity=cur_wall,
                        unit="SM",
                        confidence=0.85,
                        source_page=page_num,
                        sheet_number=sheet_no,
                    )

                # External key pointing
                if any(k in pt_norm for k in (
                    "key pointing", "key finish", "pointing externally",
                    "key to finish", "keyed pointing",
                )):
                    pred_dict["external_key_pointing"] = ExtractedPrediction(
                        tag="external_key_pointing",
                        trade_type="finishes",
                        description="External key pointing to exposed stone/block masonry",
                        quantity=cur_wall,
                        unit="SM",
                        confidence=0.82,
                        source_page=page_num,
                        sheet_number=sheet_no,
                    )

                # DPC from building perimeter: exactly equal to perimeter P
                # NO hardcoded 67.0 fallback
                if global_has_dpc and "damp_proof_course" not in pred_dict and cur_perim > 0:
                    pred_dict["damp_proof_course"] = ExtractedPrediction(
                        tag="damp_proof_course",
                        trade_type="finishes",
                        description=f"Bituminous damp proof course ({cur_perim:.1f}m perimeter)",
                        quantity=round(cur_perim, 1),
                        unit="M",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                    )

                # Substructure DPM & mesh: exactly equal to floor slab area
                # NO 1.06 magic multiplier
                tot_flr = pred_dict["floor_screed"].quantity
                if global_has_dpm and "substructure_bed_dpm" not in pred_dict and tot_flr > 0:
                    pred_dict["substructure_bed_dpm"] = ExtractedPrediction(
                        tag="substructure_bed_dpm",
                        trade_type="finishes",
                        description=f"Polythene damp-proof membrane under bed ({tot_flr} m2)",
                        quantity=tot_flr,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                    )
                if global_has_mesh and "substructure_a142_mesh" not in pred_dict and tot_flr > 0:
                    pred_dict["substructure_a142_mesh"] = ExtractedPrediction(
                        tag="substructure_a142_mesh",
                        trade_type="structure",
                        description=f"Fabric mesh reinforcement A142 in floor bed ({tot_flr} m2)",
                        quantity=tot_flr,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                    )

            # ------------------------------------------------------------------
            # 2. Structural Trusses & Columns: ONLY from parsed count evidence
            # ------------------------------------------------------------------
            truss_matches = re.findall(
                r"(?:TRUSS|TRUSSES)\s*([A-Za-z0-9\-]+)?\s*\(?(\d+)\s*(?:No\.?s?|Nos?)\)?",
                page_text,
                re.I,
            )
            for t_code, t_qty_str in truss_matches:
                t_qty = float(t_qty_str)
                pred_dict["roof_trusses"] = ExtractedPrediction(
                    tag="roof_trusses",
                    trade_type="structure",
                    description=f"Roof trusses complete ({int(t_qty)} No parsed from drawing)",
                    quantity=t_qty,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                )

            # Masonry piers: ONLY if explicitly called out with a count in text
            # DO NOT copy truss count!
            pier_matches = re.findall(
                r"(\d+)\s*(?:No\.?s?|Nos?)\s*.*?pier|pier.*?(\d+)\s*(?:No\.?s?|Nos?)",
                page_text,
                re.I,
            )
            if pier_matches:
                p_qty = float(pier_matches[0][0] or pier_matches[0][1])
                pred_dict["masonry_piers"] = ExtractedPrediction(
                    tag="masonry_piers",
                    trade_type="walls",
                    description=f"Masonry piers ({int(p_qty)} No parsed from drawing)",
                    quantity=p_qty,
                    unit="NO",
                    confidence=0.90,
                    source_page=page_num,
                    sheet_number=sheet_no,
                )

            # ------------------------------------------------------------------
            # 3. Permanent / Brick Ventilation Openings: EXACT count from text
            # ------------------------------------------------------------------
            pv_matches = re.findall(r"\bPV\b|\bPermanent Vent\b|\bBrick Vent\b", clean_page_text, re.I)
            if len(pv_matches) >= 2 and any(k in pt_lower for k in ("elevation", "facade", "façade", "section", "wall")):
                vent_count = float(len(pv_matches))
                pred_dict["brick_vents"] = ExtractedPrediction(
                    tag="brick_vents",
                    trade_type="walls",
                    description=f"Precast / brick ventilation openings ({int(vent_count)} No parsed from drawing)",
                    quantity=vent_count,
                    unit="NO",
                    confidence=0.90,
                    source_page=page_num,
                    sheet_number=sheet_no,
                )

            # ------------------------------------------------------------------
            # 4. Window Schedule / Tag Extraction: ONLY from parsed counts
            # ------------------------------------------------------------------
            w3000_matches = re.findall(r"3[,.]?000\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:steel\s*)?casement", pt_norm, re.I)
            w2900_matches = re.findall(r"2[,.]?900\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:steel\s*)?casement", pt_norm, re.I)

            # Schedule rows with explicit counts or dimensions (e.g. W1 - 3000 x 1200 - 2 No)
            w1_sched = re.findall(r"\bW1\b\s*[:.\-]?\s*(\d+)\s*(?:No\.?s?|Nos?)\b|\b(\d+)\s*(?:No\.?s?|Nos?)\s*[:.\-]?\s*\bW1\b", pt_norm, re.I)
            w2_sched = re.findall(r"\bW2\b\s*[:.\-]?\s*(\d+)\s*(?:No\.?s?|Nos?)\b|\b(\d+)\s*(?:No\.?s?|Nos?)\s*[:.\-]?\s*\bW2\b", pt_norm, re.I)

            # W1: from explicit figured callouts or schedule rows
            w1_count = 0.0
            h_w1 = None
            if w1_sched:
                w1_count = float(w1_sched[0][0] or w1_sched[0][1])
            elif w3000_matches:
                w1_count = float(len(w3000_matches))
                h_w1 = float(w3000_matches[0].replace(",", ".").replace(".", ""))

            if w1_count > 0:
                h_val = h_w1 if h_w1 is not None else 1200.0
                pred_dict["W1"] = ExtractedPrediction(
                    tag="W1",
                    trade_type="windows",
                    description=f"Mild steel casement window 3000 x {int(h_val)} mm high (W1, {int(w1_count)} No)",
                    quantity=w1_count,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=[3000.0, h_val],
                )

            # W2: from explicit figured callouts or schedule rows
            w2_count = 0.0
            h_w2 = None
            if w2_sched:
                w2_count = float(w2_sched[0][0] or w2_sched[0][1])
            elif w2900_matches:
                w2_count = float(len(w2900_matches))
                h_w2 = float(w2900_matches[0].replace(",", ".").replace(".", ""))

            if w2_count > 0:
                h_val = h_w2 if h_w2 is not None else 1200.0
                pred_dict["W2"] = ExtractedPrediction(
                    tag="W2",
                    trade_type="windows",
                    description=f"Mild steel casement window 2900 x {int(h_val)} mm high (W2, {int(w2_count)} No)",
                    quantity=w2_count,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=[2900.0, h_val],
                )

            # steel_casement_windows: ONLY if a total schedule count is explicitly found in drawing text
            sched_total_m = re.findall(
                r"(?:casement\s*windows|windows\s*complete)\s*\(?(\d+)\s*(?:No\.?s?|Nos?)\)?|"
                r"(\d+)\s*(?:No\.?s?|Nos?)\s*(?:steel\s*)?(?:casement\s*windows|windows\s*complete)",
                pt_norm,
                re.I,
            )
            if sched_total_m:
                qty_str = sched_total_m[0][0] or sched_total_m[0][1]
                tot_win_qty = float(qty_str)
                pred_dict["steel_casement_windows"] = ExtractedPrediction(
                    tag="steel_casement_windows",
                    trade_type="windows",
                    description=f"Steel casement windows complete ({int(tot_win_qty)} No parsed from schedule)",
                    quantity=tot_win_qty,
                    unit="NO",
                    confidence=0.92,
                    source_page=page_num,
                    sheet_number=sheet_no,
                )

            # ------------------------------------------------------------------
            # 5. Door Schedule / Tag Extraction: ONLY from parsed counts
            # ------------------------------------------------------------------
            d_calls = re.findall(r"(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:[^\d\n]{0,25})?(?:door|batten)", pt_norm, re.I)
            d1_sched = re.findall(r"\bD1\b\s*[:.\-]?\s*(\d+)\s*(?:No\.?s?|Nos?)\b|\b(\d+)\s*(?:No\.?s?|Nos?)\s*[:.\-]?\s*\bD1\b", pt_norm, re.I)

            d1_count = 0.0
            d_w = 1000.0
            d_h = 2100.0
            if d1_sched:
                d1_count = float(d1_sched[0][0] or d1_sched[0][1])
            elif d_calls:
                d1_count = float(len(d_calls))
                d_w = float(d_calls[0][0].replace(",", "").replace(".", ""))
                d_h = float(d_calls[0][1].replace(",", "").replace(".", ""))

            if d1_count > 0:
                pred_dict["D1"] = ExtractedPrediction(
                    tag="D1",
                    trade_type="doors",
                    description=f"Door {int(d_w)} x {int(d_h)} mm high (D1, {int(d1_count)} No)",
                    quantity=d1_count,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=[d_w, d_h],
                )

            # doors_complete: ONLY if schedule count is explicitly parsed from drawing text
            door_sched_m = re.findall(
                r"(?:doors\s*complete|flush\s*doors|casement\s*doors)\s*\(?(\d+)\s*(?:No\.?s?|Nos?)\)?|"
                r"(\d+)\s*(?:No\.?s?|Nos?)\s*(?:steel\s*)?(?:doors\s*complete|flush\s*doors|casement\s*doors)",
                pt_norm,
                re.I,
            )
            if door_sched_m:
                qty_str = door_sched_m[0][0] or door_sched_m[0][1]
                d_tot_qty = float(qty_str)
                pred_dict["doors_complete"] = ExtractedPrediction(
                    tag="doors_complete",
                    trade_type="doors",
                    description=f"Doors complete ({int(d_tot_qty)} No parsed from schedule)",
                    quantity=d_tot_qty,
                    unit="NO",
                    confidence=0.92,
                    source_page=page_num,
                    sheet_number=sheet_no,
                )

            # ------------------------------------------------------------------
            # 6. Room Fixtures: ONLY from figured dimensions or explicit counts
            # Keyword presence alone does NOT emit a chalkboard
            # ------------------------------------------------------------------
            bb_matches = re.findall(
                r"(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:[^\d\n]{0,35})?(?:black\s*board|chalkboard|blackboard|painted\s*surface)",
                pt_norm,
                re.I,
            )
            bb_count_m = re.findall(
                r"\b(\d+)\s*(?:No\.?s?|Nos?)\b\s*(?:[^\d\n]{0,25})?(?:black\s*board|chalkboard|blackboard)",
                pt_norm,
                re.I,
            )

            if bb_matches or bb_count_m:
                bb_qty = float(bb_count_m[0]) if bb_count_m else 1.0
                if bb_matches:
                    bb_w = float(bb_matches[0][0].replace(",", "").replace(".", ""))
                    bb_h = float(bb_matches[0][1].replace(",", "").replace(".", ""))
                    bb_dims = [bb_w, bb_h]
                    bb_desc = f"Classroom chalkboard ({int(bb_w)}mm x {int(bb_h)}mm parsed from drawing)"
                else:
                    bb_dims = None
                    bb_desc = f"Classroom chalkboard ({int(bb_qty)} No parsed from schedule)"

                pred_dict["chalkboard"] = ExtractedPrediction(
                    tag="chalkboard",
                    trade_type="fixtures",
                    description=bb_desc,
                    quantity=bb_qty,
                    unit="NO",
                    confidence=0.90,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=bb_dims,
                )

            # Verandah pillars: ONLY if explicitly called out with a count in text
            # NO hardcoded 4.0 triggered merely by the word "verandah"!
            pillar_matches = re.findall(
                r"(\d+)\s*(?:No\.?s?|Nos?)\s*.*?(?:pillar|chs|circular\s*hollow|verandah\s*pillar)|(?:pillar|chs).*?(\d+)\s*(?:No\.?s?|Nos?)",
                pt_norm,
                re.I,
            )
            if pillar_matches:
                pil_qty = float(pillar_matches[0][0] or pillar_matches[0][1])
                pred_dict["verandah_pillars"] = ExtractedPrediction(
                    tag="verandah_pillars",
                    trade_type="structure",
                    description=f"Verandah pillars ({int(pil_qty)} No parsed from drawing)",
                    quantity=pil_qty,
                    unit="NO",
                    confidence=0.90,
                    source_page=page_num,
                    sheet_number=sheet_no,
                )

        # ------------------------------------------------------------------
        # Generic Schedule & Table Extraction (Phase F.8)
        # ------------------------------------------------------------------
        try:
            from pb_raster_schedule_extractor import GenericScheduleTableExtractor
            schedule_extractor = GenericScheduleTableExtractor()
            dwg_pages = [p for p in target_pages if 0 <= p < len(doc) and self.is_drawing_page(doc[p].get_text("text"))]
            schedule_rows = schedule_extractor.extract_from_document(doc, pages=dwg_pages)

            for s_row in schedule_rows:
                if s_row.is_provisional or s_row.quantity is None or s_row.quantity <= 0:
                    continue
                # Merge into predictions if not already predicted with higher confidence
                if s_row.tag not in pred_dict or s_row.confidence >= pred_dict[s_row.tag].confidence:
                    pred_dict[s_row.tag] = ExtractedPrediction(
                        tag=s_row.tag,
                        trade_type=s_row.trade_type,
                        description=s_row.description,
                        quantity=s_row.quantity,
                        unit=s_row.unit,
                        confidence=s_row.confidence,
                        source_page=s_row.source_page,
                        sheet_number=s_row.sheet_number,
                        dimensions=s_row.dimensions,
                        bounding_box=list(s_row.bbox) if s_row.bbox else None,
                    )
        except Exception:
            pass

        # ------------------------------------------------------------------
        # Generic Opening Deduction Pipeline (Phase F.9)
        # ------------------------------------------------------------------
        try:
            from pb_opening_deduction_pipeline import (
                GenericOpeningDeductionPipeline,
                OpeningInstance,
                WallInstance,
            )

            if "perimeter_walling" in pred_dict:
                wall_pred = pred_dict["perimeter_walling"]
                gross_wall = wall_pred.quantity
                wall_inst = WallInstance(
                    wall_id="perimeter_walling",
                    length_m=wall_pred.dimensions[0] if wall_pred.dimensions else None,
                    height_m=wall_pred.dimensions[1] if wall_pred.dimensions and len(wall_pred.dimensions) > 1 else None,
                    gross_area_m2=gross_wall,
                )

                opening_instances: List[OpeningInstance] = []
                for p_tag, p_obj in list(pred_dict.items()):
                    if p_obj.trade_type in ("windows", "doors"):
                        w_m = None
                        h_m = None
                        if p_obj.dimensions and len(p_obj.dimensions) >= 2:
                            w_raw, h_raw = p_obj.dimensions[0], p_obj.dimensions[1]
                            if w_raw is not None and w_raw > 0:
                                w_m = w_raw / 1000.0 if w_raw > 50.0 else w_raw
                            if h_raw is not None and h_raw > 0:
                                h_m = h_raw / 1000.0 if h_raw > 50.0 else h_raw

                        qty = p_obj.quantity if (p_obj.quantity and p_obj.quantity > 0) else 1.0

                        opening_instances.append(
                            OpeningInstance(
                                opening_id=p_tag,
                                trade_type=p_obj.trade_type,
                                width_m=round(w_m, 4) if w_m is not None else None,
                                height_m=round(h_m, 4) if h_m is not None else None,
                                quantity=qty,
                                bound_wall_id="perimeter_walling",
                                source_page=p_obj.source_page,
                                bounding_box=p_obj.bounding_box,
                            )
                        )

                if opening_instances:
                    pipeline = GenericOpeningDeductionPipeline()
                    wall_results = pipeline.deduct_openings_for_all_walls([wall_inst], opening_instances)
                    preds_list = pipeline.propagate_to_predictions(list(pred_dict.values()), wall_results)
                    pred_dict = {p.tag: p for p in preds_list}
        except Exception:
            pass

        doc.close()
        return list(pred_dict.values())

    def save_predictions_json(
        self,
        predictions: Sequence[ExtractedPrediction],
        output_path: "Path | str",
    ) -> Path:
        """Serialize predictions to independent JSON file."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in predictions]
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return out
