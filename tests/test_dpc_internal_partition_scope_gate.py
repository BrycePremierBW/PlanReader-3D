"""Regression tests for the DPC "all walls" scope gate.

pb_planreader_pdf_extractor only adds an evidenced internal partition's
length to damp_proof_course when the drawing's own DPC note explicitly
extends scope beyond the external perimeter (e.g. "... provided under all
walls on ground floor"). Proves both directions of that gate directly,
using a synthetic drawing with a real internal partition wall-like fill in
its vector geometry -- so these tests exercise the actual gate condition
(present vs absent "all walls" phrasing), not just the geometry detector.
"""
from __future__ import annotations

from pathlib import Path

import fitz

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor

# A 10m x 8m envelope at 20 pt/m, with a 0.2m-thick internal partition
# spanning the full depth at the horizontal midpoint -- deliberately
# simple synthetic geometry, not derived from or matched to any benchmark
# drawing.
_SCALE_PT_PER_M = 20.0
_X0, _Y0 = 100.0, 100.0
_WIDTH_PT, _DEPTH_PT = 200.0, 160.0  # 10m x 8m at 20pt/m
_THICKNESS_PT = 4.0  # 0.2m


def _build_pdf(tmp_path: Path, name: str, dpc_note: str) -> Path:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)

    x1 = _X0 + _WIDTH_PT
    y1 = _Y0 + _DEPTH_PT
    mid_x = _X0 + _WIDTH_PT / 2.0

    # Four perimeter walls, drawn as thin solid black fills.
    page.draw_rect(fitz.Rect(_X0, _Y0, _X0 + _THICKNESS_PT, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(x1 - _THICKNESS_PT, _Y0, x1, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(_X0, _Y0, x1, _Y0 + _THICKNESS_PT), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(_X0, y1 - _THICKNESS_PT, x1, y1), color=None, fill=(0, 0, 0))
    # One internal partition, spanning the full depth at the midpoint.
    page.draw_rect(
        fitz.Rect(mid_x - _THICKNESS_PT / 2.0, _Y0, mid_x + _THICKNESS_PT / 2.0, y1),
        color=None,
        fill=(0, 0, 0),
    )

    page.insert_text(
        (_X0, _Y0 - 20),
        "10,000 x 8,000",
        fontsize=10,
    )
    page.insert_text((_X0, y1 + 20), "GROUND FLOOR PLAN", fontsize=10)
    page.insert_text((_X0, y1 + 40), dpc_note, fontsize=9)

    doc.save(path)
    doc.close()
    return path


def _preds(pdf: Path) -> dict:
    return {p.tag: p for p in GenericPlanReaderExtractor().extract_from_pdf(pdf)}


def test_all_walls_phrase_absent_does_not_add_internal_partition_to_dpc(tmp_path: Path) -> None:
    pdf = _build_pdf(
        tmp_path,
        "dpc_no_all_walls_scope.pdf",
        "DPC to be laid to external walls only, minimum 150mm above ground level.",
    )
    preds = _preds(pdf)
    assert "damp_proof_course" in preds
    dpc = preds["damp_proof_course"]
    # Naive external perimeter only: 2*(10+8) = 36m. If the internal
    # partition (8m) were wrongly added, this would read ~44m instead.
    assert dpc.quantity == 36.0
    assert "internal_partition_length_m" not in (dpc.metadata or {})


def test_all_walls_phrase_present_adds_internal_partition_to_dpc(tmp_path: Path) -> None:
    pdf = _build_pdf(
        tmp_path,
        "dpc_all_walls_scope.pdf",
        "DPC denotes damp proof course to be of approved bituminous felt "
        "provided under all walls on ground floor.",
    )
    preds = _preds(pdf)
    assert "damp_proof_course" in preds
    dpc = preds["damp_proof_course"]
    # External perimeter (36m) + the evidenced internal partition (8m).
    assert dpc.quantity == 44.0
    assert (dpc.metadata or {}).get("internal_partition_length_m") == 8.0


def test_all_walls_phrase_variants_are_recognized(tmp_path: Path) -> None:
    for phrase in (
        "DPC to be laid to all walls on ground floor.",
        "DPC damp proof course beneath all walls.",
    ):
        pdf = _build_pdf(tmp_path, f"dpc_variant_{hash(phrase) & 0xffff}.pdf", phrase)
        preds = _preds(pdf)
        assert preds["damp_proof_course"].quantity == 44.0, phrase


def test_same_page_unrelated_all_walls_phrase_does_not_add_partition(tmp_path: Path) -> None:
    """Regression: a DPC note exists, and a separate, unrelated note on the
    same page happens to say "to all walls" (e.g. about plaster) -- the
    gate must require both signals in the SAME clause, not merely the same
    page, and must stay false here."""
    path = tmp_path / "dpc_unrelated_all_walls_phrase.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)

    x1 = _X0 + _WIDTH_PT
    y1 = _Y0 + _DEPTH_PT
    mid_x = _X0 + _WIDTH_PT / 2.0
    page.draw_rect(fitz.Rect(_X0, _Y0, _X0 + _THICKNESS_PT, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(x1 - _THICKNESS_PT, _Y0, x1, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(_X0, _Y0, x1, _Y0 + _THICKNESS_PT), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(_X0, y1 - _THICKNESS_PT, x1, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(
        fitz.Rect(mid_x - _THICKNESS_PT / 2.0, _Y0, mid_x + _THICKNESS_PT / 2.0, y1),
        color=None, fill=(0, 0, 0),
    )
    page.insert_text((_X0, _Y0 - 20), "10,000 x 8,000", fontsize=10)
    page.insert_text((_X0, y1 + 20), "GROUND FLOOR PLAN", fontsize=10)
    # DPC note with NO scope statement of its own.
    page.insert_text((_X0, y1 + 40), "DPC to be laid to external walls only.", fontsize=9)
    # A genuinely unrelated note, elsewhere on the same page, that happens
    # to contain the "all walls" phrase for a different trade entirely.
    page.insert_text((_X0, y1 + 60), "Plaster finish to be applied to all walls internally.", fontsize=9)
    doc.save(path)
    doc.close()

    preds = _preds(path)
    dpc = preds["damp_proof_course"]
    assert dpc.quantity == 36.0
    assert "internal_partition_length_m" not in (dpc.metadata or {})


def test_newline_only_separated_unrelated_phrase_does_not_add_partition(tmp_path: Path) -> None:
    """Regression: two notes separated ONLY by a newline -- no terminal
    punctuation at all between them, so a period-only split cannot see any
    boundary here -- must still be recognized as two independent notes,
    not merged into one because they happen to share a text block."""
    path = tmp_path / "dpc_newline_only_unrelated.pdf"
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)

    x1 = _X0 + _WIDTH_PT
    y1 = _Y0 + _DEPTH_PT
    mid_x = _X0 + _WIDTH_PT / 2.0
    page.draw_rect(fitz.Rect(_X0, _Y0, _X0 + _THICKNESS_PT, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(x1 - _THICKNESS_PT, _Y0, x1, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(_X0, _Y0, x1, _Y0 + _THICKNESS_PT), color=None, fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(_X0, y1 - _THICKNESS_PT, x1, y1), color=None, fill=(0, 0, 0))
    page.draw_rect(
        fitz.Rect(mid_x - _THICKNESS_PT / 2.0, _Y0, mid_x + _THICKNESS_PT / 2.0, y1),
        color=None, fill=(0, 0, 0),
    )
    page.insert_text((_X0, _Y0 - 20), "10,000 x 8,000", fontsize=10)
    page.insert_text((_X0, y1 + 20), "GROUND FLOOR PLAN", fontsize=10)
    # One text block, two lines, NO period/semicolon anywhere -- only a
    # newline separates them, and the second line starts a genuinely new
    # sentence (capital "P"), not a wrapped continuation of the first.
    page.insert_text(
        (_X0, y1 + 40),
        "DPC to be laid to external walls only\nPlaster finish to all walls internally",
        fontsize=9,
    )
    doc.save(path)
    doc.close()

    preds = _preds(path)
    dpc = preds["damp_proof_course"]
    assert dpc.quantity == 36.0
    assert "internal_partition_length_m" not in (dpc.metadata or {})


def test_semicolon_separated_unrelated_phrase_does_not_add_partition(tmp_path: Path) -> None:
    """Regression: DPC and an unrelated "all walls" phrase separated only
    by a semicolon on the same line must not be conflated."""
    pdf = _build_pdf(
        tmp_path,
        "dpc_semicolon_unrelated.pdf",
        "DPC to external walls only; plaster finish to all walls internally",
    )
    preds = _preds(pdf)
    dpc = preds["damp_proof_course"]
    assert dpc.quantity == 36.0
    assert "internal_partition_length_m" not in (dpc.metadata or {})


def test_wrapped_dpc_note_across_a_hard_line_break_is_still_recognized() -> None:
    """Regression: a genuine DPC note commonly wraps across PDF text lines
    with no terminal punctuation at the wrap point (this is exactly how
    the real Lamu drawing's own note is extracted). Must still be
    recognized as one note, not severed into two meaningless fragments
    that individually lack one of the two required signals."""
    wrapped_note = (
        "3.    DPC denotes damp proof course to be of approved\n"
        "       bitumious felt provided under all walls on ground floor.\n"
        "4.    All walls less than 200mm thick to be reinforced."
    )
    assert GenericPlanReaderExtractor._has_dpc_all_walls_scope(wrapped_note)


def test_cross_page_all_walls_note_does_not_leak_to_different_page(tmp_path: Path) -> None:
    """Regression: page A states DPC scope extends to all walls, but page A
    itself carries no usable building/partition geometry. Page B has the
    real geometry and its own DPC mention, but that page's OWN note says
    nothing about "all walls". The page-A note must not leak into page B's
    DPC computation -- the scope check is page-local, not document-global.
    """
    path = tmp_path / "dpc_cross_page_leakage.pdf"
    doc = fitz.open()

    # Page A: DPC + "all walls" scope note, but no parseable envelope
    # dimensions and no wall-like fills -- contributes no geometry at all.
    page_a = doc.new_page(width=842, height=595)
    page_a.insert_text((100, 100), "GENERAL NOTES", fontsize=10)
    page_a.insert_text(
        (100, 130),
        "DPC denotes damp proof course provided under all walls on ground floor.",
        fontsize=9,
    )

    # Page B: the real building geometry, with its own DPC note that does
    # NOT extend scope to all walls.
    page_b = doc.new_page(width=842, height=595)
    x1 = _X0 + _WIDTH_PT
    y1 = _Y0 + _DEPTH_PT
    mid_x = _X0 + _WIDTH_PT / 2.0
    page_b.draw_rect(fitz.Rect(_X0, _Y0, _X0 + _THICKNESS_PT, y1), color=None, fill=(0, 0, 0))
    page_b.draw_rect(fitz.Rect(x1 - _THICKNESS_PT, _Y0, x1, y1), color=None, fill=(0, 0, 0))
    page_b.draw_rect(fitz.Rect(_X0, _Y0, x1, _Y0 + _THICKNESS_PT), color=None, fill=(0, 0, 0))
    page_b.draw_rect(fitz.Rect(_X0, y1 - _THICKNESS_PT, x1, y1), color=None, fill=(0, 0, 0))
    page_b.draw_rect(
        fitz.Rect(mid_x - _THICKNESS_PT / 2.0, _Y0, mid_x + _THICKNESS_PT / 2.0, y1),
        color=None, fill=(0, 0, 0),
    )
    page_b.insert_text((_X0, _Y0 - 20), "10,000 x 8,000", fontsize=10)
    page_b.insert_text((_X0, y1 + 20), "GROUND FLOOR PLAN", fontsize=10)
    page_b.insert_text((_X0, y1 + 40), "DPC to be laid to external walls only.", fontsize=9)

    doc.save(path)
    doc.close()

    preds = _preds(path)
    assert "damp_proof_course" in preds
    dpc = preds["damp_proof_course"]
    # Must be page B's own external perimeter only (36m) -- page A's "all
    # walls" note must not have leaked in to add the 8m partition.
    assert dpc.quantity == 36.0
    assert "internal_partition_length_m" not in (dpc.metadata or {})
