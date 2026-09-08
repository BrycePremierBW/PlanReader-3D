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

        # 2. Column-aligned schedule detection (CAD multi-column schedules)
        col_rows = self._extract_column_aligned_schedules(page, page_num)
        page_rows.extend(col_rows)

        # 3. Explicit callouts (windows, doors, vents, pillars, trusses)
        callout_rows = self._extract_callouts_from_page(page, page_num)
        page_rows.extend(callout_rows)

        return page_rows

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

                    # Determine trade type
                    combined_text = f"{raw_tag} {raw_desc} {raw_dim}".lower()
                    trade = "other"
                    if any(k in combined_text for k in ("window", "casement", "glaz", "w1", "w2", "w3", "w4")):
                        trade = "windows"
                    elif any(k in combined_text for k in ("door", "flush", "panelled", "d1", "d2")):
                        trade = "doors"
                    elif any(k in combined_text for k in ("vent", "pv")):
                        trade = "walls"
                    elif any(k in combined_text for k in ("pillar", "column", "pier", "truss")):
                        trade = "structure"

                    # Only accept recognized architectural trade tags, skip generic non-schedule items
                    if trade == "other" or not raw_tag or raw_tag.startswith("ITEM_") or raw_tag.isdigit():
                        continue
                    tag_name = raw_tag

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
                
                is_window = any(k in col_text.lower() for k in ("casement", "window", "glass", "fixed glass"))
                is_door = any(k in col_text.lower() for k in ("door", "flush door", "panelled door"))

                if not (is_window or is_door):
                    continue

                trade = "windows" if is_window else "doors"
                dims = self._parse_dimensions_string(col_text)

                qty_match = re.search(r"\b(\d+)\s*(?:no\.?s?|nos?)\b", col_text, re.I)
                qty = float(qty_match.group(1)) if qty_match else None

                c_x0 = min(w[0] for w in col_w)
                c_y0 = min(w[1] for w in col_w)
                c_x1 = max(w[2] for w in col_w)
                c_y1 = max(w[3] for w in col_w)

                tag_match = re.search(r"\b(W\d+|D\d+)\b", col_text, re.I)
                tag_name = tag_match.group(1).upper() if tag_match else f"{trade[0].upper()}_COL_{col_idx}"

                if qty is not None:
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
                            description=f"Column schedule item {tag_name} (unquantified)",
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
        pv_words = [w for w in page.get_text("words") if re.match(r"^(?:PV|P\.V)$", w[4], re.I)]
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

        for r in rows:
            if r.is_provisional:
                continue

            if r.tag == "brick_vents":
                if r.source_page not in vent_pages and r.quantity:
                    vent_pages[r.source_page] = r.quantity
                continue

            dim_str = f"_{int(r.dimensions[0])}x{int(r.dimensions[1])}" if r.dimensions else ""
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
