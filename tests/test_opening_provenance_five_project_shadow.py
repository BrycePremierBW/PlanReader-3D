"""Five-project opening-provenance shadow audit. Score is not asserted."""
from __future__ import annotations

from pathlib import Path

import pytest

from pb_planreader_pdf_extractor import GenericPlanReaderExtractor

_REPO = Path(__file__).resolve().parents[1]
_SOURCES = _REPO / "benchmarks" / "sources"

_PROJECTS = (
    ("kstvet", "1727358888238-bq-nd-drawing.pdf"),
    ("murera", "1785347143869-bqs-drawings.pdf"),
    ("ghazi", "1739211305954-tender-document-for-construction-of-science-laboratory-at-ghazi-primary-school.pdf"),
    ("umma", "umma-university-hostels-builders-work.pdf"),
    ("lamu", "lamu-ishakani-ecd-classrooms-boq.pdf"),
)


def _summarize(shadow: dict) -> dict:
    resolutions = shadow.get("resolutions") or []
    counts = {"RESOLVED": 0, "AMBIGUOUS": 0, "CONFLICT": 0, "UNBOUND": 0}
    heights = []
    marks = []
    for item in resolutions:
        counts[item.get("status", "UNBOUND")] = counts.get(item.get("status", "UNBOUND"), 0) + 1
        if item.get("height_m") is not None:
            heights.append(item["height_m"])
        if item.get("resolved_type_mark"):
            marks.append(item["resolved_type_mark"])
    return {
        "reason": shadow.get("reason"),
        "status": shadow.get("status"),
        "counts": counts,
        "marks": marks,
        "heights": heights,
        "bound_walls": [item.get("bound_wall_id") for item in resolutions],
    }


@pytest.mark.parametrize("name,filename", _PROJECTS)
def test_five_project_provenance_shadow_is_fail_closed(name: str, filename: str) -> None:
    pdf = _SOURCES / filename
    if not pdf.exists():
        pytest.skip(f"official source PDF not present: {pdf}")
    extractor = GenericPlanReaderExtractor()
    preds = extractor.extract_from_pdf(pdf)
    summary = _summarize(extractor.opening_provenance_shadow)
    assert all(wall is None for wall in summary["bound_walls"])
    assert 1.2 not in summary["heights"]
    assert 2.1 not in summary["heights"]
    assert 2.8 not in summary["heights"]
    pred_tags = {item.tag for item in preds}
    # Provenance must not be the source of new anonymous hosted-span predictions.
    assert not any(str(tag).startswith("hosted-span-") for tag in pred_tags)
    assert extractor.opening_provenance_shadow.get("resolutions") is not None
    if extractor.opening_provenance_shadow.get("reason") == "BLOCKED_ON_VIEWPORT_AUTHORITY":
        census = extractor.hosted_opening_shadow.get("viewport_census") or {}
        assert census.get("authoritative_floor_plan_count") == 0
        assert extractor.opening_provenance_shadow.get("viewport_census") == census
