"""Mutation/red-team coverage for corroborated secondary-area support counts."""
from __future__ import annotations

import fitz

from pb_secondary_area_support_evidence import (
    SecondaryAreaSupportEvidence,
    extract_secondary_area_support_evidence_from_page,
    resolve_document_secondary_area_support_evidence,
)


def _reopen(doc: fitz.Document) -> fitz.Document:
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype="pdf")


def _support_page(
    *,
    bay_count: int = 7,
    span_mm: int = 2250,
    lower_bay_count: int | None = None,
    include_upper: bool = True,
    include_lower: bool = True,
    include_zone: bool = True,
    include_support: bool = True,
    support_text: str = "100mm Dia. RHS Steel Poles",
    x_offset: float = 0.0,
    y_offset: float = 0.0,
    scale: float = 1.0,
) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=842 * scale, height=595 * scale)

    def pos(x: float, y: float) -> tuple[float, float]:
        return ((x + x_offset) * scale, (y + y_offset) * scale)

    def put_dims(y: float, count: int) -> None:
        for idx in range(count):
            page.insert_text(
                pos(170 + idx * 58, y),
                f"{span_mm:,}",
                fontsize=8 * scale,
            )

    lower_count = lower_bay_count if lower_bay_count is not None else bay_count
    shared_count = min(bay_count, lower_count)
    chain_center_x = 170 + max(0, shared_count - 1) * 58 / 2 + 12

    if include_upper:
        put_dims(220, bay_count)
    if include_zone:
        page.insert_text(pos(chain_center_x - 25, 245), "VERANDAH", fontsize=10 * scale)
    if include_lower:
        put_dims(270, lower_count)
    if include_support:
        page.insert_text(pos(chain_center_x - 55, 290), support_text, fontsize=8 * scale)
    return _reopen(doc)


def _resolve(doc: fitz.Document):
    evidence = extract_secondary_area_support_evidence_from_page(
        doc[0], source_page=1
    )
    doc.close()
    return evidence


def test_two_corroborating_bay_chains_with_verandah_and_support_spec_resolve() -> None:
    evidence = _resolve(_support_page())
    assert evidence is not None
    assert evidence.zone_type == "verandah"
    assert evidence.support_kind == "pole"
    assert evidence.bay_count == 7
    assert evidence.support_count == 8
    assert evidence.bay_spans_m == (2.25,) * 7
    assert len(evidence.chain_ids) == 2


def test_count_mutation_tracks_bay_count_plus_one_not_a_fixture() -> None:
    evidence = _resolve(_support_page(bay_count=4, span_mm=1800))
    assert evidence is not None
    assert evidence.bay_count == 4
    assert evidence.support_count == 5
    assert evidence.bay_spans_m == (1.8,) * 4


def test_translation_and_scale_do_not_change_resolved_count() -> None:
    translated = _resolve(_support_page(x_offset=45, y_offset=25))
    scaled = _resolve(_support_page(scale=1.35))
    assert translated is not None and translated.support_count == 8
    assert scaled is not None and scaled.support_count == 8


def test_single_dimension_chain_is_insufficient() -> None:
    assert _resolve(_support_page(include_lower=False)) is None


def test_conflicting_corroborating_chain_counts_fail_closed() -> None:
    assert _resolve(_support_page(bay_count=7, lower_bay_count=6)) is None


def test_missing_secondary_area_label_fails_closed() -> None:
    assert _resolve(_support_page(include_zone=False)) is None


def test_missing_support_specification_fails_closed() -> None:
    assert _resolve(_support_page(include_support=False)) is None


def test_general_structural_note_does_not_lend_support_semantics() -> None:
    assert _resolve(
        _support_page(support_text="02. 40mm to columns above ground level.")
    ) is None


def test_plain_support_noun_without_material_or_size_is_insufficient() -> None:
    assert _resolve(_support_page(support_text="COLUMNS")) is None


def test_document_resolution_accepts_repeated_agreement() -> None:
    first = SecondaryAreaSupportEvidence(
        zone_type="verandah",
        support_kind="pole",
        support_count=8,
        bay_count=7,
        bay_spans_m=(2.25,) * 7,
        source_pages=(3,),
        chain_ids=("a", "b"),
        zone_bbox=(0, 0, 1, 1),
        support_bbox=(0, 1, 1, 2),
        zone_text="VERANDAH",
        support_text="100mm RHS Steel Poles",
    )
    second = SecondaryAreaSupportEvidence(
        zone_type="verandah",
        support_kind="column",
        support_count=8,
        bay_count=7,
        bay_spans_m=(2.25,) * 7,
        source_pages=(5,),
        chain_ids=("c", "d"),
        zone_bbox=(0, 0, 1, 1),
        support_bbox=(0, 1, 1, 2),
        zone_text="VERANDAH",
        support_text="100mm steel columns",
    )
    resolved = resolve_document_secondary_area_support_evidence([first, second])
    assert resolved is not None
    assert resolved.support_count == 8
    assert resolved.source_pages == (3, 5)
    assert resolved.chain_ids == ("a", "b", "c", "d")


def test_document_resolution_rejects_conflicting_building_counts() -> None:
    first = SecondaryAreaSupportEvidence(
        zone_type="verandah",
        support_kind="pole",
        support_count=8,
        bay_count=7,
        bay_spans_m=(2.25,) * 7,
        source_pages=(1,),
        chain_ids=("a", "b"),
        zone_bbox=(0, 0, 1, 1),
        support_bbox=(0, 1, 1, 2),
        zone_text="VERANDAH",
        support_text="100mm steel poles",
    )
    second = SecondaryAreaSupportEvidence(
        zone_type="verandah",
        support_kind="pole",
        support_count=6,
        bay_count=5,
        bay_spans_m=(2.0,) * 5,
        source_pages=(2,),
        chain_ids=("c", "d"),
        zone_bbox=(0, 0, 1, 1),
        support_bbox=(0, 1, 1, 2),
        zone_text="VERANDAH",
        support_text="100mm steel poles",
    )
    assert resolve_document_secondary_area_support_evidence([first, second]) is None
