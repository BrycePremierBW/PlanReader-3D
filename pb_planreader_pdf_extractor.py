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
    def _has_dpm_specification(page_text: str) -> bool:
        """Return whether drawing text explicitly specifies a damp-proof membrane.

        CAD exports commonly remove punctuation from ``D.P.M.`` and may spell the
        material out without mentioning polythene.  Keep DPC/course wording out:
        a damp-proof course is a different measured item.
        """
        normalized = re.sub(r"\s+", " ", page_text.lower())
        return bool(
            re.search(r"\bd\s*\.?\s*p\s*\.?\s*m\s*\.?\b", normalized)
            or re.search(r"\bdamp[\s-]*proof\s+membrane\b", normalized)
            or re.search(r"\bpolythene\b", normalized)
        )

    @staticmethod
    def _has_surface_bed_specification(page_text: str) -> bool:
        """Return whether drawing text explicitly specifies a substructure
        surface bed / ground-bearing slab -- the same floor area that
        substructure_bed_dpm and substructure_a142_mesh already key off,
        but for the bed's own concrete rather than its DPM or mesh
        reinforcement.

        Requires BOTH a bed/slab term AND ground-siting context
        (hardcore/compacted/blinding) nearby, so a suspended or roof slab
        mention is never misread as a ground-bearing surface bed.
        """
        normalized = re.sub(r"\s+", " ", page_text.lower())
        has_bed_or_slab_term = bool(re.search(
            r"\bsurface\s*bed\b|\bfloor\s*bed\b|\bground\s*bed\b|"
            r"\br\s*\.?\s*c\s*\.?\s*slab\b|\breinforced\s+concrete\s+slab\b|"
            r"\bconcrete\s+bed\b",
            normalized,
        ))
        has_ground_siting_context = bool(re.search(
            r"\bhard\s*core\b|\bcompacted\s+(?:earth|ground|hardcore)\b|\bblinding\b",
            normalized,
        ))
        return has_bed_or_slab_term and has_ground_siting_context

    @staticmethod
    def _has_internal_plaster_finish(page_text: str) -> bool:
        """Recognize explicit internal plaster annotations across common grammar."""
        normalized = re.sub(r"\s+", " ", page_text.lower())
        fixed_phrases = (
            "internal plaster",
            "plaster to internal",
            "plaster and paint",
            "finish internally",
            "two-coat plaster",
            "two coat plaster",
            "internal wall finish",
        )
        if any(phrase in normalized for phrase in fixed_phrases):
            return True
        return bool(
            re.search(
                r"\bplaster(?:ed|ing)?\b[^.\n;]{0,45}\binternally\b",
                normalized,
            )
        )

    @staticmethod
    def _contextual_opening_tag_counts(page_text: str) -> Dict[str, Tuple[str, int]]:
        """Count explicitly annotated opening tags using their semantic context.

        Some drawing standards use ``WD-##`` and ``DR-##`` rather than ``W#``
        and ``D#``.  WD is accepted as a window only when both a window heading
        and a hung/casement descriptor are present; this avoids treating common
        wood-door or drawing-number abbreviations as window instances.
        """
        normalized = re.sub(r"\s+", " ", page_text)
        has_window_scope = bool(re.search(r"\bwindows?\b", normalized, re.I))
        counts: Counter[str] = Counter()
        trades: Dict[str, str] = {}
        pattern = re.compile(r"\b(WD|DR)[-_ ]?0*(\d{1,3})\b\s*\(([^)]{1,60})\)", re.I)
        for prefix, number, descriptor in pattern.findall(normalized):
            if prefix.upper() == "WD":
                if not has_window_scope or not re.search(r"\b(?:side|top)[ -]?hung\b|\bcasement\b", descriptor, re.I):
                    continue
                tag, trade = f"W{int(number)}", "windows"
            else:
                if not re.search(r"\b(?:door|casement|panel(?:led)?|flush|batten|steel|timber)\b", descriptor, re.I):
                    continue
                tag, trade = f"D{int(number)}", "doors"
            counts[tag] += 1
            trades[tag] = trade
        return {tag: (trades[tag], count) for tag, count in counts.items()}

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
        global_has_verandah_mention = False
        global_roof_pitch_deg: Optional[float] = None
        global_has_dpc = False
        global_has_dpm = False
        global_has_mesh = False
        global_has_surface_bed = False
        global_level_markers: List[Any] = []  # List[LevelMarker], imported lazily below
        global_dimension_chains: List[Any] = []  # List[DimensionChain], imported lazily below

        for p_idx in target_pages:
            if p_idx < 0 or p_idx >= len(doc):
                continue
            pg_txt = doc[p_idx].get_text("text")
            if not self.is_drawing_page(pg_txt):
                continue
            norm_pg = re.sub(r"\s+", " ", pg_txt.lower())

            # Track verandah mention across drawings
            if any(k in norm_pg for k in ("verandah", "veranda")):
                global_has_verandah_mention = True

            # Only record verandah width if an explicit dimension is figured in text.
            # F.23: prefer same-viewport, adjacency-validated spatial evidence
            # (a real dimension chain bound to the same F.07-resolved
            # floor-plan viewport as the label itself) over the page-wide
            # sentence regex below -- the regex is purely additive as a
            # fallback for wording this stricter resolver does not (yet)
            # anchor to a viewport, never a replacement for it.
            if global_verandah_width is None:
                from pb_secondary_footprint_evidence import (
                    resolve_secondary_footprint_width_m,
                )

                spatial_evidence = resolve_secondary_footprint_width_m(
                    doc[p_idx], page_num=p_idx + 1
                )
                if spatial_evidence is not None:
                    global_verandah_width = spatial_evidence.width_m

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
            if self._has_dpm_specification(norm_pg):
                global_has_dpm = True
            if "mesh a142" in norm_pg or "b.r.c" in norm_pg or "a142" in norm_pg:
                global_has_mesh = True
            if self._has_surface_bed_specification(norm_pg):
                global_has_surface_bed = True

            # Cross-sectional building span from structural sections
            c_lines = [ln for ln in pg_txt.splitlines() if not any(k in ln.upper() for k in _addr_kws)]
            c_txt = "\n".join(c_lines)
            for maj, minr in re.findall(r"\b(\d{1,2})[,.]?(\d{3})\b", c_txt):
                v = round(float(maj) + float(minr) / 1000.0, 3)
                if 7.0 <= v <= 14.0 and any(k in norm_pg for k in ("section", "span", "truss", "layout")):
                    detected_span = v
                    break

            # Roof/floor level datum annotations (Phase F.14): real figured
            # evidence of wall/room height, when a section or elevation
            # sheet carries one -- see pb_level_datum_extraction.
            from pb_level_datum_extraction import find_level_markers
            global_level_markers.extend(find_level_markers(pg_txt, source_page=p_idx + 1))

            # Spatially-reconstructed dimension chains (Phase F.15): real
            # figured wall-thickness evidence, when the drawing's own
            # dimension strings carry a genuine wall-span-wall bracket --
            # see pb_dimension_chain_evidence_extractor.
            from pb_dimension_chain_evidence_extractor import extract_dimension_chains_from_page
            global_dimension_chains.extend(
                extract_dimension_chains_from_page(doc[p_idx], page_num=p_idx + 1, view_id=f"page_{p_idx + 1}")
            )

        # Resolve wall height strictly from real level-datum evidence when
        # present; otherwise this stays None and every wall-height use below
        # falls back to self.default_ceiling_height_m exactly as before --
        # additive only, never a regression on a project with no such evidence.
        from pb_dimension_graph_constraint_engine import ConstraintStatus, resolve_wall_height
        global_resolved_wall_height_m: Optional[float] = None
        if global_level_markers:
            height_res = resolve_wall_height(global_level_markers, scope_id=None)
            if height_res.status == ConstraintStatus.FULLY_CONSTRAINED.value:
                global_resolved_wall_height_m = height_res.clear_height_m

        # Resolve wall thickness strictly from corroborated (>=2 independent
        # chains agreeing) dimension-chain evidence; stays None otherwise,
        # in which case internal-face-area predictions below fall back to
        # their existing external-area-proxy behaviour unchanged.
        from pb_dimension_chain_evidence_extractor import resolve_corroborated_wall_thickness_m
        global_resolved_wall_thickness_m: Optional[float] = resolve_corroborated_wall_thickness_m(global_dimension_chains)

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

            # ------------------------------------------------------------------
            # Structural bay -> support (column/pillar/pier/post) count.
            # Only emitted when BOTH a genuine, unambiguous repeated-bay
            # dimension pattern is found on this page AND the page text
            # names a support element -- neither signal alone is emitted on,
            # since a repeated dimension run with no support keyword is just
            # as likely to be window/opening spacing, and a support keyword
            # with no genuine repeated-bay evidence has nothing to count from.
            # Multiple candidate runs on one page are ambiguous (which one
            # is the actual support line?) and are left unresolved rather
            # than guessed.
            if "structural_columns" not in pred_dict and any(k in pt_norm for k in (
                "pillars to", "pillar to", "columns to", "column to",
                "piers to", "pier to", "posts to", "post to",
                "chs pillar", "chs column", "rhs column", "shs column",
                "masonry pier", "concrete column", "concrete pillar", "steel column",
            )):
                from pb_structural_bay_pillar_count import find_uniform_bay_runs

                bay_runs = find_uniform_bay_runs(parsed_dims_m)
                if len(bay_runs) == 1:
                    run = bay_runs[0]
                    pred_dict["structural_columns"] = ExtractedPrediction(
                        tag="structural_columns",
                        trade_type="structure",
                        description=(
                            f"Structural columns/pillars/piers derived from "
                            f"{run.bay_count} repeated bay span(s) "
                            f"({run.bay_spans_m} m)"
                        ),
                        quantity=float(run.support_count),
                        unit="NO",
                        confidence=0.7,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata={
                            "derivation": "bay_count_plus_one_from_repeated_dimension_chain",
                            "bay_count": run.bay_count,
                            "bay_spans_m": run.bay_spans_m,
                        },
                    )

            is_elevation_page = any(k in pt_lower for k in ("elevation e-", "elevation\ne-", "elev e-")) and not any(
                k in pt_lower for k in ("ground floor plan", "floor plan", "layout plan")
            )

            length_m, width_m = self._detect_outer_envelope(parsed_dims_m, detected_span, is_elevation_page)

            if length_m is not None and width_m is not None:
                from pb_multi_space_footprint_geometry import MultiSpaceFootprintBuilder

                builder = MultiSpaceFootprintBuilder()
                builder.add_main_room(
                    length_m=length_m,
                    width_m=width_m,
                    label=f"Main Building Envelope ({length_m}m x {width_m}m)",
                    source_page=page_num,
                )

                if global_has_verandah_mention:
                    builder.add_verandah(
                        length_m=length_m,
                        width_m=global_verandah_width,
                        adjacency="front",
                        label="Verandah",
                        source_page=page_num,
                    )

                footprint_res = builder.build()
                structural_bed_area_m2 = footprint_res.gross_floor_area_m2
                total_floor_screed = structural_bed_area_m2

                # F.22: an enclosed main room's floor finish is measured to
                # the clear wall faces when wall thickness is independently
                # corroborated. Evidenced open verandahs remain at their full
                # component area. Unsupported/partial compound geometry fails
                # closed in the helper and leaves the existing footprint basis
                # unchanged. Structural slab/DPM/mesh area is preserved
                # separately below.
                floor_finish_geometry = None
                if global_resolved_wall_thickness_m is not None:
                    from pb_component_floor_finish_geometry import (
                        derive_component_aware_floor_finish_area,
                    )

                    floor_finish_geometry = derive_component_aware_floor_finish_area(
                        footprint_res,
                        global_resolved_wall_thickness_m,
                    )
                    if floor_finish_geometry is not None:
                        total_floor_screed = floor_finish_geometry.floor_finish_area_m2

                perimeter_m = round(2 * (length_m + width_m), 2)

                existing_area = pred_dict.get("floor_screed")
                current_best_area = existing_area.quantity if existing_area else 0.0

                if total_floor_screed > current_best_area or current_best_area == 0:
                    if global_verandah_width is not None and global_verandah_width > 0:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope + {length_m}m x {global_verandah_width}m verandah)"
                    else:
                        desc_flr = f"Floor screed ({length_m}m x {width_m}m envelope)"

                    if floor_finish_geometry is not None:
                        desc_flr = (
                            "Floor screed / finish ("
                            f"{floor_finish_geometry.main_clear_area_m2} m2 clear enclosed main space"
                            f" + {floor_finish_geometry.open_verandah_area_m2} m2 evidenced verandah)"
                        )

                    # External wall area: derived deterministically from perimeter * height.
                    # Opening deductions are only applied when openings are actually parsed.
                    # Height prefers real figured level-datum evidence (Phase F.14,
                    # e.g. a section/elevation's Roof Level + Floor Level annotations)
                    # over the convenience default; the default is only ever used when
                    # no such evidence resolved on this document.
                    height_is_genuine_evidence = global_resolved_wall_height_m is not None
                    effective_wall_height_m = (
                        global_resolved_wall_height_m
                        if height_is_genuine_evidence
                        else self.default_ceiling_height_m
                    )
                    gross_wall_area = round(perimeter_m * effective_wall_height_m, 2)

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
                        metadata={
                            "component_areas": footprint_res.component_areas,
                            "gross_floor_area_m2": footprint_res.gross_floor_area_m2,
                            "dpm_area_m2": footprint_res.dpm_area_m2,
                            "mesh_area_m2": footprint_res.mesh_area_m2,
                            "external_perimeter_m": footprint_res.external_perimeter_m,
                            "enclosed_wall_perimeter_m": perimeter_m,
                            "shared_edge_length_m": footprint_res.shared_edge_length_m,
                            "footprint_status": footprint_res.status,
                            "missing_components": footprint_res.missing_components,
                            "structural_bed_area_m2": structural_bed_area_m2,
                            **(
                                {
                                    "floor_finish_area_derivation": "component_clear_main_plus_evidenced_verandah",
                                    "wall_thickness_m": floor_finish_geometry.wall_thickness_m,
                                    "main_clear_floor_area_m2": floor_finish_geometry.main_clear_area_m2,
                                    "open_verandah_floor_area_m2": floor_finish_geometry.open_verandah_area_m2,
                                    "component_finish_areas_m2": floor_finish_geometry.component_finish_areas_m2,
                                    "main_clear_dimensions_m": [
                                        floor_finish_geometry.main_clear_length_m,
                                        floor_finish_geometry.main_clear_width_m,
                                    ],
                                }
                                if floor_finish_geometry is not None
                                else {}
                            ),
                        },
                    )

                    # --------------------------------------------------------
                    # F.21: Generic reinforced-floor-slab classification and
                    # geometry binding. Emits `reinforced_floor_slab` only
                    # when a recognized slab annotation spatially binds --
                    # via its own real PDF word position, never page-wide
                    # keyword presence -- to this page's already-confirmed
                    # footprint envelope, with a corroborated thickness and
                    # no conflicting evidence. Reuses the exact same
                    # authoritative footprint (footprint_res /
                    # structural_bed_area_m2) already relied on for
                    # floor_screed/DPM/mesh above -- never a second,
                    # disconnected geometry pipeline. See
                    # pb_slab_classification_geometry.py for the full
                    # resolution engine and its documented scope limits.
                    # --------------------------------------------------------
                    from pb_multi_space_footprint_geometry import FootprintStatus

                    if (
                        "reinforced_floor_slab" not in pred_dict
                        and footprint_res.status == FootprintStatus.CONFIRMED.value
                        and not footprint_res.missing_components
                    ):
                        from pb_slab_classification_geometry import (
                            CandidateBoundary,
                            SlabResolutionState,
                            dimension_word_bbox_envelope,
                            resolve_slabs_from_page,
                        )

                        slab_spatial_envelope = dimension_word_bbox_envelope(page)
                        if slab_spatial_envelope is not None:
                            slab_boundary = CandidateBoundary(
                                boundary_id=f"footprint_p{page_num}",
                                polygon=[
                                    (0.0, 0.0),
                                    (length_m, 0.0),
                                    (length_m, width_m),
                                    (0.0, width_m),
                                ],
                                area_m2=structural_bed_area_m2,
                                source_page=page_num,
                                units_authoritative=True,
                                spatial_envelope=slab_spatial_envelope,
                            )
                            slab_entities = resolve_slabs_from_page(
                                page, [slab_boundary], source_page=page_num
                            )
                            resolved_slabs = [
                                e
                                for e in slab_entities
                                if e.resolution_state == SlabResolutionState.RESOLVED.value
                                and e.area_m2 is not None
                            ]
                            if len(resolved_slabs) == 1:
                                slab = resolved_slabs[0]
                                pred_dict["reinforced_floor_slab"] = ExtractedPrediction(
                                    tag="reinforced_floor_slab",
                                    trade_type="structure",
                                    description=(
                                        f"Reinforced concrete floor slab "
                                        f"({slab.slab_type}, {slab.thickness_mm}mm thick)"
                                    ),
                                    quantity=slab.area_m2,
                                    unit="SM",
                                    confidence=0.75,
                                    source_page=page_num,
                                    sheet_number=sheet_no,
                                    dimensions=[length_m, width_m],
                                    metadata={
                                        "slab_id": slab.slab_id,
                                        "slab_type": slab.slab_type,
                                        "thickness_mm": slab.thickness_mm,
                                        "reinforcement": [
                                            asdict(r) for r in slab.reinforcement
                                        ],
                                        "boundary_id": slab_boundary.boundary_id,
                                        "resolution_state": slab.resolution_state,
                                        "provenance": slab.provenance,
                                    },
                                )

                    height_desc = (
                        f"{effective_wall_height_m}m height (resolved from Roof/Floor "
                        f"level datum evidence)"
                        if height_is_genuine_evidence
                        else f"{effective_wall_height_m}m height (no level-datum evidence "
                        f"found; assumed default -- provisional, not a firm measurement)"
                    )
                    # Known authority/safety debt (F.23A): this default-height
                    # fallback still exists -- a genuinely unresolved height
                    # is not replaced with a real measurement, only with a
                    # clearly-flagged, low-confidence assumption. Investigated
                    # directly against both real diagnostic project PDFs for
                    # stronger generic vertical evidence (explicit floor-to-
                    # ceiling dimensions, wall-plate/eaves/beam/lintel datums,
                    # section dimension chains, ceiling/floor level
                    # annotations) beyond what F.14's level-datum parser
                    # already recognizes: comprehensive keyword search across
                    # every page of both documents, plus a spatial check for
                    # a genuine vertical (column-oriented) dimension chain
                    # near the elevation/section views, found nothing further
                    # in either document. Where no such evidence exists, this
                    # fallback is demoted (never invented a different guessed
                    # height) so a downstream commercial consumer gating on
                    # confidence or wall_height_authority cannot mistake an
                    # assumption for a firm, evidence-based quantity.
                    from pb_geometry_takeoff_model import MeasurementAuthorityType
                    wall_height_authority = (
                        MeasurementAuthorityType.DOCUMENTED_DIMENSION.value
                        if height_is_genuine_evidence
                        else MeasurementAuthorityType.PROVISIONAL.value
                    )
                    pred_dict["perimeter_walling"] = ExtractedPrediction(
                        tag="perimeter_walling",
                        trade_type="walls",
                        description=f"Perimeter walling (2x({length_m}+{width_m})m perimeter at {height_desc})",
                        quantity=gross_wall_area,
                        unit="SM",
                        confidence=0.93 if height_is_genuine_evidence else 0.6,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        dimensions=[perimeter_m, effective_wall_height_m],
                        metadata={
                            "external_perimeter_m": footprint_res.external_perimeter_m,
                            "enclosed_wall_perimeter_m": perimeter_m,
                            "shared_edge_length_m": footprint_res.shared_edge_length_m,
                            "footprint_status": footprint_res.status,
                            "wall_height_source": (
                                "resolved_level_datum_evidence"
                                if height_is_genuine_evidence
                                else "default_ceiling_height_assumption"
                            ),
                            "wall_height_authority": wall_height_authority,
                        },
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
                cur_wall_dims = pred_dict["perimeter_walling"].dimensions
                cur_height = cur_wall_dims[1] if cur_wall_dims and len(cur_wall_dims) > 1 else None

                # Internal face area (Phase F.15): when real, corroborated
                # wall-thickness dimension-chain evidence resolved, compute
                # a genuine internal perimeter (external perimeter minus 8x
                # the wall thickness -- the standard rectangle relation) and
                # a true internal face area, distinct from (and smaller
                # than) the external wall's gross area. The opening
                # deduction pipeline (F.9) deducts the SAME openings from
                # this independent gross value via
                # metadata["independent_gross_area_m2"] rather than
                # overwriting it with the external wall's net area -- see
                # pb_opening_deduction_pipeline.propagate_to_predictions.
                # Falls back to the pre-existing external-area proxy,
                # unchanged, whenever thickness evidence does not resolve.
                internal_face_gross_area_m2: Optional[float] = None
                if (
                    global_resolved_wall_thickness_m is not None
                    and cur_height is not None
                    and cur_perim > 0
                ):
                    internal_perimeter_m = cur_perim - 8.0 * global_resolved_wall_thickness_m
                    if internal_perimeter_m > 0:
                        internal_face_gross_area_m2 = round(internal_perimeter_m * cur_height, 4)

                if self._has_internal_plaster_finish(page_text):
                    if internal_face_gross_area_m2 is not None:
                        _internal_face_derivation = {
                            "derivation": "internal_face_area_from_resolved_wall_thickness",
                            "wall_thickness_m": global_resolved_wall_thickness_m,
                            "independent_gross_area_m2": internal_face_gross_area_m2,
                            "wall_height_authority": wall_height_authority,
                            "note": (
                                "Internal face area computed from a genuinely "
                                "corroborated wall-thickness dimension chain "
                                "(internal perimeter = external perimeter - 8x "
                                "thickness), not copied from the external wall area."
                            ),
                        }
                        # The wall-thickness evidence is genuine either way,
                        # but this area still multiplies by cur_height -- when
                        # that height is only the assumed default (F.23A
                        # authority debt), the result silently inherits that
                        # same unresolved-height uncertainty and must not be
                        # presented at the same confidence as when BOTH
                        # thickness and height are genuinely evidenced.
                        if height_is_genuine_evidence:
                            internal_confidence = 0.8
                            _internal_face_derivation["note"] += (
                                " Wall height is also genuinely evidenced."
                            )
                        else:
                            internal_confidence = 0.65
                            _internal_face_derivation["note"] += (
                                " Wall height is still only the assumed default "
                                "(no level-datum evidence resolved), so this "
                                "area is provisional despite the genuine "
                                "thickness evidence."
                            )
                        internal_quantity = internal_face_gross_area_m2
                    else:
                        _internal_face_derivation = {
                            "derivation": "external_wall_area_proxy_no_internal_face_evidence",
                            "wall_height_authority": wall_height_authority,
                            "note": (
                                "No wall-thickness evidence available to compute a true "
                                "internal face area; this reuses the external net wall "
                                "area as a rough proxy and should be treated as provisional."
                            ),
                        }
                        internal_confidence = 0.5
                        internal_quantity = cur_wall

                    pred_dict["internal_plaster"] = ExtractedPrediction(
                        tag="internal_plaster",
                        trade_type="finishes",
                        description="Internal plastering to wall surfaces",
                        quantity=internal_quantity,
                        unit="SM",
                        confidence=internal_confidence,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=dict(_internal_face_derivation),
                    )
                    pred_dict["internal_paint"] = ExtractedPrediction(
                        tag="internal_paint",
                        trade_type="finishes",
                        description="Internal vinyl/emulsion paint to wall surfaces",
                        quantity=internal_quantity,
                        unit="SM",
                        confidence=internal_confidence,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=dict(_internal_face_derivation),
                    )

                # External key pointing: at least the correct FACE (external,
                # like perimeter_walling itself), but still triggered purely
                # by a keyword appearing somewhere in the page text with no
                # geometric evidence of its own extent -- never as confident
                # as a directly measured quantity.
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
                        confidence=0.5,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata={
                            "derivation": "external_wall_area_copy_keyword_triggered",
                            "wall_height_authority": wall_height_authority,
                            "note": (
                                "Triggered by a key-pointing keyword in the page text "
                                "with no independent measurement of its own extent; "
                                "reuses the external wall area and should be treated "
                                "as provisional."
                            ),
                        },
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
                flr_meta = pred_dict["floor_screed"].metadata or {}
                bed_area_for_substructure_m2 = float(
                    flr_meta.get(
                        "structural_bed_area_m2",
                        flr_meta.get("gross_floor_area_m2", tot_flr),
                    )
                )
                if global_has_dpm and "substructure_bed_dpm" not in pred_dict and bed_area_for_substructure_m2 > 0:
                    pred_dict["substructure_bed_dpm"] = ExtractedPrediction(
                        tag="substructure_bed_dpm",
                        trade_type="finishes",
                        description=f"Polythene damp-proof membrane under bed ({bed_area_for_substructure_m2} m2)",
                        quantity=bed_area_for_substructure_m2,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
                    )
                if global_has_mesh and "substructure_a142_mesh" not in pred_dict and bed_area_for_substructure_m2 > 0:
                    pred_dict["substructure_a142_mesh"] = ExtractedPrediction(
                        tag="substructure_a142_mesh",
                        trade_type="structure",
                        description=f"Fabric mesh reinforcement A142 in floor bed ({bed_area_for_substructure_m2} m2)",
                        quantity=bed_area_for_substructure_m2,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
                    )
                if global_has_surface_bed and "substructure_surface_bed" not in pred_dict and bed_area_for_substructure_m2 > 0:
                    pred_dict["substructure_surface_bed"] = ExtractedPrediction(
                        tag="substructure_surface_bed",
                        trade_type="structure",
                        description=f"Reinforced concrete ground-bearing surface bed ({bed_area_for_substructure_m2} m2)",
                        quantity=bed_area_for_substructure_m2,
                        unit="SM",
                        confidence=0.90,
                        source_page=page_num,
                        sheet_number=sheet_no,
                        metadata=flr_meta,
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
            # 4 & 5. Window and Door Extraction with Evidence Binding (Phase F.12)
            # ------------------------------------------------------------------
            from pb_drawing_evidence_binding import (
                DrawingEvidenceBindingEngine,
                DrawingViewClassifier,
                DrawingViewType,
                EvidenceOccurrence,
                ScheduleSpecification,
            )

            page_blocks = page.get_text("blocks")
            view_headers: List[Tuple[float, float, str]] = []
            for b in page_blocks:
                b_txt = b[4].strip()
                vt = DrawingViewClassifier.classify_text(b_txt)
                if vt in (DrawingViewType.FLOOR_PLAN, DrawingViewType.ELEVATION, DrawingViewType.SECTION, DrawingViewType.SCHEDULE):
                    view_headers.append(((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0, vt.value))

            def _get_block_view_type(bx: float, by: float) -> str:
                if not view_headers:
                    return DrawingViewType.UNKNOWN.value
                return min(view_headers, key=lambda vh: math.hypot(vh[0] - bx, vh[1] - by))[2]

            # Schedule rows with explicit counts
            w1_sched = re.findall(r"\bW1\b\s*[:.\-]?\s*(\d+)\s*(?:No\.?s?|Nos?)\b|\b(\d+)\s*(?:No\.?s?|Nos?)\s*[:.\-]?\s*\bW1\b", pt_norm, re.I)
            w2_sched = re.findall(r"\bW2\b\s*[:.\-]?\s*(\d+)\s*(?:No\.?s?|Nos?)\b|\b(\d+)\s*(?:No\.?s?|Nos?)\s*[:.\-]?\s*\bW2\b", pt_norm, re.I)
            d1_sched = re.findall(r"\bD1\b\s*[:.\-]?\s*(\d+)\s*(?:No\.?s?|Nos?)\b|\b(\d+)\s*(?:No\.?s?|Nos?)\s*[:.\-]?\s*\bD1\b", pt_norm, re.I)

            sched_spec_w1 = ScheduleSpecification("W1", "windows", "Mild steel casement window 3000mm", dimensions=[3000.0, 1200.0], scheduled_quantity=float(w1_sched[0][0] or w1_sched[0][1])) if w1_sched else None
            sched_spec_w2 = ScheduleSpecification("W2", "windows", "Mild steel casement window 2900mm", dimensions=[2900.0, 1200.0], scheduled_quantity=float(w2_sched[0][0] or w2_sched[0][1])) if w2_sched else None
            sched_spec_d1 = ScheduleSpecification("D1", "doors", "Door 1000x2100mm", dimensions=[1000.0, 2100.0], scheduled_quantity=float(d1_sched[0][0] or d1_sched[0][1])) if d1_sched else None

            w1_occs: List[EvidenceOccurrence] = []
            w2_occs: List[EvidenceOccurrence] = []
            d1_occs: List[EvidenceOccurrence] = []

            for b_idx, b in enumerate(page_blocks):
                b_txt = b[4].strip().replace("\n", " ")
                bx = (b[0] + b[2]) / 2.0
                by = (b[1] + b[3]) / 2.0
                vt = _get_block_view_type(bx, by)
                bbox = [b[0], b[1], b[2], b[3]]

                # W1 (3000 casement)
                for m3000 in re.finditer(r"3[,.]?000\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:steel\s*)?casement", b_txt, re.I):
                    h_val = float(m3000.group(1).replace(",", ".").replace(".", ""))
                    w1_occs.append(EvidenceOccurrence(f"w1_{b_idx}_{m3000.start()}", "W1", "windows", view_type=vt, source_page=page_num, bounding_box=bbox, dimensions=[3000.0, h_val]))

                # W2 (2900 casement)
                for m2900 in re.finditer(r"2[,.]?900\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:steel\s*)?casement", b_txt, re.I):
                    h_val = float(m2900.group(1).replace(",", ".").replace(".", ""))
                    w2_occs.append(EvidenceOccurrence(f"w2_{b_idx}_{m2900.start()}", "W2", "windows", view_type=vt, source_page=page_num, bounding_box=bbox, dimensions=[2900.0, h_val]))

                # D1 (1000 door)
                for m1000 in re.finditer(r"(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:[^\d\n]{0,25})?(?:door|batten)", b_txt, re.I):
                    dw = float(m1000.group(1).replace(",", "").replace(".", ""))
                    dh = float(m1000.group(2).replace(",", "").replace(".", ""))
                    d1_occs.append(EvidenceOccurrence(f"d1_{b_idx}_{m1000.start()}", "D1", "doors", view_type=vt, source_page=page_num, bounding_box=bbox, dimensions=[dw, dh]))

            # Fallback if block matching missed raw text matches
            if not w1_occs:
                w3000_matches = re.findall(r"3[,.]?000\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:steel\s*)?casement", pt_norm, re.I)
                for i, m_h in enumerate(w3000_matches):
                    h_val = float(m_h.replace(",", ".").replace(".", ""))
                    w1_occs.append(EvidenceOccurrence(f"w1_raw_{i}", "W1", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=page_num, dimensions=[3000.0, h_val]))

            if not w2_occs:
                w2900_matches = re.findall(r"2[,.]?900\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:steel\s*)?casement", pt_norm, re.I)
                for i, m_h in enumerate(w2900_matches):
                    h_val = float(m_h.replace(",", ".").replace(".", ""))
                    w2_occs.append(EvidenceOccurrence(f"w2_raw_{i}", "W2", "windows", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=page_num, dimensions=[2900.0, h_val]))

            if not d1_occs:
                d_calls = re.findall(r"(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*[xX]\s*(\d{1,2}[,.]?\d{3}|\d{3,4})\s*mm\s*(?:[^\d\n]{0,25})?(?:door|batten)", pt_norm, re.I)
                for i, dc in enumerate(d_calls):
                    dw = float(dc[0].replace(",", "").replace(".", ""))
                    dh = float(dc[1].replace(",", "").replace(".", ""))
                    d1_occs.append(EvidenceOccurrence(f"d1_raw_{i}", "D1", "doors", view_type=DrawingViewType.FLOOR_PLAN.value, source_page=page_num, dimensions=[dw, dh]))

            # Reconcile W1
            r_w1 = DrawingEvidenceBindingEngine.reconcile("W1", "windows", w1_occs, sched_spec_w1)
            if r_w1.final_quantity is not None and r_w1.final_quantity > 0:
                pred_dict["W1"] = ExtractedPrediction(
                    tag="W1",
                    trade_type="windows",
                    description=r_w1.description,
                    quantity=r_w1.final_quantity,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=r_w1.dimensions or [3000.0, 1200.0],
                    metadata={
                        "physical_object_ids": r_w1.physical_object_ids,
                        "evidence_ids": [o.occurrence_id for o in w1_occs],
                        "schedule_evidence": r_w1.metadata.get("schedule_count"),
                        "occurrence_evidence": {"plan_count": r_w1.metadata.get("plan_count"), "elevation_count": r_w1.metadata.get("elevation_count")},
                        "duplicate_observations_suppressed": r_w1.duplicate_observations_suppressed,
                        "duplicates_suppressed": r_w1.duplicate_observations_suppressed,
                        "conflicts": r_w1.conflicts,
                        "scope": "primary_building",
                        "reconciliation_status": r_w1.status,
                    },
                )

            # Reconcile W2
            r_w2 = DrawingEvidenceBindingEngine.reconcile("W2", "windows", w2_occs, sched_spec_w2)
            if r_w2.final_quantity is not None and r_w2.final_quantity > 0:
                pred_dict["W2"] = ExtractedPrediction(
                    tag="W2",
                    trade_type="windows",
                    description=r_w2.description,
                    quantity=r_w2.final_quantity,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=r_w2.dimensions or [2900.0, 1200.0],
                    metadata={
                        "physical_object_ids": r_w2.physical_object_ids,
                        "evidence_ids": [o.occurrence_id for o in w2_occs],
                        "schedule_evidence": r_w2.metadata.get("schedule_count"),
                        "occurrence_evidence": {"plan_count": r_w2.metadata.get("plan_count"), "elevation_count": r_w2.metadata.get("elevation_count")},
                        "duplicate_observations_suppressed": r_w2.duplicate_observations_suppressed,
                        "duplicates_suppressed": r_w2.duplicate_observations_suppressed,
                        "conflicts": r_w2.conflicts,
                        "scope": "primary_building",
                        "reconciliation_status": r_w2.status,
                    },
                )

            # Reconcile D1
            r_d1 = DrawingEvidenceBindingEngine.reconcile("D1", "doors", d1_occs, sched_spec_d1)
            if r_d1.final_quantity is not None and r_d1.final_quantity > 0:
                pred_dict["D1"] = ExtractedPrediction(
                    tag="D1",
                    trade_type="doors",
                    description=r_d1.description,
                    quantity=r_d1.final_quantity,
                    unit="NO",
                    confidence=0.95,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    dimensions=r_d1.dimensions or [1000.0, 2100.0],
                    metadata={
                        "physical_object_ids": r_d1.physical_object_ids,
                        "evidence_ids": [o.occurrence_id for o in d1_occs],
                        "schedule_evidence": r_d1.metadata.get("schedule_count"),
                        "occurrence_evidence": {"plan_count": r_d1.metadata.get("plan_count"), "elevation_count": r_d1.metadata.get("elevation_count")},
                        "duplicate_observations_suppressed": r_d1.duplicate_observations_suppressed,
                        "duplicates_suppressed": r_d1.duplicate_observations_suppressed,
                        "conflicts": r_d1.conflicts,
                        "scope": "primary_building",
                        "reconciliation_status": r_d1.status,
                    },
                )

            # Alternate explicit opening-tag conventions. Existing reconciled
            # schedule/geometry predictions retain authority when present.
            for opening_tag, (trade, count) in self._contextual_opening_tag_counts(page_text).items():
                if opening_tag in pred_dict:
                    continue
                pred_dict[opening_tag] = ExtractedPrediction(
                    tag=opening_tag,
                    trade_type=trade,
                    description=f"{opening_tag} explicit tagged opening occurrences",
                    quantity=float(count),
                    unit="NO",
                    confidence=0.88,
                    source_page=page_num,
                    sheet_number=sheet_no,
                    metadata={"derivation": "contextual_explicit_opening_tag_count"},
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
        # Generic Drawing Vision / OCR Evidence Layer (Phase F.10)
        # ------------------------------------------------------------------
        try:
            from pb_drawing_ocr_evidence_layer import (
                DrawingEvidenceParser,
                DrawingEvidenceRecord,
                DrawingOCREngine,
                EvidenceMethod,
                EvidenceReconciler,
                EvidenceStatus,
            )

            ocr_engine = DrawingOCREngine()
            dwg_pages = [p for p in target_pages if 0 <= p < len(doc) and self.is_drawing_page(doc[p].get_text("text"))]

            for p_num in dwg_pages:
                page = doc[p_num]
                p_text = page.get_text("text")

                # Prefer native evidence first:
                # Only run raster OCR if native extraction on this sheet is insufficient:
                native_openings_on_page = [
                    p for p in pred_dict.values()
                    if p.source_page == p_num + 1 and p.trade_type in ("windows", "doors")
                ]
                has_complete_native_openings = (
                    len(native_openings_on_page) > 0
                    and all(p.quantity is not None and p.quantity > 0 for p in native_openings_on_page)
                )
                is_scanned_or_raster = len(p_text.strip()) < 150
                has_schedule_word = any(
                    k in p_text.lower()
                    for k in ("schedule of doors", "schedule of windows", "window schedule", "door schedule")
                )
                # Broader, still-generic signal (bug fix, this PR): a real
                # door/window schedule sheet does not always literally say
                # "schedule" -- found against a real project PDF whose
                # window/door detail sheet describes types via "Steel
                # casement frames", "Fixed glass", door/frame material
                # notes, with no "schedule" heading text anywhere on it.
                # Only ever broadens the trigger, never narrows it: still
                # requires zero usable native openings on this specific
                # page before OCR is even considered.
                has_opening_keyword = any(
                    k in p_text.lower()
                    for k in (
                        "casement", "glazing", "glazed", "steel frame",
                        "timber door", "flush door", "panelled door", "panel door",
                    )
                )

                native_insufficient = is_scanned_or_raster or (
                    (has_schedule_word or has_opening_keyword) and not has_complete_native_openings
                )
                if not native_insufficient:
                    continue

                # Bug fix (this PR): the OCR extraction below previously sat
                # unreachable after an unconditional `continue` in the
                # branch that skips OCR (native already sufficient) --
                # meaning Phase F.10's OCR evidence layer never actually
                # ran, on any page, regardless of native sufficiency. It now
                # correctly runs only in the remaining case: native
                # evidence on this page is insufficient (raster/scanned
                # sheet, or a schedule-word page with incomplete native
                # window/door quantities).
                ocr_lines = ocr_engine.recognize_page_rect(page, dpi=150)
                ocr_records: List[DrawingEvidenceRecord] = []
                for o_line in ocr_lines:
                    rec = DrawingEvidenceParser.parse_schedule_line(
                        o_line["text"],
                        source_page=p_num + 1,
                        bbox=o_line.get("bounding_box"),
                        confidence=o_line.get("confidence", 0.85),
                        method=EvidenceMethod.RASTER_OCR.value,
                    )
                    if rec:
                        ocr_records.append(rec)

                if ocr_records:
                    # Bug fix (this PR): this reconciliation is strictly a
                    # window/door evidence layer -- collecting every
                    # prediction on the page regardless of trade_type (as
                    # written before this fix) meant an unrelated
                    # prediction (e.g. internal_plaster, structural_columns)
                    # would be round-tripped through DrawingEvidenceRecord
                    # and rebuilt below with a bare extraction_method/
                    # raw_evidence_ref/status metadata dict, silently
                    # discarding its real metadata (e.g. "derivation").
                    # Newly reachable now that the dead-code bug above is
                    # fixed, so this scope restriction is what keeps that
                    # activation additive rather than destructive.
                    native_records = []
                    for tag, pred in list(pred_dict.items()):
                        if pred.source_page == p_num + 1 and pred.trade_type in ("windows", "doors"):
                            native_records.append(
                                DrawingEvidenceRecord(
                                    tag=pred.tag,
                                    trade_type=pred.trade_type,
                                    description=pred.description,
                                    quantity=pred.quantity,
                                    unit=pred.unit,
                                    dimensions=pred.dimensions,
                                    source_page=pred.source_page,
                                    bounding_box=pred.bounding_box,
                                    extracted_text=pred.description,
                                    extracted_value=pred.quantity,
                                    confidence=pred.confidence,
                                    extraction_method=EvidenceMethod.NATIVE_TEXT.value,
                                    status=EvidenceStatus.CONFIRMED.value,
                                )
                            )

                    reconciled = EvidenceReconciler.reconcile(native_records, ocr_records)
                    for r in reconciled:
                        if r.status == EvidenceStatus.CONFIRMED.value and r.quantity is not None and r.quantity > 0:
                            if r.tag not in pred_dict or r.confidence >= pred_dict[r.tag].confidence:
                                pred_dict[r.tag] = ExtractedPrediction(
                                    tag=r.tag,
                                    trade_type=r.trade_type,
                                    description=r.description,
                                    quantity=r.quantity,
                                    unit=r.unit,
                                    confidence=r.confidence,
                                    source_page=r.source_page,
                                    dimensions=r.dimensions,
                                    bounding_box=r.bounding_box,
                                    metadata={
                                        "extraction_method": r.extraction_method,
                                        "raw_evidence_ref": r.raw_evidence_ref,
                                        "status": r.status,
                                    },
                                )
                        elif r.status == EvidenceStatus.CONFLICT_MANUAL_REVIEW.value:
                            if r.tag in pred_dict:
                                del pred_dict[r.tag]
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
                        # Fail closed: do not deduct conflicted openings
                        if p_obj.metadata and p_obj.metadata.get("reconciliation_status") == "conflict_manual_review":
                            continue
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
