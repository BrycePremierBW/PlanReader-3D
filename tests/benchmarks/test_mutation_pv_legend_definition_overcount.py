"""Mutation/red-team tests for the PV/P.V drafting-legend overcounting fix.

Root cause: ``pb_raster_schedule_extractor._extract_callouts_from_page``
matched "PV" or "P.V" as a whole word to count permanent-vent callouts on a
facade sheet. Real drawings commonly also carry a once-per-sheet legend
definition in the standard "<abbrev> denotes <meaning>" drafting
convention -- e.g. "P.V denotes permanent vents." or "S.V.P denotes soil
vent pipe" (both forms appear in real tender drawings). That definition
word itself matched the same regex, so every sheet carrying the legend
note added one extra phantom vent, and vent counts are summed across
sheets in ``deduplicate_schedule_rows`` -- one phantom per sheet compounds
across a whole drawing set.

The fix excludes a PV/P.V occurrence only when the immediately following
word (same block/line, next word index) is "denotes" -- a generic
grammatical exclusion, not a benchmark-specific count or page number.

All drawings are synthetic. No development-benchmark quantities, project
names, file names, or expected takeoff outputs are used anywhere here.
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pb_raster_schedule_extractor import GenericScheduleTableExtractor


def _facade_pdf(tmp_path: Path, filename: str, body: str) -> fitz.Document:
    pdf_path = tmp_path / filename
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_text((50, 40), "DRAWING TITLE: WEST ELEVATION", fontsize=12)
    page.insert_text((50, 60), "SCALE 1:50", fontsize=9)
    page.insert_text((50, 100), body, fontsize=9)
    doc.save(str(pdf_path))
    doc.close()
    return fitz.open(str(pdf_path))


def _extract_brick_vents(doc: fitz.Document):
    extractor = GenericScheduleTableExtractor()
    rows = {r.tag: r for r in extractor.extract_from_document(doc)}
    return rows.get("brick_vents")


def test_legend_definition_line_alone_is_not_counted_as_vents(tmp_path: Path):
    # A single "P.V denotes permanent vents." legend note with no real
    # callouts anywhere on the sheet must never produce a brick_vents row.
    doc = _facade_pdf(tmp_path, "legend_only.pdf", "P.V denotes permanent vents.\n")
    result = _extract_brick_vents(doc)
    assert result is None


def test_legend_definition_excluded_from_real_callout_count(tmp_path: Path):
    # Six genuine callouts plus the legend note on the same sheet must
    # count exactly six, not seven.
    doc = _facade_pdf(
        tmp_path,
        "legend_plus_callouts.pdf",
        "PV  PV  PV  PV  PV  PV\nP.V denotes permanent vents.\n",
    )
    result = _extract_brick_vents(doc)
    assert result is not None
    assert result.quantity == 6.0


def test_dot_variant_legend_definition_also_excluded(tmp_path: Path):
    # The dotted "P.V" spelling must be excluded the same way as bare "PV"
    # when it is the definition, not a callout.
    doc = _facade_pdf(
        tmp_path,
        "dotted_legend.pdf",
        "PV  PV  PV\nP.V denotes permanent vents.\n",
    )
    result = _extract_brick_vents(doc)
    assert result is not None
    assert result.quantity == 3.0


def test_similar_abbreviation_legend_convention_does_not_affect_vent_count(tmp_path: Path):
    # A different abbreviation's own "<abbrev> denotes <meaning>" legend
    # line (e.g. for soil vent pipes) must not interact with vent counting
    # at all -- it is a separate word, never matched by the PV pattern.
    doc = _facade_pdf(
        tmp_path,
        "other_legend.pdf",
        "PV  PV  PV\nS.V.P denotes soil vent pipe.\n",
    )
    result = _extract_brick_vents(doc)
    assert result is not None
    assert result.quantity == 3.0


def test_below_threshold_after_exclusion_yields_no_row(tmp_path: Path):
    # One real callout plus the legend note: after excluding the legend,
    # only one candidate remains -- below the >=2 threshold required to
    # emit a row at all, so this sheet must contribute nothing.
    doc = _facade_pdf(
        tmp_path,
        "single_plus_legend.pdf",
        "PV\nP.V denotes permanent vents.\n",
    )
    result = _extract_brick_vents(doc)
    assert result is None


def test_dedupe_sums_corrected_counts_across_sheets_not_inflated_ones(tmp_path: Path):
    # Two facade sheets, each carrying the legend note plus a different
    # number of real callouts. The summed total across sheets must reflect
    # only genuine callouts (5 + 3 = 8), not the legend-inflated one (6 + 4).
    extractor = GenericScheduleTableExtractor()
    doc1 = _facade_pdf(tmp_path, "sheet1.pdf", "PV  PV  PV  PV  PV\nP.V denotes permanent vents.\n")
    doc2 = _facade_pdf(tmp_path, "sheet2.pdf", "PV  PV  PV\nP.V denotes permanent vents.\n")

    rows1 = extractor._extract_callouts_from_page(doc1[0], page_num=1)
    rows2 = extractor._extract_callouts_from_page(doc2[0], page_num=2)
    deduped = extractor.deduplicate_schedule_rows(list(rows1) + list(rows2))

    vent_rows = [r for r in deduped if r.tag == "brick_vents"]
    assert len(vent_rows) == 1
    assert vent_rows[0].quantity == 8.0


def test_word_immediately_before_denotes_but_not_pv_is_unaffected(tmp_path: Path):
    # A sanity check that the exclusion is specific to PV/P.V immediately
    # preceding "denotes" -- an unrelated word before "denotes" must not
    # cause any PV callout elsewhere on the same sheet to be miscounted.
    doc = _facade_pdf(
        tmp_path,
        "unrelated_denotes.pdf",
        "PV  PV  PV\nXYZ denotes something else entirely.\n",
    )
    result = _extract_brick_vents(doc)
    assert result is not None
    assert result.quantity == 3.0
