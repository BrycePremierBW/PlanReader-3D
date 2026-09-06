"""tests/publishing/test_publishing_contract.py — Tests for publishing data contract models and hashing."""
import json
import math
import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_jobhub_publishing_contract import (
    BenchmarkStatusPayload,
    DrawingRevisionPayload,
    ExcludedScopePayload,
    ProjectIdentityPayload,
    PublishingMode,
    PublishingPackagePayload,
    PublishingWarningPayload,
    QuantityLineItemPayload,
)


def test_project_identity_payload_serialization():
    ident = ProjectIdentityPayload(
        job_no="26-017",
        job_name="60-62 School Rd Maroochydore",
        site_address="60-62 School Rd, Maroochydore QLD 4558",
        builder_client="Balleo Pty Ltd",
        estimator="Bryce Curran",
        target_jobhub_job_id=101,
    )
    d = ident.to_dict()
    assert d["job_no"] == "26-017"
    assert d["target_jobhub_job_id"] == 101
    assert json.loads(json.dumps(d)) == d


def test_drawing_revision_payload():
    rev = DrawingRevisionPayload(
        drawing_issue="BA Issue 1",
        drawing_date="2026-06-09",
        sheet_count=36,
        source_files_hash="abcdef123456",
        file_names=["A101.pdf", "A102.pdf"],
    )
    d = rev.to_dict()
    assert d["sheet_count"] == 36
    assert len(d["file_names"]) == 2


def test_quantity_line_item_payload_invariants():
    # Valid item
    item = QuantityLineItemPayload(
        row_id=1,
        section="Internal walls and ceilings",
        location="Level 1",
        substrate="Plasterboard",
        finish_tag="PB01",
        element="Internal Wall",
        unit="m2",
        quantity=145.5,
        rate=22.5,
        total_price=3273.75,
        authority_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        authority_status=AuthorityStatus.FIRM.value,
        confidence=1.0,
    )
    assert item.quantity == 145.5
    assert item.total_price == 3273.75

    # Non-finite quantity rejected
    with pytest.raises(ValueError, match="Quantity must be finite"):
        QuantityLineItemPayload(
            row_id=2,
            section="Internal walls and ceilings",
            location="Level 1",
            substrate="Plasterboard",
            finish_tag="PB01",
            element="Internal Wall",
            unit="m2",
            quantity=math.nan,
            rate=22.5,
            total_price=0.0,
            authority_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            authority_status=AuthorityStatus.FIRM.value,
            confidence=1.0,
        )

    # Non-finite rate rejected
    with pytest.raises(ValueError, match="Rate must be finite"):
        QuantityLineItemPayload(
            row_id=3,
            section="Internal walls and ceilings",
            location="Level 1",
            substrate="Plasterboard",
            finish_tag="PB01",
            element="Internal Wall",
            unit="m2",
            quantity=10.0,
            rate=math.inf,
            total_price=0.0,
            authority_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
            authority_status=AuthorityStatus.FIRM.value,
            confidence=1.0,
        )


def test_publishing_package_payload_hashing():
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
        section="Internal",
        location="Unit 1",
        substrate="Plasterboard",
        finish_tag="PB01",
        element="Wall",
        unit="m2",
        quantity=50.0,
        rate=20.0,
        total_price=1000.0,
        authority_type=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
        authority_status=AuthorityStatus.FIRM.value,
        confidence=1.0,
    )
    pkg = PublishingPackagePayload(
        workspace_id=10,
        mode=PublishingMode.COMMERCIAL.value,
        project_identity=ident,
        drawing_revision=rev,
        quantities=[q1],
    )
    h1 = pkg.compute_payload_hash()
    assert isinstance(h1, str) and len(h1) == 64

    # Hashing is deterministic
    h2 = pkg.compute_payload_hash()
    assert h1 == h2

    # Mutating quantity mutates hash
    q1.quantity = 55.0
    h3 = pkg.compute_payload_hash()
    assert h1 != h3
