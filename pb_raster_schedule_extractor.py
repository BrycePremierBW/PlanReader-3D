"""pb_raster_schedule_extractor.py — Generic Raster, CAD, and Vector Schedule Extractor.

Recovers schedule data visually or textually present in architectural/structural drawings:
- Window schedules (W1, W2, etc., sizes, counts, totals)
- Door schedules (D1, D2, etc., sizes, counts, totals)
- Vent counts (PV / permanent vents on elevations/sections)
- Pillar / pier / callout counts (CHS pillars, masonry piers, roof trusses)

Strict Rules:
- Generic OCR/vision/table extraction only.
- NO benchmark-specific dimensions, counts, or hardcodes.
- NO project-name conditions or benchmark IDs.
- Outputs must include source page and bounding evidence.
- Duplicate schedule rows across sheets/views must be deduplicated.
- Uncertain rows must remain provisional / missed rather than guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import fitz

from pb_opening_tag_normalization import normalize_opening_tag


@dataclass
class ScheduleCell:
    """A cell within a schedule table or callout box."""
    text: str
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF points
    source_page: int
    confidence: float = 1.0


@dataclass
class ScheduleRow:
    """An extracted schedule item row with drawing evidence."""
    tag: str
    trade_type: str  # 'windows', 'doors', 'walls', 'structure', 'finishes'
    description: str
    quantity: Optional[float]
    unit: str  # 'NO', 'SM', 'M'
    dimensions: Optional[List[float]] = None  # [width_mm, height_mm]
    source_page: int = 1
    bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    sheet_number: Optional[str] = None
    confidence: float = 0.90
    is_provisional: bool = False
    evidence_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "trade_type": self.trade_type,
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit,
            "dimensions": self.dimensions,
            "source_page": self.source_page,
            "bbox": list(self.bbox),
            "sheet_number": self.sheet_number,
            "confidence": self.confidence,
            "is_provisional": self.is_provisional,
            "evidence_text": self.evidence_text,
        }


_CHAIN_VALUE_TOL_MM = 25.0
_OPENING_WIDTH_MM = (700.0, 3600.0)
_PIER_WIDTH_MM = (150.0, 1000.0)
_DOOR_LEAF_WIDTH_MM = (800.0, 1250.0)
_MIN_UNIFORM_OPENINGS = 3
_FLOOR_PLAN_TEXT_RE = re.compile(
    r"\b(?:ground\s*floor\s*plan|floor\s*plan|floor\s*layout|layout\s*plan)\b",
    re.I,
)


def _chain_values_close(left: float, right: float, tol: float = _CHAIN_VALUE_TOL_MM) -> bool:
    return abs(float(left) - float(right)) <= tol


def _bucket_mm(value: float) -> int:
    return int(round(float(value) / _CHAIN_VALUE_TOL_MM) * _CHAIN_VALUE_TOL_MM)


def uniform_opening_pier_count(
    values_mm: Sequence[float],
) -> Optional[Tuple[int, float, float]]:
    """Return (opening_count, opening_mm, pier_mm) for a uniform wall chain.

    A qualifying chain is optional unique end returns plus strictly
    alternating opening / pier segments that end on an opening, so
    ``n_openings == n_piers + 1``. Equal-count W×H callout pairs
    (2900, 900, 2900, 900, ...) are rejected.
    """
    values = [float(v) for v in values_mm if v is not None]
    if len(values) < 5:
        return None

    work = list(values)
    buckets = _bucket_groups(work)
    if len(buckets) == 3:
        rare_label = min(buckets.items(), key=lambda item: (len(item[1]), sum(item[1]) / len(item[1])))[0]
        if _bucket_mm(work[0]) == rare_label and _bucket_mm(work[-1]) == rare_label:
            work = work[1:-1]
            buckets = _bucket_groups(work)
    if len(buckets) != 2:
        return None
    return _uniform_opening_pier_from_interior(work)


def _bucket_groups(values: Sequence[float]) -> Dict[int, List[float]]:
    grouped: Dict[int, List[float]] = {}
    for value in values:
        grouped.setdefault(_bucket_mm(value), []).append(float(value))
    return grouped


def _uniform_opening_pier_from_interior(
    interior: Sequence[float],
) -> Optional[Tuple[int, float, float]]:
    buckets = _bucket_groups(interior)
    if len(buckets) != 2:
        return None
    (label_a, group_a), (label_b, group_b) = sorted(
        buckets.items(), key=lambda item: sum(item[1]) / len(item[1])
    )
    pier_mm = sum(group_a) / len(group_a)
    opening_mm = sum(group_b) / len(group_b)
    if not (_PIER_WIDTH_MM[0] <= pier_mm <= _PIER_WIDTH_MM[1]):
        return None
    if not (_OPENING_WIDTH_MM[0] <= opening_mm <= _OPENING_WIDTH_MM[1]):
        return None
    if opening_mm < pier_mm + 200.0:
        return None

    n_open = 0
    n_pier = 0
    expected_opening = True
    for value in interior:
        if expected_opening:
            if not _chain_values_close(value, opening_mm):
                return None
            n_open += 1
            expected_opening = False
        else:
            if not _chain_values_close(value, pier_mm):
                return None
            n_pier += 1
            expected_opening = True
    if n_open < _MIN_UNIFORM_OPENINGS or n_open != n_pier + 1:
        return None
    return n_open, opening_mm, pier_mm


def repeated_bay_door_count(values_mm: Sequence[float]) -> Optional[int]:
    """Count doors that close each copy of a repeated floor-plan bay.

    Classroom / lab blocks are often dimensioned as the same bay repeated
    N times, with one door-leaf width at the same index in every copy.
    """
    values = [float(v) for v in values_mm if v is not None]
    n = len(values)
    if n < 8:
        return None
    for period in range(4, n // 2 + 1):
        if n % period != 0 or n // period < 2:
            continue
        bay = values[:period]
        tiled = True
        for offset in range(period, n, period):
            for idx in range(period):
                if not _chain_values_close(values[offset + idx], bay[idx]):
                    tiled = False
                    break
            if not tiled:
                break
        if not tiled:
            continue
        door_idxs = []
        start = 1 if bay[0] < 1000.0 else 0
        for idx in range(start, period):
            width = bay[idx]
            if _DOOR_LEAF_WIDTH_MM[0] <= width <= _DOOR_LEAF_WIDTH_MM[1]:
                door_idxs.append(idx)
        if len(door_idxs) != 1:
            continue
        return n // period
    return None


class GenericScheduleTableExtractor:
    """Generic schedule table and callout extractor.
    
    Operates purely on drawing evidence:
    1. Detects tabular structures from table borders, vector lines, and column-aligned text.
    2. Maps table cells into structured rows (tag, dimensions, quantity, description).
    3. Detects visual and text callouts on plan/elevation views with spatial bounding evidence.
    4. Deduplicates repeated entries across sheets/views.
    5. Leaves uncertain rows provisional (yielding missed items instead of guesses).
    """

    def __init__(self) -> None:
        pass

    def extract_from_document(
        self,
        doc: fitz.Document,
        pages: Optional[Sequence[int]] = None,
    ) -> List[ScheduleRow]:
        """Extract all evidenced schedule rows and callouts across document pages."""
        all_rows: List[ScheduleRow] = []
        target_pnos = list(pages) if pages is not None else list(range(len(doc)))

        for pno in target_pnos:
            if pno < 0 or pno >= len(doc):
                continue
            page = doc[pno]
            page_num = pno + 1
            rows_on_page = self.extract_from_page(page, page_num)
            all_rows.extend(rows_on_page)

        return self.deduplicate_schedule_rows(all_rows)

    def extract_from_page(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Extract schedule rows and callouts from a single drawing page."""
        page_rows: List[ScheduleRow] = []

        # 1. Native / Vector table extraction
        table_rows = self._extract_tables_from_page(page, page_num)
        page_rows.extend(table_rows)

        # 2. Row-aligned schedule detection. This path is independent of
        # PyMuPDF's structured-table detector and is therefore stable for
        # vector/CAD schedules whose cells are visually aligned but not
        # recognized by ``find_tables()``.
        row_rows = self._extract_row_aligned_opening_schedules(page, page_num)
        page_rows.extend(row_rows)

        # 3. Column-aligned schedule detection (CAD multi-column schedules)
        col_rows = self._extract_column_aligned_schedules(page, page_num)
        page_rows.extend(col_rows)

        # 4. Explicit callouts (windows, doors, vents, pillars, trusses)
        callout_rows = self._extract_callouts_from_page(page, page_num)
        page_rows.extend(callout_rows)

        # 5. Card-style schedules: a standalone documented tag label sitting
        # above its own labelled "Overall Quantity" field, rather than a
        # table row or a bare tag counted on a plan.
        card_rows = self._extract_card_style_schedules(page, page_num)
        page_rows.extend(card_rows)

        # F.28: a combined WD identity remains ambiguous globally.
        # Resolve it only when same-card spatial evidence independently
        # proves window semantics and the explicit card total.
        from pb_contextual_wd_card_evidence import (
            extract_contextual_wd_card_evidence,
        )
        for wd_evidence in extract_contextual_wd_card_evidence(
            page, source_page=page_num
        ):
            page_rows.append(
                ScheduleRow(
                    tag=wd_evidence.tag,
                    trade_type="windows",
                    description=(
                        f"{wd_evidence.raw_tag} card schedule, "
                        "explicit Overall Quantity"
                    ),
                    quantity=wd_evidence.quantity,
                    unit="NO",
                    source_page=page_num,
                    bbox=wd_evidence.bbox,
                    confidence=0.90,
                    evidence_text=wd_evidence.evidence_text,
                )
            )

        # Floor-plan opening/pier chains and repeated-bay door runs. Skipped
        # when this page already has an explicit documented W/D identity so
        # card/table schedules (and their tags) remain authoritative.
        if not any(normalize_opening_tag(row.tag) for row in page_rows):
            page_rows.extend(self._extract_plan_opening_dimension_chains(page, page_num))

        return page_rows

    def _plan_chain_regions(self, page: fitz.Page, page_num: int) -> List[Tuple[float, float, float, float]]:
        """Return floor-plan bboxes when F.07 resolved/derived a plan view."""
        try:
            from pb_drawing_evidence_binding import DrawingViewType
            from pb_viewport_segmentation import segment_page_viewports
        except Exception:
            return []
        regions: List[Tuple[float, float, float, float]] = []
        try:
            for viewport in segment_page_viewports(page, page_number=page_num):
                if viewport.view_type != DrawingViewType.FLOOR_PLAN.value:
                    continue
                box = getattr(viewport, "bounding_box", None)
                if box and len(box) >= 4:
                    regions.append((float(box[0]), float(box[1]), float(box[2]), float(box[3])))
        except Exception:
            return []
        return regions

    @staticmethod
    def _chain_midpoint(observations: Sequence[Any]) -> Optional[Tuple[float, float]]:
        xs: List[float] = []
        ys: List[float] = []
        for obs in observations:
            bbox = getattr(obs, "bbox", None)
            if not bbox or len(bbox) < 4:
                continue
            xs.append((float(bbox[0]) + float(bbox[2])) / 2.0)
            ys.append((float(bbox[1]) + float(bbox[3])) / 2.0)
        if not xs:
            return None
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    @staticmethod
    def _point_in_bbox(point: Tuple[float, float], bbox: Tuple[float, float, float, float]) -> bool:
        x, y = point
        return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]

    def _extract_plan_opening_dimension_chains(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Count unlabeled floor-plan openings from figured dimension chains.

        Uniform opening/pier walls with three or more equal openings become
        the single conventional window type W1. Repeated identical bays with
        one door-leaf width per bay become D1. Mixed widths never mint W2/D2.
        Dimension callout pairs (width × height in one note) are not chains.
        """
        page_text = page.get_text("text") or ""
        plan_regions = self._plan_chain_regions(page, page_num)
        if not plan_regions and not _FLOOR_PLAN_TEXT_RE.search(page_text):
            return []

        try:
            from pb_dimension_chain_evidence_extractor import extract_dimension_chains_from_page
        except Exception:
            return []

        try:
            chains = extract_dimension_chains_from_page(
                page,
                page_num=page_num,
                view_id=f"page_{page_num}",
            )
        except Exception:
            return []

        window_hits: List[Tuple[int, float, Tuple[float, float, float, float], str]] = []
        door_hits: List[Tuple[int, Tuple[float, float, float, float], str]] = []

        for chain in chains:
            observations = list(getattr(chain, "observations", []) or [])
            values = [float(obs.value_m) * 1000.0 for obs in observations]
            if len(values) < 5:
                continue
            midpoint = self._chain_midpoint(observations)
            if plan_regions:
                if midpoint is None or not any(
                    self._point_in_bbox(midpoint, region) for region in plan_regions
                ):
                    continue
            x0 = min((obs.bbox[0] for obs in observations if obs.bbox), default=0.0)
            y0 = min((obs.bbox[1] for obs in observations if obs.bbox), default=0.0)
            x1 = max((obs.bbox[2] for obs in observations if obs.bbox), default=0.0)
            y1 = max((obs.bbox[3] for obs in observations if obs.bbox), default=0.0)
            bbox = (x0, y0, x1, y1)
            evidence = ",".join(str(int(round(v))) for v in values)

            uniform = uniform_opening_pier_count(values)
            if uniform is not None:
                count, opening_mm, pier_mm = uniform
                window_hits.append((count, opening_mm, bbox, evidence))
            door_count = repeated_bay_door_count(values)
            if door_count is not None:
                door_hits.append((door_count, bbox, evidence))

        rows: List[ScheduleRow] = []
        if window_hits:
            widths = {_bucket_mm(hit[1]) for hit in window_hits}
            counts = {hit[0] for hit in window_hits}
            if len(widths) == 1 and len(counts) == 1:
                count, opening_mm, bbox, evidence = window_hits[0]
                rows.append(
                    ScheduleRow(
                        tag="W1",
                        trade_type="windows",
                        description=(
                            f"W1 plan opening/pier chain "
                            f"({int(count)} No, {int(round(opening_mm))} mm)"
                        ),
                        quantity=float(count),
                        unit="NO",
                        dimensions=[float(opening_mm)],
                        source_page=page_num,
                        bbox=bbox,
                        confidence=0.86,
                        evidence_text=f"uniform opening/pier chain mm={evidence}",
                    )
                )
        if door_hits:
            counts = {hit[0] for hit in door_hits}
            if len(counts) == 1:
                count, bbox, evidence = door_hits[0]
                rows.append(
                    ScheduleRow(
                        tag="D1",
                        trade_type="doors",
                        description=f"D1 repeated floor-plan bay doors ({int(count)} No)",
                        quantity=float(count),
                        unit="NO",
                        source_page=page_num,
                        bbox=bbox,
                        confidence=0.86,
                        evidence_text=f"repeated bay door chain mm={evidence}",
                    )
                )
        return rows

    def _extract_card_style_schedules(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Detect a vertical 'card' schedule shape.

        Some drafting standards lay out one bordered card per opening type
        (a detail drawing plus a small key/value table) rather than a
        shared table or a bare tag counted where it appears on a plan. The
        card states its own total directly in a labelled field such as
        "Overall Quantity: 172" -- stronger, less ambiguous evidence than
        counting tag occurrences, when it can be associated with a real
        documented tag.

        A tag is only accepted when it is the *entire* content of its own
        text block (typically 1-3 words, e.g. "D", "-", "01") -- never a
        substring found inside a longer sentence -- and the quantity is
        associated with the nearest such tag block positioned directly
        above it in the same horizontal band (real spatial evidence, not
        document order). A combined/ambiguous prefix (e.g. "WD", split
        across overlapping text runs in some CAD exports) does not match
        any single documented opening type via ``normalize_opening_tag``
        and is safely skipped rather than guessed at.
        """
        words = page.get_text("words")
        blocks: Dict[int, List[tuple]] = {}
        for w in words:
            blocks.setdefault(int(w[5]), []).append(w)

        tag_candidates: List[Tuple[Any, Tuple[float, float, float, float]]] = []
        quantity_candidates: List[Tuple[float, Tuple[float, float, float, float]]] = []

        for block_words in blocks.values():
            if not block_words:
                continue
            ordered = sorted(block_words, key=lambda w: (w[6], w[7]))
            text = " ".join(str(w[4]) for w in ordered).strip()
            bbox = (
                min(w[0] for w in block_words),
                min(w[1] for w in block_words),
                max(w[2] for w in block_words),
                max(w[3] for w in block_words),
            )

            if len(block_words) <= 3 and len(text) <= 12:
                norm = normalize_opening_tag(text)
                if norm is not None:
                    tag_candidates.append((norm, bbox))
                    continue

            lower = text.lower()
            if "overall" in lower and "quantity" in lower:
                m = re.search(r"(\d+(?:\.\d+)?)\s*$", text)
                if m:
                    quantity_candidates.append((float(m.group(1)), bbox))

        rows: List[ScheduleRow] = []
        for value, qbbox in quantity_candidates:
            if value <= 0:
                continue
            qx0, qy0, qx1, qy1 = qbbox
            best_norm = None
            best_dist: Optional[float] = None
            for norm, tbbox in tag_candidates:
                tx0, ty0, tx1, ty1 = tbbox
                if ty1 > qy0:
                    continue  # the tag must sit above the quantity field
                overlap = min(tx1, qx1) - max(tx0, qx0)
                if overlap <= 0:
                    continue  # must share the same horizontal card column
                dist = qy0 - ty1
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_norm = norm
            if best_norm is None:
                continue
            rows.append(
                ScheduleRow(
                    tag=best_norm.tag,
                    trade_type=best_norm.trade_type,
                    description=f"{best_norm.raw_text} card schedule, explicit Overall Quantity",
                    quantity=value,
                    unit="NO",
                    source_page=page_num,
                    bbox=(qx0, qy0, qx1, qy1),
                    confidence=0.90,
                    evidence_text=f"Overall Quantity: {value:g}",
                )
            )
        return rows

    def _extract_tables_from_page(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Extract schedule rows from structured table grids found by PyMuPDF or vector borders."""
        rows: List[ScheduleRow] = []
        try:
            tabs = page.find_tables()
            if not tabs or not tabs.tables:
                return rows

            for table in tabs.tables:
                table_data = table.extract()
                if not table_data or len(table_data) < 2:
                    continue

                header = [str(c).lower().strip() if c else "" for c in table_data[0]]
                
                # Determine relevant columns
                tag_col = -1
                dim_col = -1
                qty_col = -1
                desc_col = -1

                for col_idx, col_name in enumerate(header):
                    if any(k in col_name for k in ("mark", "tag", "type", "window no", "door no", "item")):
                        tag_col = col_idx
                    elif any(k in col_name for k in ("size", "dimension", "width", "height", "wxh", "measurement")):
                        dim_col = col_idx
                    elif any(k in col_name for k in ("qty", "quantity", "no.", "nos", "count", "number")):
                        qty_col = col_idx
                    elif any(k in col_name for k in ("description", "specification", "particulars", "glazing")):
                        desc_col = col_idx

                # If no clear tag or quantity column, skip generic non-schedule tables
                if qty_col == -1 and tag_col == -1:
                    continue

                for r_idx, row in enumerate(table_data[1:], start=1):
                    raw_tag = str(row[tag_col]).strip() if tag_col >= 0 and tag_col < len(row) and row[tag_col] else ""
                    raw_qty = str(row[qty_col]).strip() if qty_col >= 0 and qty_col < len(row) and row[qty_col] else ""
                    raw_dim = str(row[dim_col]).strip() if dim_col >= 0 and dim_col < len(row) and row[dim_col] else ""
                    raw_desc = str(row[desc_col]).strip() if desc_col >= 0 and desc_col < len(row) and row[desc_col] else ""

                    qty_val = self._parse_quantity_string(raw_qty)
                    dims = self._parse_dimensions_string(raw_dim)

                    # Normalize only an explicitly documented opening identity.
                    # Dimensions never imply W/D tags.
                    normalized_opening = normalize_opening_tag(raw_tag)
                    combined_text = f"{raw_tag} {raw_desc} {raw_dim}".lower()
                    trade = normalized_opening.trade_type if normalized_opening else "other"
                    if trade == "other" and any(k in combined_text for k in ("window", "casement", "glaz")):
                        trade = "windows"
                    elif trade == "other" and any(k in combined_text for k in ("door", "flush", "panelled")):
                        trade = "doors"
                    elif trade == "other" and any(k in combined_text for k in ("vent", "pv")):
                        trade = "walls"
                    elif trade == "other" and any(k in combined_text for k in ("pillar", "column", "pier", "truss")):
                        trade = "structure"

                    if trade == "other" or not raw_tag or raw_tag.startswith("ITEM_") or raw_tag.isdigit():
                        continue
                    tag_name = normalized_opening.tag if normalized_opening else raw_tag

                    if qty_val is not None and qty_val > 0:
                        rows.append(
                            ScheduleRow(
                                tag=tag_name,
                                trade_type=trade,
                                description=f"Schedule item {tag_name}: {raw_desc or raw_dim}".strip(),
                                quantity=qty_val,
                                unit="NO",
                                dimensions=dims,
                                source_page=page_num,
                                bbox=table.bbox,
                                confidence=0.92,
                                evidence_text=f"Table row: tag={raw_tag}, qty={raw_qty}, dim={raw_dim}",
                            )
                        )
                    elif raw_tag:
                        rows.append(
                            ScheduleRow(
                                tag=tag_name,
                                trade_type=trade,
                                description=f"Schedule item {tag_name} (unquantified in table)",
                                quantity=None,
                                unit="NO",
                                dimensions=dims,
                                source_page=page_num,
                                bbox=table.bbox,
                                confidence=0.50,
                                is_provisional=True,
                                evidence_text=f"Table row without valid count: tag={raw_tag}",
                            )
                        )
        except Exception:
            pass

        return rows

    def _extract_row_aligned_opening_schedules(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Recover explicit opening schedule rows from native word geometry.

        This is a deterministic fallback for vector/CAD schedule sheets where
        ``Page.find_tables()`` does not recognize the grid. A firm row requires
        all three pieces of source evidence on one visual row: an explicit W/D
        identity, figured dimensions, and an explicit count marker. Dimensions
        or counts alone never manufacture an opening identity.
        """
        rows: List[ScheduleRow] = []
        try:
            page_text = page.get_text("text") or ""
            normalized_page = re.sub(r"\s+", " ", page_text.lower())
            has_schedule_context = (
                bool(re.search(r"\bschedules?\b", normalized_page))
                and bool(re.search(r"\b(?:windows?|doors?)\b", normalized_page))
            )
            if not has_schedule_context:
                return rows

            words = page.get_text("words") or []
            if not words:
                return rows

            # Cluster by visual baseline rather than PDF block identity. CAD
            # exports commonly place each schedule cell in a separate block.
            visual_rows: List[Dict[str, Any]] = []
            for word in sorted(words, key=lambda w: (((w[1] + w[3]) / 2.0), w[0])):
                cy = (float(word[1]) + float(word[3])) / 2.0
                target = None
                for candidate in visual_rows:
                    if abs(cy - candidate["cy"]) <= 4.5:
                        target = candidate
                        break
                if target is None:
                    target = {"cy": cy, "words": []}
                    visual_rows.append(target)
                target["words"].append(word)
                n = len(target["words"])
                target["cy"] = ((target["cy"] * (n - 1)) + cy) / n

            for visual in visual_rows:
                row_words = sorted(visual["words"], key=lambda w: w[0])
                row_text = " ".join(str(w[4]) for w in row_words).strip()
                normalized_opening = normalize_opening_tag(row_text)
                if normalized_opening is None:
                    continue

                dims = self._parse_dimensions_string(row_text)
                qty_match = re.search(r"\b(\d{1,3})\s*(?:no\.?s?|nos?)\b", row_text, re.I)
                if dims is None or qty_match is None:
                    continue

                qty = float(qty_match.group(1))
                if qty <= 0:
                    continue

                x0 = min(float(w[0]) for w in row_words)
                y0 = min(float(w[1]) for w in row_words)
                x1 = max(float(w[2]) for w in row_words)
                y1 = max(float(w[3]) for w in row_words)
                rows.append(
                    ScheduleRow(
                        tag=normalized_opening.tag,
                        trade_type=normalized_opening.trade_type,
                        description=(
                            f"Row-aligned schedule item {normalized_opening.tag} "
                            f"({int(qty)} No)"
                        ),
                        quantity=qty,
                        unit="NO",
                        dimensions=dims,
                        source_page=page_num,
                        bbox=(x0, y0, x1, y1),
                        confidence=0.87,
                        evidence_text=f"Row-aligned native schedule evidence: {row_text}",
                    )
                )
        except Exception:
            return []

        return rows

    def _extract_column_aligned_schedules(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Extract multi-column CAD schedules (common in architectural schedule sheets)."""
        rows: List[ScheduleRow] = []
        try:
            words = page.get_text("words")
            if not words or len(words) < 20:
                return rows

            # Filter for words in schedule area (exclude title block at x > 600)
            sched_words = [w for w in words if w[0] < 600]
            if len(sched_words) < 15:
                return rows

            x_coords = sorted([w[0] for w in sched_words])
            
            clusters: List[List[float]] = []
            current_cluster: List[float] = []
            for x in x_coords:
                if not current_cluster or (x - current_cluster[-1]) < 80.0:
                    current_cluster.append(x)
                else:
                    clusters.append(current_cluster)
                    current_cluster = [x]
            if current_cluster:
                clusters.append(current_cluster)

            if len(clusters) < 2:
                return rows

            col_ranges: List[Tuple[float, float]] = []
            for c in clusters:
                if len(c) >= 5:
                    col_ranges.append((min(c) - 10.0, max(c) + 10.0))

            for col_idx, (x_min, x_max) in enumerate(col_ranges, start=1):
                col_w = [w for w in sched_words if x_min <= w[0] <= x_max]
                col_text = " ".join(w[4] for w in sorted(col_w, key=lambda w: (w[1], w[0])))
                
                normalized_opening = normalize_opening_tag(col_text)
                is_window = any(k in col_text.lower() for k in ("casement", "window", "glass", "fixed glass"))
                is_door = any(k in col_text.lower() for k in ("door", "flush door", "panelled door"))

                if normalized_opening is not None:
                    trade = normalized_opening.trade_type
                elif is_window != is_door:
                    trade = "windows" if is_window else "doors"
                else:
                    continue

                dims = self._parse_dimensions_string(col_text)
                qty_match = re.search(r"\b(\d+)\s*(?:no\.?s?|nos?)\b", col_text, re.I)
                qty = float(qty_match.group(1)) if qty_match else None

                c_x0 = min(w[0] for w in col_w)
                c_y0 = min(w[1] for w in col_w)
                c_x1 = max(w[2] for w in col_w)
                c_y1 = max(w[3] for w in col_w)

                tag_name = normalized_opening.tag if normalized_opening else f"{trade[0].upper()}_COL_{col_idx}"

                # Untagged visual columns remain provisional even when a count
                # is visible: type existence is not schedule identity.
                if qty is not None and normalized_opening is not None:
                    rows.append(
                        ScheduleRow(
                            tag=tag_name,
                            trade_type=trade,
                            description=f"Column schedule item {tag_name} ({int(qty)} No)",
                            quantity=qty,
                            unit="NO",
                            dimensions=dims,
                            source_page=page_num,
                            bbox=(c_x0, c_y0, c_x1, c_y1),
                            confidence=0.88,
                            evidence_text=f"Column {col_idx} parsed count={int(qty)}: {col_text[:60]}...",
                        )
                    )
                else:
                    rows.append(
                        ScheduleRow(
                            tag=tag_name,
                            trade_type=trade,
                            description=f"Column schedule item {tag_name} (unresolved identity/count)",
                            quantity=None,
                            unit="NO",
                            dimensions=dims,
                            source_page=page_num,
                            bbox=(c_x0, c_y0, c_x1, c_y1),
                            confidence=0.40,
                            is_provisional=True,
                            evidence_text=f"Column {col_idx} missing count evidence: {col_text[:60]}...",
                        )
                    )
        except Exception:
            pass

        return rows

    def _extract_callouts_from_page(self, page: fitz.Page, page_num: int) -> List[ScheduleRow]:
        """Extract explicit drawing callouts (vents, pillars, piers, trusses, windows, doors)."""
        rows: List[ScheduleRow] = []
        blocks = page.get_text("blocks")

        for b in blocks:
            x0, y0, x1, y1, b_text, _, _ = b
            clean_b = b_text.strip().replace("\n", " ")
            b_norm = re.sub(r"\s+", " ", clean_b)

            # F.16: directly stated ``N No item`` / ``item N Nos`` drawing
            # notes.  The pure parser requires an explicit count marker and
            # fails closed on ambiguous/conflicting clauses; it never infers
            # a quantity from dimensions or project/BOQ context.
            from pb_explicit_item_count_extractor import extract_explicit_item_counts
            for explicit in extract_explicit_item_counts(b_text):
                rows.append(
                    ScheduleRow(
                        tag=explicit.tag,
                        trade_type=explicit.trade_type,
                        description=(
                            f"Explicit drawing count: {explicit.item_text} "
                            f"({explicit.quantity} No)"
                        ),
                        quantity=float(explicit.quantity),
                        unit="NO",
                        source_page=page_num,
                        bbox=(x0, y0, x1, y1),
                        confidence=0.94,
                        evidence_text=explicit.evidence_text,
                    )
                )

            # 1. Trusses: TRUSS T1 (13 No.S)
            truss_m = re.search(
                r"(?:TRUSS|TRUSSES)\s*([A-Za-z0-9\-]+)?\s*\(?(\d+)\s*(?:No\.?s?|Nos?)\)?",
                b_norm,
                re.I,
            )
            if truss_m:
                t_code = (truss_m.group(1) or "T1").upper()
                t_qty = float(truss_m.group(2))
                rows.append(
                    ScheduleRow(
                        tag="roof_trusses",
                        trade_type="structure",
                        description=f"Timber roof trusses complete (Truss {t_code}, {int(t_qty)} No)",
                        quantity=t_qty,
                        unit="NO",
                        source_page=page_num,
                        bbox=(x0, y0, x1, y1),
                        confidence=0.96,
                        evidence_text=clean_b,
                    )
                )

            for line in b_text.split("\n"):
                line_clean = line.strip()
                if not line_clean:
                    continue

                # 2. Pillars: (\d+) No. ... pillars
                pillar_m = re.search(r"\b(\d+)\s*(?:No\.?s?|Nos?)\s+(?:[\w\./\-]+\s+){0,4}pillars?\b", line_clean, re.I)
                if pillar_m:
                    p_qty = float(pillar_m.group(1))
                    rows.append(
                        ScheduleRow(
                            tag="verandah_pillars",
                            trade_type="structure",
                            description=f"CHS / verandah pillars ({int(p_qty)} No parsed from drawing)",
                            quantity=p_qty,
                            unit="NO",
                            source_page=page_num,
                            bbox=(x0, y0, x1, y1),
                            confidence=0.92,
                            evidence_text=line_clean,
                        )
                    )

                # 3. Piers: (\d+) No. ... piers
                pier_m = re.search(r"\b(\d+)\s*(?:No\.?s?|Nos?)\s+(?:[\w\./\-]+\s+){0,4}piers?\b", line_clean, re.I)
                if pier_m:
                    pier_qty = float(pier_m.group(1))
                    rows.append(
                        ScheduleRow(
                            tag="masonry_piers",
                            trade_type="walls",
                            description=f"Masonry piers ({int(pier_qty)} No parsed from drawing)",
                            quantity=pier_qty,
                            unit="NO",
                            source_page=page_num,
                            bbox=(x0, y0, x1, y1),
                            confidence=0.92,
                            evidence_text=line_clean,
                        )
                    )

            # 4. Chalkboard: (\d+) x (\d+)mm chalkboard / black board
            chalk_m = re.search(r"(\d{3,4})\s*mm\s*[xX]\s*(\d{3,4})\s*mm.*?bla(?:ck|oc)\s*board", b_norm, re.I)
            if chalk_m:
                cw = float(chalk_m.group(1))
                ch = float(chalk_m.group(2))
                rows.append(
                    ScheduleRow(
                        tag="chalkboard",
                        trade_type="finishes",
                        description=f"Blockboard chalkboard {int(cw)} x {int(ch)} mm",
                        quantity=1.0,
                        unit="NO",
                        dimensions=[cw, ch],
                        source_page=page_num,
                        bbox=(x0, y0, x1, y1),
                        confidence=0.95,
                        evidence_text=clean_b,
                    )
                )

        # Contradictory explicit notes may live in separate PDF text blocks,
        # beyond the pure parser's single-call conflict boundary.  Drop every
        # F.16 candidate for that tag rather than letting document-level
        # deduplication silently keep whichever block happened to appear first.
        explicit_quantities: Dict[str, set[float]] = {}
        for row in rows:
            if row.description.startswith("Explicit drawing count:") and row.quantity is not None:
                explicit_quantities.setdefault(row.tag, set()).add(row.quantity)
        conflicting_explicit_tags = {
            tag for tag, quantities in explicit_quantities.items() if len(quantities) > 1
        }
        if conflicting_explicit_tags:
            rows = [
                row for row in rows
                if not (
                    row.description.startswith("Explicit drawing count:")
                    and row.tag in conflicting_explicit_tags
                )
            ]

        # 5. Permanent Vents (PV): Group and deduplicate by elevation/section sheet
        #
        # "PV"/"P.V" also appears once per sheet as a drafting-legend
        # definition ("P.V denotes permanent vents.") rather than as a real
        # vent-location callout. That definition line is itself a generic,
        # recurring drawing convention -- this same document also defines
        # "S.V.P denotes soil vent pipe" the same way -- so any "<abbrev>
        # denotes <meaning>" occurrence is excluded by its own grammar,
        # never by a benchmark-specific count or page.
        all_words = page.get_text("words")

        def _next_word_text(word: tuple) -> str:
            block_no, line_no, word_no = word[5], word[6], word[7]
            for other in all_words:
                if other[5] == block_no and other[6] == line_no and other[7] == word_no + 1:
                    return str(other[4])
            return ""

        pv_words = [
            w
            for w in all_words
            if re.match(r"^(?:PV|P\.V)$", w[4], re.I)
            and _next_word_text(w).strip().lower().rstrip(".,:;") != "denotes"
        ]
        page_text_lower = page.get_text().lower()
        is_facade_sheet = any(k in page_text_lower for k in ("elevation", "facade", "façade", "section", "schedule", "plan"))

        if len(pv_words) >= 2 and is_facade_sheet:
            pv_x0 = min(w[0] for w in pv_words)
            pv_y0 = min(w[1] for w in pv_words)
            pv_x1 = max(w[2] for w in pv_words)
            pv_y1 = max(w[3] for w in pv_words)
            pv_count = float(len(pv_words))
            rows.append(
                ScheduleRow(
                    tag="brick_vents",
                    trade_type="walls",
                    description=f"Permanent / brick vents ({int(pv_count)} No on page {page_num})",
                    quantity=pv_count,
                    unit="NO",
                    source_page=page_num,
                    bbox=(pv_x0, pv_y0, pv_x1, pv_y1),
                    confidence=0.88,
                    evidence_text=f"{int(pv_count)} PV callouts detected on facade",
                )
            )

        return rows

    def deduplicate_schedule_rows(self, rows: Sequence[ScheduleRow]) -> List[ScheduleRow]:
        """Deduplicate schedule rows across sheets and views.
        
        Rules:
        - If multiple rows share the same tag and dimensions, prefer explicit schedule tables over callouts.
        - Sum vent counts across distinct facade sheets, but do not double-count identical pages.
        - Trusses and pillars are uniquely deduplicated across sheets.
        """
        deduped: Dict[str, ScheduleRow] = {}
        vent_pages: Dict[int, float] = {}

        # Canonical aliases for one documented opening identity must agree.
        # Conflicting counts or dimensions fail closed instead of allowing
        # source order / confidence to pick a winner.
        opening_groups: Dict[str, List[ScheduleRow]] = {}
        for candidate in rows:
            if candidate.is_provisional:
                continue
            norm = normalize_opening_tag(candidate.tag)
            if norm is None:
                continue
            candidate.tag = norm.tag
            candidate.trade_type = norm.trade_type
            opening_groups.setdefault(norm.tag, []).append(candidate)

        conflicting_opening_tags = set()
        resolved_opening_rows: Dict[str, ScheduleRow] = {}
        for tag, group in opening_groups.items():
            quantities = {float(r.quantity) for r in group if r.quantity is not None}
            dimensions = {
                tuple(float(v) for v in r.dimensions[:2])
                for r in group
                if r.dimensions is not None and len(r.dimensions) >= 2
            }
            if len(quantities) > 1 or len(dimensions) > 1:
                conflicting_opening_tags.add(tag)
                continue

            # Multiple generic detectors may observe the same explicit W/D row.
            # Prefer the most complete agreeing evidence over raw confidence:
            # a count-only note must never overwrite a lower-confidence row
            # that carries the same count plus figured width/height.
            resolved_opening_rows[tag] = max(
                group,
                key=lambda candidate: (
                    int(
                        candidate.quantity is not None
                        and candidate.quantity > 0
                        and candidate.dimensions is not None
                        and len(candidate.dimensions) >= 2
                    ),
                    int(candidate.dimensions is not None and len(candidate.dimensions) >= 2),
                    int(candidate.quantity is not None and candidate.quantity > 0),
                    candidate.confidence,
                ),
            )

        for r in rows:
            if r.is_provisional:
                continue

            norm = normalize_opening_tag(r.tag)
            if norm is not None:
                r.tag = norm.tag
                r.trade_type = norm.trade_type
                if r.tag in conflicting_opening_tags:
                    continue
                # One canonical row per explicit opening identity.  Selecting
                # it here prevents a second count-only detector result from
                # surviving under a dimensionless key and later overwriting
                # the complete schedule prediction in production.
                if resolved_opening_rows.get(r.tag) is not r:
                    continue

            if r.tag == "brick_vents":
                if r.source_page not in vent_pages and r.quantity:
                    vent_pages[r.source_page] = r.quantity
                continue

            dim_str = ""
            if r.dimensions and len(r.dimensions) >= 2:
                dim_str = f"_{int(r.dimensions[0])}x{int(r.dimensions[1])}"
            elif r.dimensions and len(r.dimensions) == 1:
                dim_str = f"_{int(r.dimensions[0])}"
            key = f"{r.tag}{dim_str}"

            if key not in deduped:
                deduped[key] = r
            else:
                existing = deduped[key]
                if r.confidence > existing.confidence:
                    deduped[key] = r

        result = list(deduped.values())

        if vent_pages:
            total_vents = sum(vent_pages.values())
            first_vent_row = next(r for r in rows if r.tag == "brick_vents")
            result.append(
                ScheduleRow(
                    tag="brick_vents",
                    trade_type="walls",
                    description=f"Precast / brick ventilation openings ({int(total_vents)} No total across facades)",
                    quantity=total_vents,
                    unit="NO",
                    source_page=first_vent_row.source_page,
                    bbox=first_vent_row.bbox,
                    confidence=0.90,
                    evidence_text=f"Total {int(total_vents)} vents across pages {list(vent_pages.keys())}",
                )
            )

        return result

    def _parse_quantity_string(self, text: str) -> Optional[float]:
        """Parse count / quantity strictly from string, returning None if unevidenced."""
        if not text:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:no\.?s?|nos?|units?|pcs?|nr\.?)?", text, re.I)
        if m:
            try:
                val = float(m.group(1))
                return val if val > 0 else None
            except ValueError:
                return None
        return None

    def _parse_dimensions_string(self, text: str) -> Optional[List[float]]:
        """Parse width and height dimensions from string (e.g. '3000 x 1200', '900*2100')."""
        if not text:
            return None
        clean = text.replace(",", "")
        m = re.search(r"(\d{3,4})\s*(?:mm)?\s*[*xX×]\s*(\d{3,4})\s*(?:mm)?", clean)
        if m:
            try:
                return [float(m.group(1)), float(m.group(2))]
            except ValueError:
                return None
        return None
