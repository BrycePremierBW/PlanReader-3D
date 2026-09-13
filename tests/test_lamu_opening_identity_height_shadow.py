"""Real Lamu page-41 identity/height shadow regression.

Fixture filename identifies the official source drawing for reviewers.
Production code never branches on that name, the page number, or BOQ
quantities. F.07 viewport authority is reused, not modified.
"""
from __future__ import annotations

import os
from pathlib import Path

import fitz
import pytest

from pb_hosted_opening_instance_adapter import authoritative_floor_plan_viewports
from pb_opening_callout_dimension_binder import parse_opening_size_callouts
from pb_opening_provenance_graph import (
    STATUS_UNBOUND,
    collect_opening_provenance_shadow_for_doc,
)
from pb_opening_tag_normalization import find_explicit_opening_tags, normalize_opening_tag
from pb_planreader_pdf_extractor import GenericPlanReaderExtractor
from pb_viewport_segmentation import ViewportBoundarySource, ViewportSegmentationStatus

_REPO = Path(__file__).resolve().parents[1]


def _require_lamu() -> Path:
    sources = Path(os.environ["PLANREADER_SOURCES_DIR"]) if os.environ.get("PLANREADER_SOURCES_DIR") else (_REPO / "benchmarks" / "sources")
    pdf = sources / "lamu-ishakani-ecd-classrooms-boq.pdf"
    if not pdf.exists():
        pytest.skip(f"official source PDF not present: {pdf}")
    return pdf


def _words_inside(page, bbox):
    rows = []
    for word in page.get_text("words") or []:
        x0, y0, x1, y1, text = word[:5]
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
            rows.append((text, (x0, y0, x1, y1)))
    return rows


def test_lamu_resolved_frame_has_no_explicit_opening_identity_or_wxh() -> None:
    doc = fitz.open(str(_require_lamu()))
    page = doc[40]
    plans = authoritative_floor_plan_viewports(page, page_number=41)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.status == ViewportSegmentationStatus.RESOLVED.value
    assert plan.boundary_source == ViewportBoundarySource.VECTOR_FRAME.value
    bbox = tuple(float(value) for value in plan.bounding_box)
    assert bbox == pytest.approx((200.5, 110.1, 654.1, 342.6), abs=2.0)

    words = _words_inside(page, bbox)
    texts = [text for text, _ in words]
    assert "VERANDA" in texts or "VERANDA" in " ".join(texts).upper()
    assert any(text == "1700" for text in texts)
    assert any(text == "1200" for text in texts)
    assert all(normalize_opening_tag(text) is None for text in texts)
    assert all(find_explicit_opening_tags(text) == [] for text in texts)
    assert all(parse_opening_size_callouts(text) == [] for text in texts)
    joined = " ".join(texts)
    assert parse_opening_size_callouts(joined) == []
    assert find_explicit_opening_tags(joined) == []
    doc.close()


def test_lamu_page41_hosted_spans_remain_identity_and_height_unbound() -> None:
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(_require_lamu())
    hosted = extractor.hosted_opening_shadow
    shadow = extractor.opening_provenance_shadow

    assert hosted.get("status") == "found"
    evidence = hosted.get("evidence") or []
    assert len(evidence) == 11
    resolutions = shadow.get("resolutions") or []
    assert len(resolutions) == 11

    extra = [
        node
        for node in (shadow.get("nodes") or [])
        if node.get("evidence_type") != "physical_hosted_span"
    ]
    assert extra == []
    assert shadow.get("edges") == []

    for item in resolutions:
        assert item.get("status") == STATUS_UNBOUND
        assert item.get("resolved_type_mark") is None
        assert item.get("height_m") is None
        assert item.get("bound_wall_id") is None
        assert item.get("schedule_row") is None
        assert "no contained tag, leader, or unique local identity" in " ".join(
            item.get("reasons") or []
        )

    for row in evidence:
        assert str(row.get("span_id", "")).startswith("hosted-span-")
        assert row.get("width_m") is None

    pred_tags = [str(item.tag) for item in preds]
    assert not any(tag.startswith("hosted-span-") for tag in pred_tags)
    for pred in preds:
        notes = str(getattr(pred, "notes", "") or "")
        metadata = getattr(pred, "metadata", None) or {}
        assert "hosted_opening_span" not in notes
        assert metadata.get("source") != "hosted_opening_shadow"


def test_lamu_identity_height_shadow_does_not_use_commercial_schedule_harvest() -> None:
    doc = fitz.open(str(_require_lamu()))
    extractor = GenericPlanReaderExtractor()
    extractor.extract_from_pdf(_require_lamu())
    shadow = collect_opening_provenance_shadow_for_doc(
        doc, [40], extractor.hosted_opening_shadow
    )
    assert all(
        node.get("evidence_type") != "schedule_row"
        for node in (shadow.get("nodes") or [])
    )
    assert all(item.get("height_m") is None for item in (shadow.get("resolutions") or []))
    doc.close()
