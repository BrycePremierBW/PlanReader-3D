from __future__ import annotations

from pathlib import Path

import fitz

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor


def _write_text_drawing_pdf(tmp_path: Path, text: str) -> Path:
    pdf_path = tmp_path / "keyword_only_pointing.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72.0
    for line in text.splitlines():
        page.insert_text((72.0, y), line, fontsize=10)
        y += 14.0
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def test_keyword_only_external_key_pointing_does_not_invent_area(tmp_path: Path) -> None:
    """A finish keyword may identify scope, but cannot supply its measured extent.

    The drawing deliberately contains enough figured envelope dimensions for the
    extractor to derive a wall area.  That unrelated wall quantity must not be
    copied into a separate key-pointing item merely because a pointing phrase is
    present.
    """

    drawing_text = "\n".join(
        [
            "GROUND FLOOR PLAN",
            "SCALE 1:100",
            "10,000",
            "8,000",
            "Pointing externally to exposed masonry where indicated.",
            "General architectural notes apply to this drawing and coordinated details.",
            "All figured dimensions shall be checked before construction work proceeds.",
            "Refer to relevant details for materials, workmanship and finish locations.",
        ]
    )
    pdf_path = _write_text_drawing_pdf(tmp_path, drawing_text)

    predictions = GenericPlanReaderExtractor().extract_from_pdf(pdf_path)
    by_tag = {prediction.tag: prediction for prediction in predictions}

    # Proves a source wall-area quantity exists; before the fix the pointing
    # item copied this quantity verbatim despite having no independent extent.
    assert "perimeter_walling" in by_tag
    assert by_tag["perimeter_walling"].quantity > 0

    # Fail closed: keyword-only scope text is not measured quantity evidence.
    assert "external_key_pointing" not in by_tag
