from __future__ import annotations

from dataclasses import replace

from pb_geometry_takeoff_model import AuthorityStatus, MeasurementAuthorityType
from pb_migration_contracts import QuantityEvidence
from pb_wall_gross_area_quantity import (
    build_gross_wall_area_quantity,
    quantity_evidence_fingerprint,
)


def _q(
    *,
    family: str,
    semantic_key: str,
    value: float | None,
    unit: str,
    wall_id: str = "WALL-1",
    authority: str,
    status: str = AuthorityStatus.FIRM.value,
    abstained: bool = False,
    blockers: tuple[str, ...] = (),
    source_sha: str = "a" * 64,
    revision: str = "R1",
    viewport: str = "VP-1",
) -> QuantityEvidence:
    return QuantityEvidence(
        quantity_id=f"qty-{family}-{wall_id}",
        family=family,
        semantic_key=semantic_key,
        value=value,
        unit=unit,
        input_entity_ids=(wall_id,),
        formula="fixture",
        formula_version="test",
        evidence_ids=(f"ev-{family}",),
        authority=authority,
        status=status,
        confidence=0.95,
        abstained=abstained,
        blocking_reasons=blockers,
        metadata={
            "source_sha256": source_sha,
            "revision_id": revision,
            "viewport_id": viewport,
            "page_no": 1,
        },
    )


def _length(**kw) -> QuantityEvidence:
    args = dict(
        family="wall_length",
        semantic_key="wall_length:WALL-1",
        value=4.0,
        unit="m",
        authority=MeasurementAuthorityType.PDF_SCALED.value,
    )
    args.update(kw)
    return _q(**args)


def _height(**kw) -> QuantityEvidence:
    args = dict(
        family="wall_height",
        semantic_key="wall_height:WALL-1",
        value=3.0,
        unit="m",
        authority=MeasurementAuthorityType.DOCUMENTED_DIMENSION.value,
    )
    args.update(kw)
    return _q(**args)


def test_gross_area_requires_firm_matching_dependencies() -> None:
    result = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(),
        wall_height=_height(),
    )
    assert result.abstained is False
    assert result.status == AuthorityStatus.FIRM.value
    assert result.value == 12.0
    assert result.unit == "m2"
    assert result.semantic_key == "wall_gross_area:WALL-1"
    assert len(result.metadata["dependency_fingerprints"]) == 2


def test_abstained_or_nonfirm_dependency_fails_closed() -> None:
    result = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(),
        wall_height=_height(
            value=None,
            status=AuthorityStatus.BLOCKED.value,
            abstained=True,
            blockers=("no_height",),
        ),
    )
    assert result.abstained
    assert result.value is None
    assert "wall_height_abstained" in result.blocking_reasons
    assert "wall_height_not_firm" in result.blocking_reasons


def test_wrong_wall_identity_fails_closed() -> None:
    result = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(),
        wall_height=_height(wall_id="WALL-2"),
    )
    assert result.abstained
    assert "wall_height_identity_mismatch" in result.blocking_reasons


def test_cross_revision_or_viewport_mix_fails_closed() -> None:
    revision_mismatch = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(),
        wall_height=_height(revision="R2"),
    )
    viewport_mismatch = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(),
        wall_height=_height(viewport="VP-2"),
    )
    assert revision_mismatch.abstained
    assert "dependency_revision_mismatch" in revision_mismatch.blocking_reasons
    assert viewport_mismatch.abstained
    assert "dependency_viewport_mismatch" in viewport_mismatch.blocking_reasons


def test_incomplete_provenance_fails_closed() -> None:
    result = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(revision=""),
        wall_height=_height(),
    )
    assert result.abstained
    assert "wall_length_provenance_incomplete" in result.blocking_reasons


def test_untrusted_height_authority_cannot_enter_gross_area() -> None:
    result = build_gross_wall_area_quantity(
        wall_id="WALL-1",
        wall_length=_length(),
        wall_height=_height(authority=MeasurementAuthorityType.PROVISIONAL.value),
    )
    assert result.abstained
    assert "wall_height_authority_not_trusted" in result.blocking_reasons


def test_dependency_fingerprint_changes_when_upstream_measurement_changes() -> None:
    length = _length()
    changed = replace(length, value=4.1)
    assert quantity_evidence_fingerprint(length) != quantity_evidence_fingerprint(changed)

    first = build_gross_wall_area_quantity(
        wall_id="WALL-1", wall_length=length, wall_height=_height()
    )
    second = build_gross_wall_area_quantity(
        wall_id="WALL-1", wall_length=changed, wall_height=_height()
    )
    assert first.quantity_id != second.quantity_id
    assert first.value == 12.0
    assert second.value == 12.3


def test_deterministic_replay() -> None:
    args = dict(wall_id="WALL-1", wall_length=_length(), wall_height=_height())
    first = build_gross_wall_area_quantity(**args)
    replay = build_gross_wall_area_quantity(**args)
    assert first.to_dict() == replay.to_dict()
