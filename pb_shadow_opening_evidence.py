"""Gold-free opening-count evidence helpers for the shadow provider.

Raster schedule reading reuses ``DrawingOCREngine`` with a *shadow-only*
Tesseract adapter. The default ``DrawingOCREngine()`` used by the legacy
extractor is unchanged (no custom OCR).

Native drawing-tag acceptance is conservative: section/detail references,
drawing numbers, dimension labels, grid references, room labels, NRM codes,
legend-only definitions, and notes are not type-count evidence.

A raster table is not an opening schedule unless it carries opening-schedule
authority (title, mark column, door/window type labels, quantity column,
and/or repeated D/W marks with contextual headers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from pb_drawing_ocr_evidence_layer import DrawingOCREngine
from pb_migration_contracts import QuantityEvidence, stable_contract_id
from pb_opening_tag_normalization import normalize_opening_tag

_OPENING_MARK_RE = re.compile(r"\b([WwDd])\s*[-_]?\s*(\d{1,3})\b")
_AMBIGUOUS_OCR_MARK_RE = re.compile(
    r"^(?:[WwDd][Il]|WDI|[WwDd]\d+[?]|[WwDd][?]+)$",
    re.IGNORECASE,
)
_TITLE_OPENING_SCHEDULE_RE = re.compile(
    r"\b(?:window|door|opening)\s+schedul|"
    r"\bschedule\s+of\s+(?:windows|doors|openings)\b|"
    r"\b(?:windows?|doors?)\s+schedule\b|"
    r"\bwindow\s+and\s+door\s+schedul",
    re.IGNORECASE,
)
_TITLE_NON_OPENING_SCHEDULE_RE = re.compile(
    r"\bbill\s+of\s+quantit|"
    r"\bbills?\s+of\s+quantit|"
    r"\bbuilder'?s?\s+work\b|"
    r"\bbw\s*/?\s*\d|"
    r"\bnrm\b|"
    r"\bcost\s+schedule\b|"
    r"\bspecification\s+table\b|"
    r"\bmechanical\s+works?\b|"
    r"\bexcavating\b|"
    r"\bhardcore\b|"
    r"\bpreliminar|"
    r"\bironmongery\b|"
    r"\bfinishes?\s+schedule\b",
    re.IGNORECASE,
)
_QTY_HEADER_RE = re.compile(
    r"\b(?:overall\s+quantity|quantity|qty\.?|no\.?\s*off|nos?\.?)\b",
    re.IGNORECASE,
)
_MARK_HEADER_RE = re.compile(
    r"\b(?:mark|type|ref(?:erence)?|opening\s+type|door\s+type|window\s+type)\b",
    re.IGNORECASE,
)
_DIM_HEADER_RE = re.compile(
    r"\b(?:width|height|size|w\s*x\s*h|overall\s+size|dimensions?)\b",
    re.IGNORECASE,
)
_NON_OPENING_CONTEXT_RE = re.compile(
    r"\b(?:excavating|hardcore|mechanical\s+works?|work\s+section|"
    r"nrm|preliminar|builder'?s?\s+work|bill\s+of\s+quantit|"
    r"demolition|site\s+clearance|caws)\b",
    re.IGNORECASE,
)
_BILL_PAGE_HINT_RE = re.compile(
    r"\bbill\s+of\s+quantit|"
    r"\bbills?\s+of\s+quantit|"
    r"\bbuilder'?s?\s+work\b|"
    r"\bbw\s*/?\s*\d|"
    r"\bitem\s+description\s+qty\s+unit\s+rate\b|"
    r"\bref\.?\s+description\s+quantity\s+unit\s+rate\b|"
    r"\bnrm\b|"
    r"\bd20\s+excavating\b",
    re.IGNORECASE,
)
_NATIVE_FORBIDDEN_CONTEXT_RE = re.compile(
    r"\b(?:see\s+detail|detail\s+(?:no\.?|number)|drawing\s+no\.?|"
    r"drg\.?\s*no\.?|section\s+[A-Z]|grid\s+(?:line|ref)|"
    r"room\s+(?:no\.?|name)|legend|typical\s+detail|"
    r"note[s]?:|refer\s+to|as\s+per|title\s+block|"
    r"rev(?:ision)?\s+\d|sheet\s+\d)\b",
    re.IGNORECASE,
)
_DETAIL_NUMBER_RE = re.compile(
    r"\b(?:detail|dtl|section|elev(?:ation)?)\s*[-_/]?\s*[WwDd]\s*[-_]?\s*\d{1,3}\b",
    re.IGNORECASE,
)
_DRAWING_TITLE_RE = re.compile(
    r"\b(?:drawing|drg|sheet|title)\b.{0,40}\b[WwDd]\s*[-_]?\s*\d{1,3}\b",
    re.IGNORECASE,
)
_LEGEND_LINE_RE = re.compile(
    r"\blegend\b|\bkey\s*:|\btypical\s+mark\b|\bdenotes\b",
    re.IGNORECASE,
)
_NOTE_LINE_RE = re.compile(
    r"^\s*(?:note[s]?|n\.b\.|nb)[\s.:]",
    re.IGNORECASE,
)
_GRID_AXIS_RE = re.compile(
    r"\b(?:grid|grids?)\b|\b[A-Z]\s*/\s*\d{1,2}\b",
    re.IGNORECASE,
)
_WORK_SECTION_CODE_RE = re.compile(
    r"\b([A-Z])\s*(\d{2})\b",
    re.IGNORECASE,
)
_COMPLETE_QTY_RE = re.compile(r"\b(\d{1,3})\s*(?:no\.?s?|nos?)\b", re.IGNORECASE)
_COMPLETE_SCHEDULE_ROW_RE = re.compile(
    r"\b(?P<tag>[WwDd]\s*[-_]?\s*\d{1,3})\b"
    r".{0,80}?"
    r"(?P<w>\d{3,4})\s*(?:mm)?\s*[xX\*]\s*(?P<h>\d{3,4})"
    r".{0,40}?"
    r"\b(?P<qty>\d{1,3})\s*(?:no\.?s?|nos?)\b",
    re.IGNORECASE | re.DOTALL,
)

AUTHORITATIVE_TYPE_FORMULAS = frozenset(
    {"explicit_schedule_count", "schedule_plan_corroborated"}
)
FAMILY_TOTAL_KEYS = {
    "door_count": "door_total",
    "window_count": "window_total",
}
FORMULA_FAMILY_TOTAL = "sum_of_authoritative_type_counts"


def page_looks_like_bill_or_nrm(page_text: str) -> bool:
    """True when the page/table is a BOQ / Builder's Work / NRM bill."""
    if not page_text or not page_text.strip():
        return False
    return bool(_BILL_PAGE_HINT_RE.search(page_text))


def is_work_section_or_nrm_code(raw: str, surrounding: str = "") -> bool:
    """True for NRM / CAWS work-section codes (D20 EXCAVATING, D10 demolition, W20)."""
    blob = f"{raw} {surrounding}"
    if _TITLE_OPENING_SCHEDULE_RE.search(blob) and _OPENING_MARK_RE.search(raw or surrounding):
        if not _NON_OPENING_CONTEXT_RE.search(blob):
            return False
    if _NON_OPENING_CONTEXT_RE.search(blob):
        return True
    match = _WORK_SECTION_CODE_RE.search(blob)
    if not match:
        return False
    letter = match.group(1).upper()
    number = match.group(2)
    if letter not in {"D", "W"} or number not in {"10", "20", "30", "40"}:
        return False
    if re.search(r"\b(?:excavating|demolition|work\s+section|caws|nrm|site\s+clearance)\b", blob, re.IGNORECASE):
        return True
    if re.search(r"\b(?:excav|demol|hardcore|concrete|masonry)\b", blob, re.IGNORECASE):
        return True
    return False


def is_ambiguous_ocr_mark(raw: str) -> bool:
    """True when OCR cannot distinguish a mark from lookalikes (D1/DI, W1/WI)."""
    token = re.sub(r"[\s_\-]", "", (raw or "").strip())
    if not token:
        return True
    if _AMBIGUOUS_OCR_MARK_RE.match(token):
        return True
    if re.fullmatch(r"[WwDd][Il]", token):
        return True
    if re.fullmatch(r"WDI\d*", token, re.IGNORECASE):
        return True
    if "?" in token:
        return True
    return False


def ocr_mark_is_usable(raw: str, *, min_confidence: float | None = None) -> bool:
    if is_ambiguous_ocr_mark(raw):
        return False
    if min_confidence is not None and min_confidence < 0.55:
        return False
    return normalize_opening_tag(raw) is not None


@dataclass(frozen=True)
class OpeningScheduleAuthority:
    accepted: bool
    score: int
    reasons: tuple[str, ...]
    title_is_opening_schedule: bool
    has_mark_column: bool
    has_qty_column: bool
    has_dim_column: bool
    repeated_marks: int


def assess_opening_schedule_authority(
    *,
    title: str = "",
    headers: Sequence[str] = (),
    body_text: str = "",
    mark_hits: int = 0,
    distinct_marks: int = 0,
) -> OpeningScheduleAuthority:
    """Require enough structure to prove the table/card is about doors/windows."""
    blob = " ".join(part for part in (title, " ".join(headers), body_text) if part)
    reasons: list[str] = []
    score = 0

    if _TITLE_NON_OPENING_SCHEDULE_RE.search(blob) or _BILL_PAGE_HINT_RE.search(blob):
        return OpeningScheduleAuthority(
            accepted=False,
            score=0,
            reasons=("non_opening_schedule_context",),
            title_is_opening_schedule=False,
            has_mark_column=False,
            has_qty_column=False,
            has_dim_column=False,
            repeated_marks=mark_hits,
        )

    title_ok = bool(_TITLE_OPENING_SCHEDULE_RE.search(title or blob))
    if title_ok:
        score += 4
        reasons.append("opening_schedule_title")

    header_blob = " ".join(headers)
    has_mark = bool(_MARK_HEADER_RE.search(header_blob) or _MARK_HEADER_RE.search(blob))
    has_qty = bool(_QTY_HEADER_RE.search(header_blob) or _QTY_HEADER_RE.search(blob))
    has_dim = bool(_DIM_HEADER_RE.search(header_blob) or _DIM_HEADER_RE.search(blob))
    if has_mark:
        score += 2
        reasons.append("opening_mark_column")
    if has_qty:
        score += 2
        reasons.append("quantity_column")
    if has_dim:
        score += 1
        reasons.append("dimension_column")

    type_labels = bool(
        re.search(r"\b(?:door|window|opening)\s+type\b", blob, re.IGNORECASE)
        or re.search(r"\b(?:casement|flush\s+door|steel\s+casement)\b", blob, re.IGNORECASE)
    )
    if type_labels:
        score += 2
        reasons.append("opening_type_labels")

    if mark_hits >= 2:
        score += 2
        reasons.append("repeated_opening_marks")
    elif mark_hits == 1 and not title_ok:
        reasons.append("lone_mark_insufficient")

    if distinct_marks >= 2:
        score += 1
        reasons.append("multiple_opening_types")

    accepted = score >= 5 and (
        title_ok or (has_mark and has_qty) or (has_mark and mark_hits >= 2 and has_qty)
    )
    if not accepted and "insufficient_opening_schedule_authority" not in reasons:
        reasons.append("insufficient_opening_schedule_authority")
    return OpeningScheduleAuthority(
        accepted=accepted,
        score=score,
        reasons=tuple(reasons),
        title_is_opening_schedule=title_ok,
        has_mark_column=has_mark,
        has_qty_column=has_qty,
        has_dim_column=has_dim,
        repeated_marks=mark_hits,
    )


def has_opening_schedule_semantics(
    *,
    title: str = "",
    headers: Sequence[str] = (),
    body_text: str = "",
    mark_hits: int = 0,
    distinct_marks: int = 0,
) -> bool:
    return assess_opening_schedule_authority(
        title=title,
        headers=headers,
        body_text=body_text,
        mark_hits=mark_hits,
        distinct_marks=distinct_marks,
    ).accepted


def iter_complete_opening_schedule_rows(text: str) -> list[dict[str, Any]]:
    """Split a raster schedule blob into complete mark/dimension/quantity rows."""
    rows: list[dict[str, Any]] = []
    if not text or page_looks_like_bill_or_nrm(text) or _NON_OPENING_CONTEXT_RE.search(text):
        return rows
    for match in _COMPLETE_SCHEDULE_ROW_RE.finditer(text):
        tag = re.sub(r"\s+", "", match.group("tag")).upper()
        if is_ambiguous_ocr_mark(tag) or not ocr_mark_is_usable(tag):
            continue
        if is_work_section_or_nrm_code(tag, match.group(0)):
            continue
        rows.append(
            {
                "text": match.group(0),
                "tag": tag,
                "quantity": float(match.group("qty")),
                "dimensions": [float(match.group("w")), float(match.group("h"))],
            }
        )
    return rows


def schedule_line_is_authoritative(text: str, *, tag: str = "", quantity: float | None = None) -> bool:
    """A complete opening-schedule row may stand as type-count evidence.

    A lone ``D20`` token is not enough. Quantity-looking BOQ rows are not enough.
    """
    blob = text or ""
    if page_looks_like_bill_or_nrm(blob) or _NON_OPENING_CONTEXT_RE.search(blob):
        return False
    if is_work_section_or_nrm_code(tag or blob, blob):
        return False
    if tag and (is_ambiguous_ocr_mark(tag) or not ocr_mark_is_usable(tag)):
        return False
    if quantity is None:
        return False
    has_dims = bool(re.search(r"\d{3,4}\s*(?:mm)?\s*[xX\*]\s*\d{3,4}", blob))
    has_opening_words = bool(re.search(r"\b(?:door|window|casement|flush)\b", blob, re.IGNORECASE))
    has_no = bool(_COMPLETE_QTY_RE.search(blob))
    return bool(has_dims or has_opening_words or has_no)


def native_tag_context_allowed(line: str, nearby: str = "") -> bool:
    """Conservative gate for native drawing-tag type-count evidence."""
    blob = f"{line} {nearby}"
    if page_looks_like_bill_or_nrm(blob):
        return False
    if _NON_OPENING_CONTEXT_RE.search(blob):
        return False
    if is_work_section_or_nrm_code(line, nearby):
        return False
    if _NATIVE_FORBIDDEN_CONTEXT_RE.search(blob):
        return False
    if _DETAIL_NUMBER_RE.search(blob):
        return False
    if _DRAWING_TITLE_RE.search(blob):
        return False
    if _LEGEND_LINE_RE.search(blob) or _LEGEND_LINE_RE.search(line):
        return False
    if _NOTE_LINE_RE.search(line) or _NOTE_LINE_RE.search(nearby):
        return False
    if _GRID_AXIS_RE.search(nearby):
        return False
    if is_ambiguous_ocr_mark(line):
        return False
    return True


def nearby_word_text(
    words: Sequence[Any],
    center: tuple[float, float] | None,
    *,
    radius: float = 80.0,
) -> str:
    if center is None or not words:
        return ""
    cx, cy = center
    parts: list[str] = []
    for word in words:
        if isinstance(word, (tuple, list)) and len(word) >= 5:
            bbox = word[:4]
            text = str(word[4] or "")
        else:
            bbox = getattr(word, "bbox", None)
            text = str(getattr(word, "text", "") or "")
        if bbox is None or len(bbox) < 4:
            continue
        wx = (float(bbox[0]) + float(bbox[2])) / 2.0
        wy = (float(bbox[1]) + float(bbox[3])) / 2.0
        if abs(wx - cx) <= radius and abs(wy - cy) <= radius:
            parts.append(text)
    return " ".join(parts)


def group_ocr_tokens_into_lines(
    tokens: Sequence[Mapping[str, Any]],
    *,
    y_tol: float = 8.0,
) -> list[dict[str, Any]]:
    """Merge word-level OCR tokens into reading-order lines."""
    prepared: list[tuple[float, float, list[float], str, float]] = []
    for token in tokens:
        text = str(token.get("text") or "").strip()
        if not text:
            continue
        bbox = list(token.get("bounding_box") or token.get("bbox") or ())
        if len(bbox) < 4:
            bbox = [0.0, 0.0, 0.0, 0.0]
        try:
            conf = float(token.get("confidence") if token.get("confidence") is not None else 0.8)
        except (TypeError, ValueError):
            conf = 0.8
        prepared.append((float(bbox[1]), float(bbox[0]), [float(v) for v in bbox[:4]], text, conf))
    prepared.sort(key=lambda item: (round(item[0] / y_tol), item[1]))

    lines: list[dict[str, Any]] = []
    current: list[tuple[float, float, list[float], str, float]] = []
    current_y: float | None = None
    for item in prepared:
        if current_y is None or abs(item[0] - current_y) <= y_tol:
            current.append(item)
            current_y = item[0] if current_y is None else (current_y + item[0]) / 2.0
            continue
        lines.append(_merge_ocr_line(current))
        current = [item]
        current_y = item[0]
    if current:
        lines.append(_merge_ocr_line(current))
    return lines


def _merge_ocr_line(items: Sequence[tuple[float, float, list[float], str, float]]) -> dict[str, Any]:
    ordered = sorted(items, key=lambda item: item[1])
    xs0 = [item[2][0] for item in ordered]
    ys0 = [item[2][1] for item in ordered]
    xs1 = [item[2][2] for item in ordered]
    ys1 = [item[2][3] for item in ordered]
    confs = [item[4] for item in ordered]
    return {
        "text": " ".join(item[3] for item in ordered),
        "bbox": [min(xs0), min(ys0), max(xs1), max(ys1)],
        "confidence": min(confs) if confs else 0.5,
    }


def tesseract_image_lines(image: Any) -> list[dict[str, Any]]:
    """Shadow-only ``DrawingOCREngine.custom_ocr_func`` using pytesseract.

    Must not be installed as the default on ``DrawingOCREngine()`` — that
    path is used by the legacy extractor and must stay empty on this host.
    """
    try:
        import pytesseract
        from PIL import Image as PILImage
    except ImportError:
        return []

    if image is None:
        return []
    if not isinstance(image, PILImage.Image):
        try:
            image = PILImage.fromarray(image)
        except Exception:
            return []

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    n = len(data.get("text") or [])
    lines: list[dict[str, Any]] = []
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        is_mark = bool(re.fullmatch(r"[WwDd]\s*-?\s*\d{1,3}", text))
        if 0 <= conf < (15 if is_mark else 40):
            continue
        x, y, w, h = (
            float(data["left"][i]),
            float(data["top"][i]),
            float(data["width"][i]),
            float(data["height"][i]),
        )
        box = (x, y, x + w, y + h)
        confidence = max(0.0, min(1.0, conf / 100.0)) if conf >= 0 else 0.5
        lines.append(
            {
                "text": text,
                "bbox": box,
                "bounding_box": box,
                "confidence": confidence,
            }
        )
    return lines


def make_shadow_ocr_engine() -> DrawingOCREngine:
    """OCR engine for the shadow provider only."""
    return DrawingOCREngine(custom_ocr_func=tesseract_image_lines)


def viewport_is_opening_schedule_candidate(viewport: Any, page_text: str = "") -> bool:
    """True only for viewports that look like actual opening schedules."""
    if page_looks_like_bill_or_nrm(page_text):
        return False
    view_type = getattr(viewport, "view_type", None)
    title = str(getattr(viewport, "title", "") or "")
    label = str(getattr(viewport, "label", "") or "")
    view_name = getattr(view_type, "value", str(view_type or "")).lower()
    blob = f"{title} {label} {view_name} {page_text[:800]}"
    if _TITLE_NON_OPENING_SCHEDULE_RE.search(blob):
        return False
    if view_name in {"schedule", "window_schedule", "door_schedule", "opening_schedule"}:
        return bool(_TITLE_OPENING_SCHEDULE_RE.search(blob)) or has_opening_schedule_semantics(
            title=title or label or view_name,
            body_text=page_text,
            mark_hits=len(_OPENING_MARK_RE.findall(page_text)),
            distinct_marks=len({f"{a.upper()}{b}" for a, b in _OPENING_MARK_RE.findall(page_text)}),
        )
    if _TITLE_OPENING_SCHEDULE_RE.search(title) or _TITLE_OPENING_SCHEDULE_RE.search(label):
        return True
    return False


def page_is_opening_schedule_sheet(page_text: str) -> bool:
    if page_looks_like_bill_or_nrm(page_text):
        return False
    return bool(_TITLE_OPENING_SCHEDULE_RE.search(page_text or ""))


def raster_table_looks_like_opening_schedule(table: Mapping[str, Any] | Any) -> bool:
    headers = list(
        getattr(table, "headers", None)
        or (table.get("headers", []) if isinstance(table, Mapping) else [])
    )
    title = str(
        getattr(table, "title", None)
        or (table.get("title") if isinstance(table, Mapping) else "")
        or ""
    )
    rows = list(
        getattr(table, "rows", None)
        or (table.get("rows") if isinstance(table, Mapping) else [])
        or []
    )
    body = " ".join(
        " ".join(str(cell) for cell in (row if isinstance(row, (list, tuple)) else [row]))
        for row in rows
    )
    marks = _OPENING_MARK_RE.findall(f"{title} {' '.join(str(h) for h in headers)} {body}")
    return has_opening_schedule_semantics(
        title=title,
        headers=[str(h) for h in headers],
        body_text=body,
        mark_hits=len(marks),
        distinct_marks=len({f"{a.upper()}{b}" for a, b in marks}),
    )


def unique_ids(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for item in values:
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def derive_family_totals(
    quantities: Sequence[QuantityEvidence],
    *,
    formula_version: str,
) -> tuple[QuantityEvidence, ...]:
    """Deterministic door/window totals from authoritative type counts only."""
    authoritative = [
        item
        for item in quantities
        if (
            not item.abstained
            and item.value is not None
            and item.formula in AUTHORITATIVE_TYPE_FORMULAS
            and item.semantic_key not in FAMILY_TOTAL_KEYS.values()
            and item.metadata.get("count_kind") != "family_aggregate"
            and item.family in FAMILY_TOTAL_KEYS
        )
    ]
    totals: list[QuantityEvidence] = []
    for family, semantic_key in FAMILY_TOTAL_KEYS.items():
        parts = [item for item in authoritative if item.family == family]
        if len(parts) < 2:
            continue
        total = sum(float(item.value) for item in parts)
        source_keys = [item.semantic_key for item in parts]
        totals.append(
            QuantityEvidence(
                quantity_id=stable_contract_id(
                    "qty",
                    {
                        "family": family,
                        "tag": semantic_key,
                        "value": total,
                        "formula": FORMULA_FAMILY_TOTAL,
                        "version": formula_version,
                        "parts": source_keys,
                    },
                ),
                family=family,
                semantic_key=semantic_key,
                value=float(total),
                unit="ea",
                input_entity_ids=unique_ids(
                    eid for item in parts for eid in item.input_entity_ids
                ),
                formula=FORMULA_FAMILY_TOTAL,
                formula_version=formula_version,
                evidence_ids=unique_ids(eid for item in parts for eid in item.evidence_ids),
                authority="schedule_extracted",
                status="provisional",
                confidence=min(float(item.confidence) for item in parts),
                abstained=False,
                reason_codes=(FORMULA_FAMILY_TOTAL,),
                metadata={
                    "count_kind": "family_aggregate",
                    "spatially_reconstructed": False,
                    "source_semantic_keys": source_keys,
                    "source_quantity_ids": [item.quantity_id for item in parts],
                    "source_values": [item.value for item in parts],
                },
            )
        )
    return tuple(totals)
