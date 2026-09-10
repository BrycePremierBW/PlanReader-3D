from __future__ import annotations

import ast
import inspect
from pathlib import Path
import shutil

import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import pytest

from pb_shadow_opening_count_eval import EligibleOpeningItem, score_frozen_quantities
from pb_shadow_opening_count_provider import ShadowOpeningCountProvider
from pb_shadow_opening_evidence import (
    assess_opening_schedule_authority,
    group_ocr_tokens_into_lines,
    is_ambiguous_ocr_mark,
    is_work_section_or_nrm_code,
    native_tag_context_allowed,
    raster_table_looks_like_opening_schedule,
    schedule_line_is_authoritative,
    viewport_is_opening_schedule_candidate,
)
import pb_shadow_opening_evidence as evidence_mod


def _draw_table(page: fitz.Page, rows: list[list[str]], *, origin: tuple[float, float] = (40.0, 85.0)) -> None:
    x = [origin[0], origin[0] + 90, origin[0] + 260, origin[0] + 350, origin[0] + 610]
    y0 = origin[1]
    rh = 28
    for ridx, row in enumerate(rows):
        y = y0 + ridx * rh
        page.draw_line(fitz.Point(x[0], y), fitz.Point(x[-1], y))
        for cidx, cell in enumerate(row):
            page.draw_line(fitz.Point(x[cidx], y), fitz.Point(x[cidx], y + rh))
            page.insert_text((x[cidx] + 5, y + 18), cell, fontsize=9)
        page.draw_line(fitz.Point(x[-1], y), fitz.Point(x[-1], y + rh))
    page.draw_line(fitz.Point(x[0], y0 + len(rows) * rh), fitz.Point(x[-1], y0 + len(rows) * rh))


def _answered(bundle):
    return {item.semantic_key: item for item in bundle.quantities if not item.abstained}


def _abstained(bundle):
    return {item.semantic_key: item for item in bundle.quantities if item.abstained}


def _font(size: int = 28) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)


def _raster_page_pdf(
    tmp_path: Path,
    name: str,
    *,
    vector_title: str,
    image_lines: list[str],
    extra_vector: str = "",
    blur: float = 0.0,
    rotate: int = 0,
    image_width: int = 1400,
    font_size: int = 32,
) -> Path:
    img = Image.new("RGB", (image_width, max(220, 80 + len(image_lines) * (font_size + 18))), "white")
    draw = ImageDraw.Draw(img)
    font = _font(font_size)
    y = 16
    for line in image_lines:
        draw.text((16, y), line, fill="black", font=font)
        y += font_size + 14
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor="white")
    png = tmp_path / f"{name}.png"
    img.save(png)

    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 30), vector_title, fontsize=12)
    if extra_vector:
        page.insert_text((40, 48), extra_vector, fontsize=8)
    page.insert_image(fitz.Rect(40, 60, 800, 560), filename=str(png))
    doc.save(path)
    doc.close()
    return path


def test_legacy_drawing_ocr_engine_has_no_tesseract_fallback() -> None:
    from pb_drawing_ocr_evidence_layer import DrawingOCREngine
    from PIL import Image

    engine = DrawingOCREngine()
    assert engine.custom_ocr_func is None
    assert engine.recognize_pil_image(Image.new("RGB", (80, 40), "white")) == []


def test_evidence_module_is_gold_free() -> None:
    source = inspect.getsource(evidence_mod)
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "benchmark_accuracy_engine",
        "public_tender_benchmark",
        "benchmark_runner",
        "holdout_suite",
        "expected_boq",
        "pb_shadow_opening_count_eval",
        "pb_quantity_commercial_adapter",
    )
    assert not [module for module in imported if any(token in module.lower() for token in forbidden)]
    assert "NEW_SELECTIVE" not in source
    assert "expected_quantity" not in source


def test_builders_work_and_nrm_tables_are_not_opening_schedules() -> None:
    bw = assess_opening_schedule_authority(
        title="Builder's Work BW / 12",
        headers=["Item", "Description", "Qty", "Unit", "Rate"],
        body_text="Window W1 2 No. Window W2 3 No. Window W3 1 No.",
        mark_hits=3,
        distinct_marks=3,
    )
    assert bw.accepted is False
    assert "non_opening_schedule_context" in bw.reasons
    nrm = assess_opening_schedule_authority(
        title="NRM classification",
        body_text="D20 EXCAVATING AND FILLING 12 m3",
        mark_hits=1,
        distinct_marks=1,
    )
    assert nrm.accepted is False
    assert is_work_section_or_nrm_code("D20", "D20 EXCAVATING AND FILLING")
    assert is_work_section_or_nrm_code("D10", "D10 demolition")
    assert is_work_section_or_nrm_code("W20", "W20 work section joinery")
    assert not is_work_section_or_nrm_code("D1", "WINDOW SCHEDULE D1 900 x 2100 2 No flush door")


def test_lone_mark_and_quantity_table_without_opening_semantics_are_rejected() -> None:
    lone = assess_opening_schedule_authority(title="GENERAL NOTES", body_text="D20", mark_hits=1)
    assert lone.accepted is False
    qty_only = assess_opening_schedule_authority(
        title="COST SCHEDULE",
        headers=["Item", "Qty"],
        body_text="A 6\nB 4",
        mark_hits=0,
    )
    assert qty_only.accepted is False
    assert not schedule_line_is_authoritative("D20 4", tag="D20", quantity=4.0)
    assert schedule_line_is_authoritative("W1: 1200 x 1500 - 6 No.", tag="W1", quantity=6.0)
    assert not raster_table_looks_like_opening_schedule(
        {"title": "Bill of Quantities", "headers": ["Item", "Qty"], "rows": [["W1", "2"]]}
    )


def test_opening_schedule_without_quantity_column_does_not_invent_counts(tmp_path: Path) -> None:
    path = tmp_path / "no_qty.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "WINDOW SCHEDULE", fontsize=12)
    page.insert_text((40, 80), "Mark    Dimensions         Description", fontsize=10)
    page.insert_text((40, 110), "W1      1200 x 1500 mm    Casement", fontsize=10)
    doc.save(path)
    doc.close()
    bundle = ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path)
    assert "W1" not in _answered(bundle)
    if "W1" in {item.semantic_key for item in bundle.quantities}:
        assert _abstained(bundle)["W1"].value is None


def test_native_tag_context_rejects_notes_titles_details_and_legends() -> None:
    assert native_tag_context_allowed("W1", "GROUND FLOOR PLAN CLASSROOM")
    assert not native_tag_context_allowed("W1", "NOTES: Provide W1 as specified")
    assert not native_tag_context_allowed("W1", "TYPICAL DETAIL W1")
    assert not native_tag_context_allowed("D1", "DETAIL D1")
    assert not native_tag_context_allowed("W1", "DRAWING TITLE W1 WINDOW TYPES")
    assert not native_tag_context_allowed("W1", "LEGEND W1 Steel casement")
    assert not native_tag_context_allowed("D20", "D20 EXCAVATING")
    assert not native_tag_context_allowed("D1", "grid line D 1")


def test_notes_detail_title_and_legend_marks_are_not_counted(tmp_path: Path) -> None:
    path = tmp_path / "false_marks.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=12)
    page.insert_text((40, 80), "NOTES: Provide W1 as specified in the window schedule.", fontsize=10)
    page.insert_text((40, 120), "TYPICAL DETAIL D1", fontsize=10)
    page.insert_text((40, 160), "DRAWING TITLE W1 WINDOW TYPES", fontsize=10)
    page.insert_text((40, 200), "LEGEND W1 Steel casement", fontsize=10)
    doc.save(path)
    doc.close()
    answered = _answered(ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path))
    assert "W1" not in answered
    assert "D1" not in answered


def test_elevation_only_is_supporting_evidence_not_a_type_total(tmp_path: Path) -> None:
    path = tmp_path / "elev_only.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "NORTH ELEVATION", fontsize=12)
    page.insert_text((80, 140), "W1", fontsize=11)
    page.insert_text((220, 140), "W1", fontsize=11)
    page.insert_text((360, 140), "W1", fontsize=11)
    doc.save(path)
    doc.close()
    bundle = ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path)
    assert "W1" not in _answered(bundle)
    if "W1" in _abstained(bundle):
        assert "supporting_view_only" in _abstained(bundle)["W1"].blocking_reasons


def test_schedule_plus_elevation_does_not_sum_across_views(tmp_path: Path) -> None:
    path = tmp_path / "cross_view.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "WINDOW SCHEDULE", fontsize=12)
    _draw_table(
        page,
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "4 No.", "Casement"],
        ],
    )
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "NORTH ELEVATION", fontsize=12)
    page.insert_text((80, 140), "W1", fontsize=11)
    page.insert_text((220, 140), "W1", fontsize=11)
    doc.save(path)
    doc.close()
    answered = _answered(ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path))
    assert answered["W1"].value == 4.0


def test_ocr_ambiguity_does_not_normalize_to_nearest_mark(tmp_path: Path) -> None:
    assert is_ambiguous_ocr_mark("DI")
    assert is_ambiguous_ocr_mark("WI")
    assert is_ambiguous_ocr_mark("WDI")
    assert is_ambiguous_ocr_mark("D7?")
    assert not is_ambiguous_ocr_mark("W1")
    path = tmp_path / "ambig.pdf"
    doc = fitz.open()
    doc.new_page(width=842, height=595)
    doc.save(path)
    doc.close()
    provider = ShadowOpeningCountProvider(
        enable_raster_ocr=False,
        ocr_lines_by_page={
            1: (
                {"text": "WI: 1200 x 1500 - 6 No.", "bbox": [40, 80, 240, 100], "confidence": 0.84},
                {"text": "DI: 900 x 2100 - 3 No.", "bbox": [40, 120, 240, 140], "confidence": 0.84},
            )
        },
    )
    answered = _answered(provider.extract_bundle(path))
    assert "W1" not in answered
    assert "D1" not in answered


def test_work_section_codes_are_not_door_or_window_marks(tmp_path: Path) -> None:
    path = tmp_path / "nrm.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "GROUND FLOOR PLAN", fontsize=12)
    page.insert_text((40, 90), "D20 EXCAVATING AND FILLING", fontsize=11)
    page.insert_text((40, 120), "D10 demolition", fontsize=11)
    page.insert_text((40, 150), "W20 work section", fontsize=11)
    doc.save(path)
    doc.close()
    answered = _answered(ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path))
    assert "D20" not in answered
    assert "D10" not in answered
    assert "W20" not in answered


def test_family_totals_sum_authoritative_type_counts_only(tmp_path: Path) -> None:
    path = tmp_path / "totals.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "DOOR SCHEDULE", fontsize=12)
    _draw_table(
        page,
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["D1", "900 x 2100 mm", "2 No.", "Flush door"],
            ["D2", "1000 x 2100 mm", "3 No.", "Flush door"],
            ["D3", "800 x 2100 mm", "1 No.", "Flush door"],
        ],
    )
    doc.save(path)
    doc.close()
    bundle = ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path)
    answered = _answered(bundle)
    assert answered["D1"].value == 2.0
    assert answered["D2"].value == 3.0
    assert answered["D3"].value == 1.0
    assert answered["door_total"].value == 6.0
    assert answered["door_total"].formula == "sum_of_authoritative_type_counts"
    assert answered["door_total"].metadata["source_semantic_keys"] == ["D1", "D2", "D3"]
    assert set(answered["door_total"].evidence_ids)
    metrics = score_frozen_quantities(
        benchmark_id="demo",
        frozen_quantities=bundle.quantities,
        eligible=(
            EligibleOpeningItem("demo", "I1", "D1", 2.0, "NO", "Door D1", "schedule_extractable"),
        ),
    )
    assert metrics["answered"] == 1
    assert metrics["family_aggregates"] == 1
    assert metrics["extra_valid_type_marks"] == 2
    assert metrics["hallucinations"] == 0
    assert "door_total" not in metrics["hallucinated_keys"]
    assert "steel_casement_windows" not in {item.semantic_key for item in bundle.quantities}


def test_ocr_box_reorder_and_merged_split_cells_do_not_hallucinate() -> None:
    ordered = group_ocr_tokens_into_lines(
        [
            {"text": "W1", "bbox": [10, 10, 40, 24], "confidence": 0.9},
            {"text": "1200", "bbox": [50, 10, 90, 24], "confidence": 0.9},
            {"text": "x", "bbox": [95, 10, 105, 24], "confidence": 0.9},
            {"text": "1500", "bbox": [110, 10, 150, 24], "confidence": 0.9},
            {"text": "6", "bbox": [160, 10, 175, 24], "confidence": 0.9},
            {"text": "No.", "bbox": [180, 10, 210, 24], "confidence": 0.9},
        ]
    )
    reversed_tokens = group_ocr_tokens_into_lines(
        [
            {"text": "No.", "bbox": [180, 10, 210, 24], "confidence": 0.9},
            {"text": "6", "bbox": [160, 10, 175, 24], "confidence": 0.9},
            {"text": "1500", "bbox": [110, 10, 150, 24], "confidence": 0.9},
            {"text": "x", "bbox": [95, 10, 105, 24], "confidence": 0.9},
            {"text": "1200", "bbox": [50, 10, 90, 24], "confidence": 0.9},
            {"text": "W1", "bbox": [10, 10, 40, 24], "confidence": 0.9},
        ]
    )
    assert ordered[0]["text"] == reversed_tokens[0]["text"] == "W1 1200 x 1500 6 No."
    merged = group_ocr_tokens_into_lines(
        [{"text": "W11200x15006No", "bbox": [10, 10, 210, 24], "confidence": 0.4}]
    )
    assert merged[0]["confidence"] == 0.4


def test_repeated_headers_and_irrelevant_adjacent_table(tmp_path: Path) -> None:
    path = tmp_path / "headers.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((40, 35), "WINDOW SCHEDULE", fontsize=12)
    _draw_table(
        page,
        [
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["Mark", "Dimensions", "Quantity", "Description"],
            ["W1", "1200 x 1500 mm", "6 No.", "Casement"],
            ["Item", "Qty", "Rate", "Amount"],
            ["Preliminaries", "1", "-", "-"],
        ],
    )
    doc.save(path)
    doc.close()
    answered = _answered(ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path))
    assert answered["W1"].value == 6.0
    assert "Preliminaries" not in answered


def test_raster_opening_schedule_is_read_and_raster_boq_is_rejected(tmp_path: Path) -> None:
    pytest.importorskip("pytesseract")
    if shutil.which("tesseract") is None:
        pytest.skip("optional Tesseract OCR runtime is not installed")
    opening = _raster_page_pdf(
        tmp_path,
        "raster_opening.pdf",
        vector_title="WINDOW SCHEDULE",
        image_lines=[
            "Mark   Dimensions        Quantity   Description",
            "W3     1200 x 1500 mm    6 No.      Casement",
            "D8     900 x 2100 mm     3 No.      Flush door",
        ],
    )
    boq = _raster_page_pdf(
        tmp_path,
        "raster_boq.pdf",
        vector_title="BILL OF QUANTITIES",
        extra_vector="Builder's Work BW / 12 Item Description Qty Unit Rate",
        image_lines=[
            "Item Description Qty Unit Rate",
            "Window W1 2 No.",
            "Window W2 3 No.",
            "Window W3 1 No.",
        ],
    )
    opening_answered = _answered(ShadowOpeningCountProvider().extract_bundle(opening))
    boq_answered = _answered(ShadowOpeningCountProvider().extract_bundle(boq))
    assert opening_answered["W3"].value == 6.0
    assert opening_answered["W3"].authority == "schedule_extracted"
    assert opening_answered["D8"].value == 3.0
    assert "W1" not in boq_answered
    assert "W2" not in boq_answered
    assert "W3" not in boq_answered
    assert "D8" not in boq_answered


def test_low_dpi_blur_and_rotation_do_not_raise_hallucinations(tmp_path: Path) -> None:
    clean = _raster_page_pdf(
        tmp_path,
        "clean.pdf",
        vector_title="WINDOW SCHEDULE",
        image_lines=["W3  1200 x 1500 mm  6 No.  Casement"],
    )
    blur = _raster_page_pdf(
        tmp_path,
        "blur.pdf",
        vector_title="WINDOW SCHEDULE",
        image_lines=["W3  1200 x 1500 mm  6 No.  Casement"],
        blur=2.4,
    )
    rotated = _raster_page_pdf(
        tmp_path,
        "rot.pdf",
        vector_title="WINDOW SCHEDULE",
        image_lines=["W3  1200 x 1500 mm  6 No.  Casement"],
        rotate=90,
    )
    low = _raster_page_pdf(
        tmp_path,
        "low.pdf",
        vector_title="WINDOW SCHEDULE",
        image_lines=["W3  1200 x 1500 mm  6 No.  Casement"],
        font_size=14,
        image_width=500,
    )
    allowed = {"W3", "window_total", "door_total"}
    clean_answered = _answered(ShadowOpeningCountProvider().extract_bundle(clean))
    assert set(clean_answered) <= allowed
    for pdf in (blur, rotated, low):
        answered = _answered(ShadowOpeningCountProvider(raster_ocr_dpi=72).extract_bundle(pdf))
        invented = set(answered) - allowed
        assert not invented


def test_metamorphic_padding_hatching_and_duplicate_views(tmp_path: Path) -> None:
    def base(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "WINDOW SCHEDULE", fontsize=12)
        page.insert_text((40, 90), "Mark Dimensions Quantity Description", fontsize=9)
        page.insert_text((40, 120), "W1 1200 x 1500 mm 3 No. Casement", fontsize=9)

    def padded(doc: fitz.Document) -> None:
        page = doc.new_page(width=900, height=700)
        page.insert_text((80, 80), "WINDOW SCHEDULE", fontsize=12)
        page.insert_text((80, 140), "Mark Dimensions Quantity Description", fontsize=9)
        page.insert_text((80, 170), "W1 1200 x 1500 mm 3 No. Casement", fontsize=9)

    def hatched(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "WINDOW SCHEDULE", fontsize=12)
        for i in range(8):
            page.draw_line(fitz.Point(500, 40 + i * 12), fitz.Point(780, 80 + i * 12))
        page.insert_text((40, 90), "Mark Dimensions Quantity Description", fontsize=9)
        page.insert_text((40, 120), "W1 1200 x 1500 mm 3 No. Casement", fontsize=9)

    def title_block(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "WINDOW SCHEDULE", fontsize=12)
        page.insert_text((40, 90), "Mark Dimensions Quantity Description", fontsize=9)
        page.insert_text((40, 120), "W1 1200 x 1500 mm 3 No. Casement", fontsize=9)
        page.insert_text((500, 540), "DRAWING TITLE BLOCK REV 2 SHEET 04", fontsize=8)

    def elev(doc: fitz.Document) -> None:
        page = doc.new_page(width=842, height=595)
        page.insert_text((40, 35), "NORTH ELEVATION", fontsize=12)
        page.insert_text((80, 140), "W1", fontsize=11)
        page.insert_text((220, 140), "W1", fontsize=11)

    values = []
    for builders in ([base], [padded], [hatched], [title_block], [base, elev, elev]):
        path = tmp_path / f"{len(values)}.pdf"
        doc = fitz.open()
        for builder in builders:
            builder(doc)
        doc.save(path)
        doc.close()
        answered = _answered(ShadowOpeningCountProvider(enable_raster_ocr=False).extract_bundle(path))
        values.append(answered["W1"].value)
    assert values == [3.0] * 5


def test_schedule_viewport_classifier_rejects_non_opening_viewports() -> None:
    class _VP:
        def __init__(self, view_type: str, label: str) -> None:
            self.view_type = view_type
            self.label = label
            self.title = label
            self.view_id = "v1"

    assert viewport_is_opening_schedule_candidate(_VP("schedule", "WINDOW SCHEDULE"), "W1 6 No")
    assert not viewport_is_opening_schedule_candidate(_VP("schedule", "FINISHES SCHEDULE"), "")
    assert not viewport_is_opening_schedule_candidate(
        _VP("schedule", "BILL OF QUANTITIES"),
        "Item Description Qty Unit Rate",
    )
    assert not viewport_is_opening_schedule_candidate(_VP("legend", "SYMBOL LEGEND"), "W1 casement")
