from __future__ import annotations

import fitz

from pb_raster_page_classifier import is_sparse_raster_ocr_candidate


class _FakePage:
    def __init__(self, *, boxes=(), image_count=None):
        self.rect = fitz.Rect(0, 0, 1000, 700)
        self._boxes = list(boxes)
        self._image_count = len(self._boxes) if image_count is None else image_count

    def get_image_info(self, xrefs=True):
        return [{"bbox": box, "xref": idx + 1} for idx, box in enumerate(self._boxes)]

    def get_images(self, full=True):
        return [object() for _ in range(self._image_count)]


def test_sparse_full_page_scan_is_ocr_candidate() -> None:
    page = _FakePage(boxes=[(0, 0, 1000, 700)])
    assert is_sparse_raster_ocr_candidate(page, "PROJECT TITLE")


def test_sparse_tiled_scan_is_ocr_candidate() -> None:
    page = _FakePage(
        boxes=[
            (0, 0, 500, 350),
            (500, 0, 1000, 350),
            (0, 350, 500, 700),
            (500, 350, 1000, 700),
        ]
    )
    assert is_sparse_raster_ocr_candidate(page, "REV A")


def test_dense_native_text_does_not_enter_raster_fallback() -> None:
    page = _FakePage(boxes=[(0, 0, 1000, 700)])
    assert not is_sparse_raster_ocr_candidate(page, "drawing notes " * 80)


def test_boq_pricing_text_vetoes_even_large_raster() -> None:
    page = _FakePage(boxes=[(0, 0, 1000, 700)])
    assert not is_sparse_raster_ocr_candidate(
        page,
        "BILL OF QUANTITIES  unit rate amount KShs",
    )


def test_tiny_logo_image_is_not_enough() -> None:
    page = _FakePage(boxes=[(10, 10, 80, 50)])
    assert not is_sparse_raster_ocr_candidate(page, "PROJECT")


def test_removing_raster_tiles_removes_candidate_status() -> None:
    four_tiles = _FakePage(
        boxes=[
            (0, 0, 100, 100),
            (120, 0, 220, 100),
            (240, 0, 340, 100),
            (360, 0, 460, 100),
        ]
    )
    three_tiles = _FakePage(
        boxes=[
            (0, 0, 100, 100),
            (120, 0, 220, 100),
            (240, 0, 340, 100),
        ]
    )
    assert is_sparse_raster_ocr_candidate(four_tiles, "")
    assert not is_sparse_raster_ocr_candidate(three_tiles, "")


def test_threshold_mutation_is_monotonic_not_answer_shaped() -> None:
    page = _FakePage(boxes=[(0, 0, 410, 350)])
    assert is_sparse_raster_ocr_candidate(page, "", min_single_image_area_ratio=0.20)
    assert not is_sparse_raster_ocr_candidate(page, "", min_single_image_area_ratio=0.30)
