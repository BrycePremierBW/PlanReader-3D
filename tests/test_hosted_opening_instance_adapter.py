"""HostedOpeningSpan → anonymous OpeningInstance adapter (no WxH binding)."""
from __future__ import annotations

from pb_hosted_opening_geometry import HostedOpeningSpan
from pb_hosted_opening_instance_adapter import (
    hosted_opening_span_id,
    hosted_span_to_opening_instance,
    hosted_spans_to_opening_instances,
)
from pb_opening_deduction_pipeline import (
    GenericOpeningDeductionPipeline,
    OpeningDeductionStatus,
    OpeningInstance,
    WallInstance,
)
from pb_opening_tag_normalization import normalize_opening_tag
from pb_planreader_pdf_extractor import ExtractedPrediction


def _span(**overrides) -> HostedOpeningSpan:
    values = dict(
        page=41,
        host_orientation_deg=0.0,
        jamb_start=(10.0, 20.0),
        jamb_end=(58.0, 20.0),
        span_pt=48.0,
        width_m=1.72,
        wall_thickness_pt=6.0,
        subtype="window_like",
        evidence_flags=("host_wall_band", "aligned_two_face_gap"),
        reason="test hosted span",
    )
    values.update(overrides)
    return HostedOpeningSpan(**values)


def test_span_id_is_anonymous_and_never_a_wd_tag() -> None:
    for subtype in ("window_like", "door_like", "opening_unknown"):
        span_id = hosted_opening_span_id(_span(subtype=subtype))
        assert span_id.startswith("hosted-span-")
        assert normalize_opening_tag(span_id) is None
        assert span_id not in {"W1", "W2", "D1"}


def test_adapter_carries_evidenced_width_and_forces_height_none() -> None:
    inst = hosted_span_to_opening_instance(_span(width_m=1.72, page=41))
    assert inst.opening_id == hosted_opening_span_id(_span(width_m=1.72, page=41))
    assert inst.trade_type == "opening"
    assert inst.width_m == 1.72
    assert inst.height_m is None
    assert inst.quantity == 1.0
    assert inst.bound_wall_id == "perimeter_walling"
    assert inst.source_page == 41
    assert inst.bounding_box == [10.0, 20.0, 58.0, 20.0]
    assert "hosted_opening_span" in inst.notes
    assert "subtype=window_like" in inst.notes
    assert inst.single_area_m2 is None
    assert inst.total_area_m2 is None


def test_adapter_does_not_invent_width_or_default_heights() -> None:
    inst = hosted_span_to_opening_instance(_span(width_m=None, span_pt=48.0))
    assert inst.width_m is None
    assert inst.height_m is None
    assert inst.height_m not in (2.1, 1.2, 2.8)


def test_pipeline_marks_hosted_span_unresolved_and_deducts_zero() -> None:
    wall = WallInstance(wall_id="perimeter_walling", gross_area_m2=87.7)
    hosted = hosted_span_to_opening_instance(_span(width_m=1.72))
    result = GenericOpeningDeductionPipeline().calculate_wall_deductions(wall, [hosted])

    assert result.total_deducted_area_m2 == 0.0
    assert result.net_area_m2 == 87.7
    assert result.applied_openings == []
    assert len(result.unresolved_openings) == 1
    unresolved = result.unresolved_openings[0]
    assert unresolved["opening_id"] == hosted.opening_id
    assert unresolved["height_m"] is None
    assert unresolved["width_m"] == 1.72
    assert unresolved["status"] == OpeningDeductionStatus.UNRESOLVED_MISSING_DIMENSIONS.value


def test_existing_d1_deduction_unchanged_when_hosted_span_present() -> None:
    wall = WallInstance(wall_id="perimeter_walling", gross_area_m2=87.7)
    door = OpeningInstance(
        opening_id="D1",
        trade_type="doors",
        width_m=1.0,
        height_m=2.1,
        quantity=1.0,
        bound_wall_id="perimeter_walling",
    )
    hosted = hosted_span_to_opening_instance(_span(width_m=1.72, subtype="door_like"))
    pipeline = GenericOpeningDeductionPipeline()

    without_hosted = pipeline.calculate_wall_deductions(wall, [door])
    with_hosted = pipeline.calculate_wall_deductions(wall, [door, hosted])

    assert without_hosted.total_deducted_area_m2 == 2.1
    assert with_hosted.total_deducted_area_m2 == 2.1
    assert with_hosted.net_area_m2 == without_hosted.net_area_m2
    assert [item["opening_id"] for item in with_hosted.applied_openings] == ["D1"]
    assert [item["opening_id"] for item in with_hosted.unresolved_openings] == [hosted.opening_id]


def test_propagation_leaves_walling_finishes_and_dpc_quantities_unchanged() -> None:
    wall = WallInstance(wall_id="perimeter_walling", gross_area_m2=87.7)
    hosted = hosted_spans_to_opening_instances([_span(width_m=1.72)])
    pipeline = GenericOpeningDeductionPipeline()
    results = pipeline.deduct_openings_for_all_walls([wall], hosted)

    preds = [
        ExtractedPrediction(
            tag="perimeter_walling",
            trade_type="walls",
            description="Perimeter walling",
            quantity=87.7,
            unit="SM",
            confidence=0.9,
            source_page=41,
        ),
        ExtractedPrediction(
            tag="internal_plaster",
            trade_type="finishes",
            description="Internal plaster",
            quantity=84.336,
            unit="SM",
            confidence=0.9,
            source_page=41,
            metadata={"independent_gross_area_m2": 84.336},
        ),
        ExtractedPrediction(
            tag="internal_paint",
            trade_type="finishes",
            description="Internal paint",
            quantity=84.336,
            unit="SM",
            confidence=0.9,
            source_page=41,
            metadata={"independent_gross_area_m2": 84.336},
        ),
        ExtractedPrediction(
            tag="damp_proof_course",
            trade_type="walls",
            description="DPC",
            quantity=54.5,
            unit="M",
            confidence=0.9,
            source_page=41,
        ),
        ExtractedPrediction(
            tag="D1",
            trade_type="doors",
            description="Door D1",
            quantity=1.0,
            unit="NO",
            confidence=0.9,
            source_page=41,
            dimensions=[1000.0, 2100.0],
        ),
    ]
    updated = {item.tag: item for item in pipeline.propagate_to_predictions(preds, results)}

    assert updated["perimeter_walling"].quantity == 87.7
    assert updated["internal_plaster"].quantity == 84.336
    assert updated["internal_paint"].quantity == 84.336
    assert updated["damp_proof_course"].quantity == 54.5
    assert updated["D1"].quantity == 1.0
    assert updated["D1"].tag == "D1"
    assert "W1" not in updated
    assert "W2" not in updated
    assert updated["perimeter_walling"].metadata["total_deducted_opening_area_m2"] == 0.0
    unresolved_ids = [
        item["opening_id"]
        for item in updated["perimeter_walling"].metadata["unresolved_openings"]
    ]
    assert hosted[0].opening_id in unresolved_ids
