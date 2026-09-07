"""pb_drawing_ocr_evidence_layer.py — Generic Drawing Vision / OCR Evidence Layer.

PR F.10: Generic, leak-free visual and OCR drawing evidence recovery.

CRITICAL ARCHITECTURAL RULES:
1. Generic only: ZERO benchmark IDs, ground truth BOQs, or project-name heuristics.
2. Prefer native evidence first: PDF text, word spans, and vector tables are prioritized.
3. Fall back to raster OCR only when native extraction is missing or incomplete.
4. Fail closed:
   - Uncertain or noisy OCR stays provisional.
   - Conflicting native vs OCR values are flagged for manual review and blocked from firm prediction.
   - Clipped counts (e.g. "No." without digits) NEVER infer or guess numbers.
5. Every evidence record carries:
   - source_page
   - bounding_box: [x0, y0, x1, y1]
   - extracted_text / extracted_value
   - confidence
   - extraction_method
   - raw_evidence_ref
   - status
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageFilter, ImageStat

try:
    import winocr
    _HAS_WINOCR = True
except Exception:
    winocr = None
    _HAS_WINOCR = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False


class EvidenceMethod(str, Enum):
    """Extraction method used to derive drawing evidence."""

    NATIVE_TEXT = "native_text"
    NATIVE_TABLE = "native_table"
    CAD_CLUSTERING = "cad_clustering"
    RASTER_OCR = "raster_ocr"
    RECONCILED = "reconciled"


class EvidenceStatus(str, Enum):
    """Integrity and review status of extracted evidence."""

    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    CONFLICT_MANUAL_REVIEW = "conflict_manual_review"
    UNRESOLVED = "unresolved"


@dataclass
class DrawingEvidenceRecord:
    """A granular, auditable piece of drawing evidence."""

    tag: str
    trade_type: str  # "windows", "doors", "structure", "walls", "fixtures"
    description: str
    quantity: Optional[float]
    unit: str = "NO"
    dimensions: Optional[List[float]] = None
    source_page: int = 1
    bounding_box: Optional[List[float]] = None  # [x0, y0, x1, y1]
    extracted_text: str = ""
    extracted_value: Any = None
    confidence: float = 0.90
    extraction_method: str = EvidenceMethod.NATIVE_TEXT.value
    raw_evidence_ref: str = ""
    status: str = EvidenceStatus.CONFIRMED.value
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "trade_type": self.trade_type,
            "description": self.description,
            "quantity": self.quantity,
            "unit": self.unit,
            "dimensions": self.dimensions,
            "source_page": self.source_page,
            "bounding_box": self.bounding_box,
            "extracted_text": self.extracted_text,
            "extracted_value": self.extracted_value,
            "confidence": round(self.confidence, 4),
            "extraction_method": self.extraction_method,
            "raw_evidence_ref": self.raw_evidence_ref,
            "status": self.status,
            "notes": self.notes,
        }


class DrawingOCREngine:
    """Visual evidence and OCR extraction engine with pluggable backend and quality evaluation."""

    def __init__(
        self,
        custom_ocr_func: Optional[Callable[[Image.Image], List[Dict[str, Any]]]] = None,
    ) -> None:
        self.custom_ocr_func = custom_ocr_func

    def evaluate_image_quality(self, image: Image.Image) -> float:
        """Evaluate image sharpness, contrast, and noise. Returns quality score 0.0 to 1.0."""
        # 1. Contrast check via standard deviation of grayscale luminance
        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        std_dev = stat.stddev[0]  # Contrast measure: low std dev means washed out / faint
        if std_dev < 15.0:
            return 0.35

        # 2. Sharpness check using high-pass / edge detection
        edges = gray.filter(ImageFilter.FIND_EDGES)
        stat_edges = ImageStat.Stat(edges)
        edge_energy = stat_edges.mean[0]

        # Higher edge energy means sharper letter contours
        if edge_energy < 3.0:
            return 0.40
        elif edge_energy < 8.5:
            return 0.60
        return 1.0

    def recognize_pil_image(self, image: Image.Image, lang: str = "en") -> List[Dict[str, Any]]:
        """Run OCR on a PIL Image. Returns list of lines with text, bbox, and confidence."""
        quality = self.evaluate_image_quality(image)

        # 1. Custom or injected OCR function (used in tests or mocked environments)
        if self.custom_ocr_func is not None:
            raw_lines = self.custom_ocr_func(image)
            out = []
            for r in raw_lines:
                r_conf = r.get("confidence", 0.90) * quality
                out.append({
                    "text": r.get("text", ""),
                    "bounding_box": r.get("bounding_box", [0.0, 0.0, float(image.width), float(image.height)]),
                    "confidence": round(r_conf, 4),
                })
            return out

        # 2. Windows Media OCR (winocr) on Windows systems
        if _HAS_WINOCR and winocr is not None:
            try:
                res = winocr.recognize_pil_sync(image, lang)
                lines_data = res.get("lines", [])
                out = []
                for line in lines_data:
                    line_text = line.get("text", "").strip()
                    if not line_text:
                        continue
                    # Compute line bounding rect from words if available
                    words = line.get("words", [])
                    if words:
                        xs = [w["bounding_rect"]["x"] for w in words if "bounding_rect" in w]
                        ys = [w["bounding_rect"]["y"] for w in words if "bounding_rect" in w]
                        x2s = [w["bounding_rect"]["x"] + w["bounding_rect"]["width"] for w in words if "bounding_rect" in w]
                        y2s = [w["bounding_rect"]["y"] + w["bounding_rect"]["height"] for w in words if "bounding_rect" in w]
                        bbox = [min(xs), min(ys), max(x2s), max(y2s)] if xs else [0.0, 0.0, float(image.width), float(image.height)]
                    else:
                        bbox = [0.0, 0.0, float(image.width), float(image.height)]

                    out.append({
                        "text": line_text,
                        "bounding_box": bbox,
                        "confidence": round(0.88 * quality, 4),
                    })
                return out
            except Exception:
                pass

        return []

    def recognize_page_rect(
        self,
        page: fitz.Page,
        clip_rect: Optional[fitz.Rect] = None,
        dpi: int = 150,
    ) -> List[Dict[str, Any]]:
        """Render a page or sub-rect to high-res pixmap and run OCR."""
        try:
            pix = page.get_pixmap(clip=clip_rect, dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            scale = 72.0 / dpi
            ocr_lines = self.recognize_pil_image(img)

            # Map image pixel coordinates back to PDF point space
            offset_x = clip_rect.x0 if clip_rect else 0.0
            offset_y = clip_rect.y0 if clip_rect else 0.0

            for line in ocr_lines:
                bx0, by0, bx1, by1 = line["bounding_box"]
                line["bounding_box"] = [
                    round(offset_x + bx0 * scale, 2),
                    round(offset_y + by0 * scale, 2),
                    round(offset_x + bx1 * scale, 2),
                    round(offset_y + by1 * scale, 2),
                ]
            return ocr_lines
        except Exception:
            return []


class DrawingEvidenceParser:
    """Parses drawing text and OCR lines into structured schedule and callout evidence."""

    @staticmethod
    def parse_schedule_line(
        text: str,
        source_page: int = 1,
        bbox: Optional[List[float]] = None,
        confidence: float = 0.90,
        method: str = EvidenceMethod.RASTER_OCR.value,
    ) -> Optional[DrawingEvidenceRecord]:
        """Parse a single text or OCR line into an evidence record.

        Strictly enforces fail-closed behavior:
        - If 'No.' exists with no leading number -> quantity is None.
        - If dimensions exist without count -> quantity is None.
        - Never guesses.
        """
        clean = " ".join(text.split()).strip()
        if not clean:
            return None

        # 1. Window / Door Schedule Line: e.g. "W_TEST - 1500 x 1200 - 7 No" or "W1: 3000 x 900 - 2 No."
        m_indexed = re.search(r"\b([WwDd]\s*[-_]?\s*[A-Za-z0-9]+)\b", clean)
        if m_indexed and not re.search(r"\b(?:door|window)\b", m_indexed.group(1), re.I):
            tag = re.sub(r"\s+", "", m_indexed.group(1)).upper()
        else:
            m_tag = re.search(r"\b(WINDOW\s*[A-Za-z0-9]*|DOOR\s*[A-Za-z0-9]*)\b", clean, re.I)
            tag = re.sub(r"\s+", "", m_tag.group(1)).upper() if m_tag else None

        # Dimensions: W x H
        m_dims = re.search(r"(\d{3,4})\s*(?:mm)?\s*[xX\*]\s*(\d{3,4})\s*(?:mm)?", clean)
        dims: Optional[List[float]] = None
        if m_dims:
            dims = [float(m_dims.group(1)), float(m_dims.group(2))]

        # Quantity: Explicit digits preceding "No." or "Nos."
        # Check for hardware/hinge/lock counts which are not opening quantities
        is_hardware = bool(re.search(r"butt\s*hinge|hinge|fastener|lever\s*lock|ironmongery", clean, re.I))
        m_valid_qty = None
        if not is_hardware:
            m_valid_qty = re.search(r"\b(\d{1,3})\s*(?:no\.?s?|nos?)\b", clean, re.I)
        else:
            m_explicit_doors = re.search(r"\b(\d{1,3})\s*(?:no\.?s?|nos?)\s*(?:steel|timber|panelled)?\s*doors?\b", clean, re.I)
            if m_explicit_doors:
                m_valid_qty = m_explicit_doors

        # Check for clipped count: "No." without digits immediately before it
        m_clipped = re.search(r"(?<!\d)\s*(?:no\.?s?|nos?)\b", clean, re.I)

        qty: Optional[float] = None
        status = EvidenceStatus.CONFIRMED.value
        notes = ""

        if m_valid_qty:
            qty = float(m_valid_qty.group(1))
        elif m_clipped:
            # Clipped annotation detected! FAIL CLOSED: Never invent quantity
            qty = None
            status = EvidenceStatus.UNRESOLVED.value
            notes = "Clipped 'No.' text missing preceding digit; fail-closed without guessing."
        elif dims:
            # Dimensions found but count absent
            qty = None
            status = EvidenceStatus.UNRESOLVED.value
            notes = "Opening dimensions found but quantity count absent."

        if not tag and not dims:
            return None

        final_tag = tag or ("WINDOW_ITEM" if "win" in clean.lower() else "DOOR_ITEM")
        trade = "windows" if (final_tag.startswith("W") or "win" in clean.lower()) else "doors"

        # Check confidence threshold: low confidence stays provisional
        if confidence < 0.70 and status == EvidenceStatus.CONFIRMED.value:
            status = EvidenceStatus.PROVISIONAL.value
            notes = "Low visual/OCR confidence; marked provisional."

        return DrawingEvidenceRecord(
            tag=final_tag,
            trade_type=trade,
            description=f"{final_tag} schedule item ({clean})",
            quantity=qty,
            unit="NO",
            dimensions=dims,
            source_page=source_page,
            bounding_box=bbox,
            extracted_text=clean,
            extracted_value=qty,
            confidence=confidence,
            extraction_method=method,
            raw_evidence_ref=clean,
            status=status,
            notes=notes,
        )


class EvidenceReconciler:
    """Reconciles native and OCR drawing evidence following strict fail-closed and conflict rules."""

    @staticmethod
    def reconcile(
        native_records: Sequence[DrawingEvidenceRecord],
        ocr_records: Sequence[DrawingEvidenceRecord],
    ) -> List[DrawingEvidenceRecord]:
        """Reconcile native evidence with OCR evidence.

        Rules:
        1. Prefer native evidence first.
        2. If native is complete and OCR matches -> CONFIRMED with RECONCILED method.
        3. If native and OCR disagree -> CONFLICT_MANUAL_REVIEW, quantity=None, blocked.
        4. If native has zero or incomplete rows and OCR provides complete evidence -> RASTER_OCR.
        5. Clipped or unevidenced counts remain UNRESOLVED.
        """
        by_tag_native: Dict[str, DrawingEvidenceRecord] = {r.tag: r for r in native_records}
        # Normalize generic OCR tags (DOOR, WINDOW, DOOR_ITEM, WINDOW_ITEM)
        # to match existing native indexed tags with identical dimensions
        normalized_ocr_records = []
        for r_ocr in ocr_records:
            if r_ocr.tag in ("DOOR", "WINDOW", "DOOR_ITEM", "WINDOW_ITEM") and r_ocr.dimensions:
                matched_tag = None
                for nat_tag, r_nat in by_tag_native.items():
                    if r_nat.dimensions and r_nat.dimensions == r_ocr.dimensions:
                        matched_tag = nat_tag
                        break
                if matched_tag:
                    r_ocr.tag = matched_tag
            normalized_ocr_records.append(r_ocr)

        by_tag_ocr: Dict[str, DrawingEvidenceRecord] = {r.tag: r for r in normalized_ocr_records}

        all_tags = list(dict.fromkeys(list(by_tag_native.keys()) + list(by_tag_ocr.keys())))
        reconciled: List[DrawingEvidenceRecord] = []

        for tag in all_tags:
            r_nat = by_tag_native.get(tag)
            r_ocr = by_tag_ocr.get(tag)

            # Case 1: Both native and OCR present
            if r_nat and r_ocr:
                nat_qty = r_nat.quantity
                ocr_qty = r_ocr.quantity

                # Both have quantities
                if nat_qty is not None and ocr_qty is not None:
                    if nat_qty == ocr_qty:
                        # Perfect agreement
                        merged_conf = min(1.0, max(r_nat.confidence, r_ocr.confidence) + 0.05)
                        reconciled.append(
                            DrawingEvidenceRecord(
                                tag=tag,
                                trade_type=r_nat.trade_type,
                                description=r_nat.description,
                                quantity=nat_qty,
                                unit=r_nat.unit,
                                dimensions=r_nat.dimensions or r_ocr.dimensions,
                                source_page=r_nat.source_page,
                                bounding_box=r_nat.bounding_box or r_ocr.bounding_box,
                                extracted_text=f"Native: '{r_nat.extracted_text}' | OCR: '{r_ocr.extracted_text}'",
                                extracted_value=nat_qty,
                                confidence=merged_conf,
                                extraction_method=EvidenceMethod.RECONCILED.value,
                                raw_evidence_ref=f"Native({r_nat.raw_evidence_ref}) + OCR({r_ocr.raw_evidence_ref})",
                                status=EvidenceStatus.CONFIRMED.value,
                                notes="Confirmed via cross-validation between native text and OCR layer.",
                            )
                        )
                    else:
                        # Conflicting values! FAIL CLOSED: Manual review
                        reconciled.append(
                            DrawingEvidenceRecord(
                                tag=tag,
                                trade_type=r_nat.trade_type,
                                description=r_nat.description,
                                quantity=None,
                                unit=r_nat.unit,
                                dimensions=r_nat.dimensions or r_ocr.dimensions,
                                source_page=r_nat.source_page,
                                bounding_box=r_nat.bounding_box or r_ocr.bounding_box,
                                extracted_text=f"Native: '{r_nat.extracted_text}' ({nat_qty}) vs OCR: '{r_ocr.extracted_text}' ({ocr_qty})",
                                extracted_value=None,
                                confidence=0.0,
                                extraction_method=EvidenceMethod.RECONCILED.value,
                                raw_evidence_ref=f"Conflict: native={nat_qty} vs ocr={ocr_qty}",
                                status=EvidenceStatus.CONFLICT_MANUAL_REVIEW.value,
                                notes=f"Conflict detected between native ({nat_qty}) and OCR ({ocr_qty}); blocked from firm prediction.",
                            )
                        )
                elif nat_qty is not None:
                    # Native has quantity, OCR does not
                    reconciled.append(r_nat)
                elif ocr_qty is not None:
                    # OCR has quantity, native does not (e.g. raster CAD sheet)
                    reconciled.append(r_ocr)
                else:
                    # Neither has quantity
                    reconciled.append(r_nat)

            # Case 2: Only in native
            elif r_nat:
                reconciled.append(r_nat)

            # Case 3: Only in OCR
            elif r_ocr:
                reconciled.append(r_ocr)

        return reconciled
