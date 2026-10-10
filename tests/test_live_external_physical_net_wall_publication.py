from __future__ import annotations

import inspect
from dataclasses import replace

import pytest
from types import MappingProxyType

from pb_gross_wall_geometry_authority import (
    GrossWallGeometryAuthority,
    GrossWallGeometryRecord,
    GrossWallGeometryResult,
    GrossWallGeometrySelector,
    _AUTHORITY_SEAL as GROSS_AUTHORITY_SEAL,
)
from pb_live_external_physical_net_wall_publication import (
    LIVE_EXTERNAL_PHYSICAL_NET_WALL_RESOLVED,
    LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED,
    compose_live_external_physical_net_wall_publication,
)
from pb_live_gross_wall_geometry_composition import (
    LiveGrossWallGeometryComposition,
    LiveGrossWallTrace,
)
from pb_live_physical_opening_void_composition import (
    LivePhysicalOpeningVoidComposition,
    compose_live_physical_opening_voids,
)
from pb_live_wall_opening_authority_composition import (
    compose_live_wall_opening_authority,
)
from pb_live_whole_wall_role_composition import LiveWholeWallRoleComposition
from pb_migration_contracts import EvidenceResolutionStatus
from pb_source_visibility_authority import SourceVisibilityProducer
from pb_wall_role_authority import WallRoleClassification
from pb_whole_wall_role_authority import (
    WholeWallRoleAuthority,
    WholeWallRoleRecord,
    WholeWallRoleResult,
    WholeWallRoleSelector,
    _AUTHORITY_SEAL as ROLE_AUTHORITY_SEAL,
    _RECORD_SEAL as ROLE_RECORD_SEAL,
)
from tests.test_live_physical_opening_void_composition import _complete_void_pdf


def _chain():
    source = SourceVisibilityProducer(
        producer_method="external-physical-net-wall-publication-test",
        producer_version="1",
    )
    published = source.ingest_native_pdf_bytes(
        document_id="external-physical-net-wall-publication",
        source_bytes=_complete_void_pdf(),
        source_locator="memory://external-physical-net-wall-publication.pdf",
    )
    wall_opening = compose_live_wall_opening_authority(
        source_visibility_producer=source,
        revision_id=published.revision.revision_id,
        page_ids=("1",),
    )
    assert wall_opening.status is EvidenceResolutionStatus.CORROBORATED

    physical_void = compose_live_physical_opening_voids(
        source_visibility_producer=source,
        wall_opening_composition=wall_opening,
    )
    assert physical_void.status is EvidenceResolutionStatus.CORROBORATED
    assert len(physical_void.traces) == 1

    opening_id = physical_void.traces[0].opening_identity_id
    void_selector = physical_void.void_selectors[opening_id]
    void_authority = physical_void.physical_opening_void_authorities[
        void_selector.page_id
    ]
    void_result = void_authority.resolve(void_selector)
    assert void_result.status is EvidenceResolutionStatus.CORROBORATED
    assert void_result.record is not None
    void_record = void_result.record

    wall_id = void_record.wall_local_frame_id
    host_frame_trace = next(
        trace
        for trace in wall_opening.host_frames
        if trace.opening_identity_id == opening_id
    )
    member_wall_candidate_ids = tuple(host_frame_trace.whole_wall_candidate_ids)
    assert member_wall_candidate_ids
    length_m = max(4.0, float(void_record.u1) + 1.0)
    height_m = max(3.0, float(void_record.z1) + 0.5)

    gross_selector = GrossWallGeometrySelector(
        document_id=void_record.document_id,
        revision_id=void_record.revision_id,
        source_sha256=void_record.source_sha256,
        snapshot_id=void_record.snapshot_id,
        page_id=void_record.page_id,
        decision_scope_id=void_record.decision_scope_id,
        physical_wall_id=wall_id,
    )
    gross_record = GrossWallGeometryRecord(
        record_id="gross-external-wall",
        document_id=gross_selector.document_id,
        revision_id=gross_selector.revision_id,
        source_sha256=gross_selector.source_sha256,
        snapshot_id=gross_selector.snapshot_id,
        page_id=gross_selector.page_id,
        decision_scope_id=gross_selector.decision_scope_id,
        physical_wall_id=wall_id,
        wall_local_frame_id=wall_id,
        length_m=length_m,
        height_m=height_m,
        gross_area_m2=length_m * height_m,
        polygon_wkb_hex="01030000",
        member_wall_candidate_ids=member_wall_candidate_ids,
    )
    gross_authority = GrossWallGeometryAuthority(
        {
            gross_selector.key: GrossWallGeometryResult(
                status=EvidenceResolutionStatus.CORROBORATED,
                reason_codes=("test_gross_resolved",),
                record=gross_record,
            )
        },
        _seal=GROSS_AUTHORITY_SEAL,
    )
    gross = LiveGrossWallGeometryComposition(
        revision_id=void_record.revision_id,
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=("test_live_gross_resolved",),
        traces=(
            LiveGrossWallTrace(
                physical_wall_id=wall_id,
                page_id=void_record.page_id,
                decision_scope_id=void_record.decision_scope_id,
                registration_target_page_ids=(),
                registration_record_ids=(),
                height_status="firm",
                height_m=height_m,
                height_reason_codes=(),
                scale_status=EvidenceResolutionStatus.CORROBORATED,
                scale_record_id="scale-1",
                scale_reason_codes=(),
                gross_status=EvidenceResolutionStatus.CORROBORATED,
                gross_record_id=gross_record.record_id,
                gross_reason_codes=("test_gross_resolved",),
            ),
        ),
        physical_wall_candidate_authority=wall_opening.physical_wall_candidate_authority,
        cross_sheet_registration_authority=None,
        physical_scale_authority=None,
        wall_height_authority=None,
        gross_wall_geometry_authority=gross_authority,
        gross_selectors=MappingProxyType({wall_id: gross_selector}),
    )

    role_selector = WholeWallRoleSelector(
        document_id=gross_selector.document_id,
        revision_id=gross_selector.revision_id,
        source_sha256=gross_selector.source_sha256,
        snapshot_id=gross_selector.snapshot_id,
        page_id=gross_selector.page_id,
        decision_scope_id=gross_selector.decision_scope_id,
        physical_wall_id=wall_id,
    )
    role_record = WholeWallRoleRecord(
        record_id="role-external-wall",
        document_id=role_selector.document_id,
        revision_id=role_selector.revision_id,
        source_sha256=role_selector.source_sha256,
        snapshot_id=role_selector.snapshot_id,
        page_id=role_selector.page_id,
        decision_scope_id=role_selector.decision_scope_id,
        physical_wall_id=wall_id,
        gross_geometry_record_id=gross_record.record_id,
        member_wall_candidate_ids=member_wall_candidate_ids,
        member_wall_role_record_ids=("member-role-external-wall",),
        role=WallRoleClassification.EXTERNAL,
        _seal=ROLE_RECORD_SEAL,
    )
    role_authority = WholeWallRoleAuthority(
        {
            role_selector.key: WholeWallRoleResult(
                status=EvidenceResolutionStatus.CORROBORATED,
                reason_codes=("test_role_resolved",),
                record=role_record,
            )
        },
        _seal=ROLE_AUTHORITY_SEAL,
    )
    roles = LiveWholeWallRoleComposition(
        revision_id=void_record.revision_id,
        status=EvidenceResolutionStatus.CORROBORATED,
        reason_codes=("test_live_role_resolved",),
        traces=(),
        whole_wall_role_authority=role_authority,
        role_selectors=MappingProxyType({wall_id: role_selector}),
    )

    return wall_opening, physical_void, gross, roles, void_record, gross_record


def test_physical_external_net_wall_subtracts_authenticated_void_without_trade_rule_tokens() -> None:
    wall_opening, physical_void, gross, roles, void_record, gross_record = _chain()

    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=wall_opening,
        physical_void_composition=physical_void,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )

    expected_void_area = (
        (float(void_record.u1) - float(void_record.u0))
        * (float(void_record.z1) - float(void_record.z0))
    )
    expected_net = round(float(gross_record.gross_area_m2) - expected_void_area, 6)

    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.reason_codes == (LIVE_EXTERNAL_PHYSICAL_NET_WALL_RESOLVED,)
    assert result.quantity_evidence is not None
    assert result.quantity_evidence.semantic_key == "perimeter_walling"
    assert result.quantity_evidence.value == expected_net
    assert result.quantity_evidence.metadata["deduction_policy"] == (
        "physical_geometry_not_trade_finish_policy"
    )
    assert void_record.record_id in result.physical_void_record_ids

    assert len(result.canonical_walls) == 1
    wall = result.canonical_walls[0]
    assert wall.canonical_wall_id == gross_record.physical_wall_id
    assert wall.physical_wall_id == gross_record.physical_wall_id
    assert wall.wall_local_frame_id == gross_record.wall_local_frame_id
    assert wall.role == "external"
    assert wall.length_m == gross_record.length_m
    assert wall.height_m == gross_record.height_m
    assert wall.gross_area_m2 == gross_record.gross_area_m2
    assert wall.net_area_m2 == expected_net
    assert wall.gross_polygon_wkb_hex == gross_record.polygon_wkb_hex
    assert wall.net_polygon_wkb_hex
    assert wall.member_wall_candidate_ids == gross_record.member_wall_candidate_ids
    assert {member.wall_candidate_id for member in wall.plan_members} == set(
        gross_record.member_wall_candidate_ids
    )
    assert all(member.centerline_pts for member in wall.plan_members)
    assert wall.opening_identity_ids == (void_record.opening_identity_id,)
    assert len(wall.opening_voids) == 1
    opening_void = wall.opening_voids[0]
    assert opening_void.opening_identity_id == void_record.opening_identity_id
    assert opening_void.physical_void_record_id == void_record.record_id
    assert opening_void.wall_local_frame_id == wall.canonical_wall_id
    assert opening_void.u0 == void_record.u0
    assert opening_void.u1 == void_record.u1
    assert opening_void.z0 == void_record.z0
    assert opening_void.z1 == void_record.z1
    assert opening_void.width_m == float(void_record.u1) - float(void_record.u0)
    assert opening_void.height_m == float(void_record.z1) - float(void_record.z0)
    assert result.quantity_evidence.metadata["canonical_wall_object_ids"] == (
        wall.canonical_wall_id,
    )


def test_expected_opening_with_missing_void_never_publishes_gross_as_net() -> None:
    wall_opening, physical_void, gross, roles, _void_record, _gross_record = _chain()
    blocked_voids = LivePhysicalOpeningVoidComposition(
        revision_id=physical_void.revision_id,
        status=EvidenceResolutionStatus.ABSTAINED,
        reason_codes=("test_missing_void",),
        traces=(),
        physical_opening_void_authorities=MappingProxyType({}),
        void_selectors=MappingProxyType({}),
    )

    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=wall_opening,
        physical_void_composition=blocked_voids,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )

    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert LIVE_EXTERNAL_PHYSICAL_NET_WALL_VOID_UNRESOLVED in result.reason_codes
    assert result.quantity_evidence is None


def test_physical_publication_has_no_trade_policy_or_quantity_truth_inputs() -> None:
    parameters = set(
        inspect.signature(
            compose_live_external_physical_net_wall_publication
        ).parameters
    )
    forbidden = {
        "target_scope_id",
        "trade_scope_id",
        "deduct",
        "deduction_rule",
        "wall_id",
        "wall_ids",
        "external_wall_ids",
        "gross_area_m2",
        "net_area_m2",
        "opening_area_m2",
        "opening_count",
        "quantity",
    }
    assert not (parameters & forbidden)


@pytest.mark.parametrize("identity", ("", "   "))
def test_source_binding_identity_must_be_complete_for_net_wall(identity):
    wall_opening, physical_void, gross, roles, _void, _wall = _chain()
    altered = replace(wall_opening, opening_bindings=(
        *wall_opening.opening_bindings,
        replace(wall_opening.opening_bindings[0], opening_identity_id=identity),
    ))
    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=altered,
        physical_void_composition=physical_void,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None
    assert result.canonical_walls == ()


@pytest.mark.parametrize("kind", ("duplicate", "blank"))
def test_physical_void_trace_coverage_cannot_silently_drop_members(kind):
    wall_opening, physical_void, gross, roles, _void, _wall = _chain()
    extra = (physical_void.traces[0] if kind == "duplicate" else replace(
        physical_void.traces[0], opening_identity_id=" "
    ))
    altered = replace(physical_void, traces=(*physical_void.traces, extra))
    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=wall_opening,
        physical_void_composition=altered,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None
    assert result.canonical_walls == ()


@pytest.mark.parametrize("field", (
    "document_id", "revision_id", "source_sha256", "snapshot_id",
    "decision_scope_id", "page_ids",
))
def test_foreign_opening_universe_cannot_prove_gross_wall_completion(field):
    wall_opening, physical_void, gross, roles, _void, _wall = _chain()
    page = gross.traces[0].page_id
    original = wall_opening.opening_universe_results[page]
    assert original.record is not None
    value = ("foreign-page",) if field == "page_ids" else "foreign-source"
    forged = replace(original, record=replace(original.record, **{field: value}))
    altered = replace(wall_opening, opening_universe_results=MappingProxyType({
        **wall_opening.opening_universe_results, page: forged,
    }))
    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=altered,
        physical_void_composition=physical_void,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None


@pytest.mark.parametrize("field", (
    "source_decode_complete", "semantic_enumeration_complete",
    "decision_scope_complete",
))
def test_source_universe_verdict_cannot_be_inferred_from_record(field):
    wall_opening, physical_void, gross, roles, _void, _wall = _chain()
    page = gross.traces[0].page_id
    original = wall_opening.opening_universe_results[page]
    altered = replace(wall_opening, opening_universe_results=MappingProxyType({
        **wall_opening.opening_universe_results, page: replace(original, **{field: False}),
    }))
    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=altered,
        physical_void_composition=physical_void,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )
    assert result.status is EvidenceResolutionStatus.ABSTAINED
    assert result.quantity_evidence is None


@pytest.mark.parametrize("field,value", (
    ("record_id", ""),
    ("host_binding_record_id", " "),
    ("opening_universe_record_id", ""),
    ("document_id", "foreign-document"),
    ("revision_id", "foreign-revision"),
    ("source_sha256", "f" * 64),
    ("snapshot_id", "foreign-snapshot"),
    ("page_id", "foreign-page"),
    ("decision_scope_id", "foreign-scope"),
))
def test_source_void_must_retain_exact_host_receipt_and_wall_lineage(field, value):
    from pb_physical_opening_void_authority import (
        PhysicalOpeningVoidAuthority, PhysicalOpeningVoidResult,
        _AUTHORITY_SEAL as VOID_AUTHORITY_SEAL,
    )
    wall_opening, physical_void, gross, roles, original, _wall = _chain()
    selector = physical_void.void_selectors[original.opening_identity_id]
    forged = replace(original, **{field: value})
    authority = PhysicalOpeningVoidAuthority({
        selector.key: PhysicalOpeningVoidResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            reason_codes=("source_void_resolved",), record=forged,
        ),
    }, _seal=VOID_AUTHORITY_SEAL)
    altered = replace(physical_void, physical_opening_void_authorities=MappingProxyType({
        **physical_void.physical_opening_void_authorities, selector.page_id: authority,
    }))
    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=wall_opening,
        physical_void_composition=altered,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None
    assert result.canonical_walls == ()


@pytest.mark.parametrize("field", ("u1", "z1"))
def test_fractional_source_void_overhang_never_reaches_boolean_subtraction(field):
    from pb_physical_opening_void_authority import (
        PhysicalOpeningVoidAuthority, PhysicalOpeningVoidResult,
        _AUTHORITY_SEAL as VOID_AUTHORITY_SEAL,
    )
    wall_opening, physical_void, gross, roles, original, wall = _chain()
    selector = physical_void.void_selectors[original.opening_identity_id]
    limit = float(wall.length_m if field == "u1" else wall.height_m)
    forged = replace(original, **{field: limit + 5e-10})
    authority = PhysicalOpeningVoidAuthority({
        selector.key: PhysicalOpeningVoidResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            reason_codes=("source_void_resolved",), record=forged,
        ),
    }, _seal=VOID_AUTHORITY_SEAL)
    altered = replace(physical_void, physical_opening_void_authorities=MappingProxyType({
        **physical_void.physical_opening_void_authorities, selector.page_id: authority,
    }))
    result = compose_live_external_physical_net_wall_publication(
        wall_opening_composition=wall_opening,
        physical_void_composition=altered,
        gross_wall_composition=gross,
        whole_wall_role_composition=roles,
    )
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None
    assert result.canonical_walls == ()
