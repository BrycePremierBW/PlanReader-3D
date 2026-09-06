"""tests/publishing/test_project_identity_publishing_gate.py — Tests for project identity gating in publishing pipeline."""
import pytest

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_jobhub_publishing_contract import (
    BenchmarkStatusPayload,
    DrawingRevisionPayload,
    ProjectIdentityPayload,
    PublishingGateStatus,
    PublishingMode,
    PublishingPackagePayload,
    QuantityLineItemPayload,
    validate_publishing_gate,
)


def _base_package(job_no="26-017", job_name="60-62 School Rd Maroochydore", address="60-62 School Rd, Maroochydore"):
    ident = ProjectIdentityPayload(
        job_no=job_no,
        job_name=job_name,
        site_address=address,
        builder_client="OneLife Property Group",
    )
    rev = DrawingRevisionPayload(
        drawing_issue="BA",
        drawing_date="2026-06-09",
        sheet_count=36,
        source_files_hash="hash123",
    )
    q = QuantityLineItemPayload(
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
        workspace_id=1,
        mode=PublishingMode.COMMERCIAL.value,
        project_identity=ident,
        drawing_revision=rev,
        quantities=[q],
    )
    pkg.payload_hash = pkg.compute_payload_hash()
    return pkg


def test_matching_identity_passes():
    pkg = _base_package()
    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.APPROVED.value
    assert res.is_publishable is True


def test_school_rd_60_62_vs_92_94_conflict_blocked():
    # Address 60-62 but name 92-94
    pkg = _base_package(
        job_no="26-017",
        job_name="92-94 School Rd Maroochydore (ELISE)",
        address="60-62 School Rd, Maroochydore",
    )
    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("Project identity conflict" in b for b in res.blocking_reasons)


def test_lago_project_with_school_rd_address_blocked():
    pkg = _base_package(
        job_no="260617_004",
        job_name="CUBE DEVELOPMENTS - LAGO DD",
        address="60-62 School Rd, Maroochydore",
    )
    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("LAGO project cannot reference School Rd" in b for b in res.blocking_reasons)


def test_benchmark_mismatch_rejection_blocks_publishing():
    pkg = _base_package()
    pkg.benchmark_status = BenchmarkStatusPayload(
        benchmark_id="school_rd_60_62",
        is_compatible=False,
        match_status="wrong_project_source_mismatch",
        tolerance_passed=False,
        summary="92-94 School Rd takeoff rejected against 60-62 architectural drawings",
    )
    pkg.payload_hash = pkg.compute_payload_hash()

    res = validate_publishing_gate(pkg)
    assert res.status == PublishingGateStatus.BLOCKED.value
    assert res.is_publishable is False
    assert any("Benchmark mismatch rejection" in b for b in res.blocking_reasons)
