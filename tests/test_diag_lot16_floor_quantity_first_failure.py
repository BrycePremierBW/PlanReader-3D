"""Q70 diagnostic only: report earliest unsupported floor measurement stage."""
from types import SimpleNamespace

from dataclasses import replace

from tools.diag_lot16_room_face_scope import (
    _floor_quantity_diagnostic,
    _floor_quantity_first_failure,
    _has_firm_metric_floor_receipt,
)
from tests.test_live_floor_area_quantity_publication_integrity import (
    _claim_with_canonical_room,
    _source_area,
)


def _floor(**updates):
    props = {
        "physical_floor_surface_identity_resolved": True,
        "physical_floor_surface_id": "physical-floor-1",
        "source_room_face_record_id": "source-face-1",
        "evidence_ids": ("source-face-1",),
        "metric_area_m2": 8.64,
        "metric_area_quantity_id": "qty-room-1",
        "metric_area_authority": "documented_dimension",
        "area_page_pts2": 320.0,
    }
    props.update(updates)
    return SimpleNamespace(**props)


def _room(**updates):
    props = {
        "room_label": "TEST ROOM",
        "room_label_binding_record_id": "room-label-binding-1",
        "room_label_evidence_ids": ("source-label-1",),
    }
    props.update(updates)
    return SimpleNamespace(**props)


def test_area_pdf_points_never_proves_metric_floor() -> None:
    floor = _floor(
        metric_area_m2=None,
        metric_area_quantity_id=None,
        metric_area_authority=None,
        area_page_pts2=50000.0,
    )
    assert _floor_quantity_first_failure(floor, _room(), set()) == (
        "documented_dimension_or_physical_scale_measurement_unavailable"
    )


def test_floor_label_proof_is_required_before_metric_measurement() -> None:
    assert _floor_quantity_first_failure(
        _floor(metric_area_m2=None, metric_area_quantity_id=None, metric_area_authority=None),
        _room(room_label_binding_record_id=None), {"qty-room-1"}
    ) == "authenticated_room_label_ownership_unavailable"


def test_missing_real_quantity_receipt_is_not_treated_as_published() -> None:
    assert _floor_quantity_first_failure(_floor(), _room(), set()) == (
        "metric_floor_area_quantity_evidence_unavailable"
    )


def test_supported_metric_floor_with_real_quantity_is_ready() -> None:
    assert _floor_quantity_first_failure(
        _floor(), _room(), {"qty-room-1"}
    ) == "floor_area_quantity_prerequisites_resolved"


def test_source_face_evidence_precedes_area_measurement() -> None:
    assert _floor_quantity_first_failure(
        _floor(evidence_ids=()), _room(), {"qty-room-1"}
    ) == "source_room_face_evidence_unavailable"


def test_authenticated_metric_floor_need_not_have_room_text_label() -> None:
    assert _floor_quantity_first_failure(
        _floor(metric_area_authority="pdf_scaled"),
        _room(
            room_label=None,
            room_label_binding_record_id=None,
            room_label_evidence_ids=(),
        ),
        {"qty-room-1"},
    ) == "floor_area_quantity_prerequisites_resolved"


def test_diagnostic_will_not_call_arbitrary_authority_source_firm() -> None:
    floor = _floor(metric_area_authority="ai_detected")
    assert _has_firm_metric_floor_receipt(floor) is False
    assert _floor_quantity_first_failure(floor, _room(), {"qty-room-1"}) == (
        "documented_dimension_or_physical_scale_measurement_unavailable"
    )
    for invalid in ("source_authenticated_scale", "model_derived", "provisional", ""):
        assert not _has_firm_metric_floor_receipt(
            _floor(metric_area_authority=invalid)
        )


def test_source_closed_lot16_diagnostic_delegates_to_real_floor_publisher() -> None:
    claim = _claim_with_canonical_room(_source_area())
    result = _floor_quantity_diagnostic(claim)
    assert result["area_quantity_count"] == 1
    assert result["source_closed_floor_quantity_count"] == 1
    assert result["canonical_floor_count"] == 1
    assert result["per_floor"][0]["first_missing_prerequisite"] == (
        "floor_area_quantity_prerequisites_resolved"
    )


def test_raw_firm_quantity_id_does_not_override_foreign_source_sha() -> None:
    authentic = _source_area()
    tampered = replace(
        authentic,
        metadata={
            **dict(authentic.metadata),
            "source_sha256": "b" * 64,
        },
    )
    result = _floor_quantity_diagnostic(_claim_with_canonical_room(tampered))
    assert result["area_quantity_count"] == 1
    assert result["source_closed_floor_quantity_count"] == 0
    assert result["per_floor"][0]["first_missing_prerequisite"] == (
        "metric_floor_area_quantity_evidence_unavailable"
    )


def test_raw_firm_quantity_id_does_not_override_wrong_area_or_units() -> None:
    authentic = _source_area()
    for malformed in (
        replace(authentic, value=9999.0),
        replace(authentic, unit="ft2"),
        replace(authentic, authority="model_derived"),
        replace(authentic, blocking_reasons=("unverified_scale",)),
        replace(authentic, evidence_ids=()),
    ):
        result = _floor_quantity_diagnostic(
            _claim_with_canonical_room(malformed)
        )
        assert result["area_quantity_count"] == 1
        assert result["source_closed_floor_quantity_count"] == 0
        assert result["per_floor"][0]["first_missing_prerequisite"] == (
            "metric_floor_area_quantity_evidence_unavailable"
        )


def test_two_conflicting_original_area_receipts_cannot_be_called_floor_ready() -> None:
    source = _source_area()
    conflict = replace(source, value=source.value + 1)
    result = _floor_quantity_diagnostic(
        _claim_with_canonical_room(source, conflict)
    )
    assert result["area_quantity_count"] == 2
    assert result["source_closed_floor_quantity_count"] == 0
    assert result["per_floor"][0]["first_missing_prerequisite"] == (
        "metric_floor_area_quantity_evidence_unavailable"
    )
