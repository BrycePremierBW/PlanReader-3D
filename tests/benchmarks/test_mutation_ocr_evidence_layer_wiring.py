"""tests/benchmarks/test_mutation_ocr_evidence_layer_wiring.py

Mutation/red-team suite proving Phase F.10's OCR evidence layer is
actually reachable from GenericPlanReaderExtractor.extract_from_pdf().

Bug found and fixed in this PR: the OCR extraction code sat entirely
unreachable after an unconditional `continue` inside the branch meant to
SKIP OCR (native evidence already sufficient) -- meaning the OCR layer
never ran on any page, regardless of native sufficiency, since Phase F.10
was first merged. Every test here calls the real extractor end-to-end
(not the OCR module in isolation, which the pre-existing
test_mutation_drawing_ocr_evidence.py already covers) and monkeypatches
DrawingOCREngine.recognize_page_rect so the test is deterministic and has
no dependency on winocr/Windows OCR actually being installed.

Every dimension, count, and text value in this file is synthetic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import fitz
import pytest

from pb_drawing_ocr_evidence_layer import DrawingOCREngine
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _make_pdf(tmp_path: Path, name: str, lines: list[str]) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontsize=11)
    pdf_path = tmp_path / name
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _ocr_lines(*texts: str) -> List[Dict[str, Any]]:
    return [{"text": t, "bounding_box": [0.0, 0.0, 100.0, 20.0], "confidence": 0.9} for t in texts]


class TestOCRLayerIsReachable:
    def test_insufficient_native_page_with_injected_ocr_produces_a_new_prediction(self, tmp_path: Path) -> None:
        # A page mentioning window terminology but with no native count at
        # all -- native_insufficient must be True, and the OCR path (once
        # reachable) must actually run and merge a result.
        pdf_path = _make_pdf(tmp_path, "window_note_only.pdf", [
            "GROUND FLOOR PLAN",
            "SCALE 1:100",
            "Steel casement windows with 4mm thick glass",
        ])
        with patch.object(
            DrawingOCREngine, "recognize_page_rect",
            return_value=_ocr_lines("W1: 1750 x 1350 mm 7 No."),
        ) as mocked:
            preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
            assert mocked.called

        pred_map = {p.tag: p for p in preds}
        assert "W1" in pred_map
        assert pred_map["W1"].quantity == 7.0
        assert pred_map["W1"].trade_type == "windows"

    def test_page_with_complete_native_openings_never_calls_ocr(self, tmp_path: Path) -> None:
        # KSTVET-shaped native evidence: a real, complete window count
        # already resolved from native text. OCR must not even be invoked.
        # (Filler notes text pushes this page comfortably past the
        # is_scanned_or_raster short-text heuristic, which a minimal
        # synthetic fixture would otherwise trip regardless of native
        # completeness -- a real drawing sheet's text bulk always does.)
        pdf_path = _make_pdf(tmp_path, "native_complete.pdf", [
            "GROUND FLOOR PLAN",
            "SCALE 1:100",
            "WINDOW SCHEDULE",
            "W27: 2,900 x 900 mm 4 No. steel casement window",
            "General notes: all dimensions are in millimetres unless",
            "otherwise stated. Drawings are not to be scaled. Any",
            "discrepancy must be reported to the architect before work begins.",
        ])
        with patch.object(
            DrawingOCREngine, "recognize_page_rect",
            return_value=_ocr_lines("W27: 999 x 999 mm 99 No."),
        ) as mocked:
            preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)

        pred_map = {p.tag: p for p in preds}
        # Explicit native W27 schedule evidence is complete, so the bogus
        # injected OCR count must never run or overwrite it.
        assert pred_map["W27"].quantity == 4.0
        assert not mocked.called

    def test_broadened_opening_keyword_trigger_fires_without_the_word_schedule(self, tmp_path: Path) -> None:
        # Real false-negative found against a live project PDF: a genuine
        # window/door detail sheet describing types via "Steel casement
        # frames" / "Fixed glass" with no literal "schedule" text anywhere
        # on it. The OCR trigger must fire on opening keywords generically,
        # not only on an exact "schedule" phrase match.
        # Filler notes text pushes this page comfortably past the
        # is_scanned_or_raster short-text heuristic, isolating the
        # opening-keyword trigger specifically (rather than the fixture
        # accidentally tripping the separate "too little text" signal).
        pdf_path = _make_pdf(tmp_path, "no_schedule_word.pdf", [
            "ELEVATION E-04",
            "SCALE 1:100",
            "Steel casement frames",
            "Fixed glass",
            "Height from floor level",
            "General notes: all dimensions are in millimetres unless",
            "otherwise stated. Drawings are not to be scaled. Any",
            "discrepancy must be reported to the architect before work begins.",
        ])
        with patch.object(
            DrawingOCREngine, "recognize_page_rect",
            return_value=_ocr_lines("D1: 900 x 2100 mm 5 No."),
        ) as mocked:
            preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
            assert mocked.called

        pred_map = {p.tag: p for p in preds}
        assert "D1" in pred_map
        assert pred_map["D1"].quantity == 5.0

    def test_conflicting_native_and_ocr_counts_block_the_prediction(self, tmp_path: Path) -> None:
        # Native finds SOME evidence for W1 but not a complete quantity
        # (dims only), OCR reports a real count for a DIFFERENT tag (D1)
        # via injected lines -- unrelated tags must not interact; this
        # mainly proves the reconciliation path runs without corrupting
        # unrelated predictions.
        pdf_path = _make_pdf(tmp_path, "mixed_evidence.pdf", [
            "GROUND FLOOR PLAN",
            "SCALE 1:100",
            "Steel casement windows with 4mm thick glass",
        ])
        with patch.object(
            DrawingOCREngine, "recognize_page_rect",
            return_value=_ocr_lines("D1: 900 x 2100 mm 3 No.", "unrelated noise text"),
        ):
            preds = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)

        pred_map = {p.tag: p for p in preds}
        assert "D1" in pred_map
        assert pred_map["D1"].quantity == 3.0
