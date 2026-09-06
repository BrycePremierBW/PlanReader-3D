"""tests/publishing/test_publishing_gate_commercial.py — Tests for commercial mode publishing gate."""
import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_jobhub_publishing_contract import (
    DrawingRevisionPayload,
    ProjectIdentityPayload,
    PublishingGateStatus,
    PublishingMode,
    PublishingPackagePayload,
    QuantityLineItemPayload,
    validate_publishing_gate,
)


def _make_valid_commercial_package():
    ident = ProjectIdentityPayload(
        job_no="26-017",
        job_name="60-62 School Rd Maroochydore",
        site_address="60-62 School Rd, Maroochydore QLD 4558",
        builder_client="Balleo Pty Ltd",
    )
    rev = DrawingRevisionPayload(
        drawing_issue="BA",
        drawing_date="2026-06-09",
        sheet_count=36,
        source_files_hash="hash123",
    )
    q = QuantityLineItemPayload(
        row_id=1,
        section="Internal walls",
        location="Unit 1",
        substrate="Plasterboard",
        finish_tag="PB01",
        element="Internal Wall",
        unit="m2",
        quantity=120.0,
        rate=22.0,
        total_price=2640.0,
        authority_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        authority_status=AuthorityStatus.FIRM.value,
        confidence=1.0,
    )
    pkg = PublishingPackagePayload(
        workspace_id=1,
        mode=PublishingMode.COMMERCIAL.value,
        project_identity=ident,
        drawing_revision=rev,
        quantities=[q],
    )
    pkg.payload_hash = pkg.compute_payload_hash()
    return pkg


def test_valid_commercial_package_approved():
    pkg = _make_valid_commercial_package()
    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.APPROVED.value
    assert res.is_publishable is True
    assert len(res.blocking_reasons) == 0


def test_provisional_quantity_blocks_commercial_publish():
    pkg = _make_valid_commercial_package()
    # Mark quantity provisional
    pkg.quantities[0].authority_status = AuthorityStatus.PROVISIONAL.value
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("PROVISIONAL" in b for b in res.blocking_reasons)


def test_unapproved_ai_detected_quantity_blocks_commercial_publish():
    pkg = _make_valid_commercial_package()
    pkg.quantities[0].authority_type = MeasurementAuthorityType.AI_DETECTED.value
    pkg.quantities[0].approved_by = None  # No estimator signoff
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("ai_detected without estimator approval" in b for b in res.blocking_reasons)


def test_approved_ai_detected_quantity_passes_commercial_publish():
    pkg = _make_valid_commercial_package()
    pkg.quantities[0].authority_type = MeasurementAuthorityType.AI_DETECTED.value
    pkg.quantities[0].authority_status = AuthorityStatus.FIRM.value
    pkg.quantities[0].approved_by = "Bryce Curran"
    pkg.quantities[0].approved_at = "2026-06-10T12:00:00Z"
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.APPROVED.value
    assert res.is_publishable is True


def test_negative_quantity_blocks_commercial_publish():
    pkg = _make_valid_commercial_package()
    pkg.quantities[0].quantity = -10.0
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("negative quantity" in b for b in res.blocking_reasons)


def test_empty_project_number_blocks_commercial_publish():
    pkg = _make_valid_commercial_package()
    pkg.project_identity.job_no = ""
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert any("Missing project job number" in b for b in res.blocking_reasons)


def test_toctou_hash_mismatch_blocks_commercial_publish():
    pkg = _make_valid_commercial_package()
    pkg.payload_hash = "stale_hash_from_previous_calculation"

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert any("TOCTOU violation" in b for b in res.blocking_reasons)
