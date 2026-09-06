"""tests/publishing/test_publishing_gate_draft.py — Tests for draft mode publishing gate."""
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


def _make_draft_package():
    ident = ProjectIdentityPayload(
        job_no="26-017",
        job_name="60-62 School Rd Maroochydore",
        site_address="60-62 School Rd, Maroochydore QLD",
        builder_client="Balleo Pty Ltd",
    )
    rev = DrawingRevisionPayload(
        drawing_issue="BA",
        drawing_date="2026-06-09",
        sheet_count=36,
        source_files_hash="hash123",
    )
    q1 = QuantityLineItemPayload(
        row_id=1,
        section="Internal walls",
        location="Unit 1",
        substrate="Plasterboard",
        finish_tag="PB01",
        element="Internal Wall",
        unit="m2",
        quantity=85.0,
        rate=22.0,
        total_price=1870.0,
        authority_type=MeasurementAuthorityType.PDF_SCALED.value,
        authority_status=AuthorityStatus.PROVISIONAL.value,
        confidence=0.6,
        notes="Scaled from uncalibrated sketch",
    )
    pkg = PublishingPackagePayload(
        workspace_id=1,
        mode=PublishingMode.DRAFT.value,
        project_identity=ident,
        drawing_revision=rev,
        quantities=[q1],
    )
    pkg.payload_hash = pkg.compute_payload_hash()
    return pkg


def test_draft_mode_allows_provisional_with_warnings():
    pkg = _make_draft_package()
    res = validate_publishing_gate(pkg)
    # Draft allows provisional items
    assert res.is_publishable is True
    assert res.status == PublishingGateStatus.REVIEW_REQUIRED.value
    assert len(res.warnings) > 0
    assert any("Draft notice" in w for w in res.warnings)


def test_draft_mode_still_blocks_negative_quantities():
    pkg = _make_draft_package()
    pkg.quantities[0].quantity = -5.0
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("negative quantity" in b for b in res.blocking_reasons)


def test_draft_mode_still_blocks_missing_job_number():
    pkg = _make_draft_package()
    pkg.project_identity.job_no = ""
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
