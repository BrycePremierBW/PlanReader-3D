"""RCP view claims must never bootstrap themselves into finish quantities."""
from types import SimpleNamespace as R
from tools.diag_gpt2_rcp_material_occurrence_gates import (
    scoped_rcp_material_occurrence_gate as gate,
)

def vp(kind="reflected_ceiling_plan",status="resolved",box=(1,2,9,20)):
    return R(view_id="v9",view_type=kind,status=status,bounding_box=box)

def scope(*,complete=False,records=(),reasons=("source_material_viewport_unauthenticated",),status=None):
    from pb_migration_contracts import EvidenceResolutionStatus
    producer_status = status or (
        EvidenceResolutionStatus.CORROBORATED
        if complete else EvidenceResolutionStatus.ABSTAINED
    )
    return R(status=producer_status,scope_complete=complete,
             records=records,reason_codes=reasons)

def test_no_rcp_owner_even_if_material_scope_has_records():
    r=gate(vp("schedule"),scope(complete=True,records=(R(record_id="id",code="FPB"),)))
    assert r["first_unclosed_gate"]=="not_an_rcp_viewport"
    assert r["new_room_material_ownership_claim"] is False

def test_unresolved_rcp_is_not_semantic_authority():
    for status in ("unsupported","ambiguous"):
        r=gate(vp(status=status,box=None),scope())
        assert r["first_unclosed_gate"]=="source_rcp_viewport_unresolved"

def test_derived_rcp_with_incomplete_scope_abstains():
    r=gate(vp(),scope())
    assert r["first_unclosed_gate"]=="producer_source_occurrence_universe_incomplete"
    assert r["producer_reason_codes"]==["source_material_viewport_unauthenticated"]
    assert r["new_metric_quantity_claim"] is False

def test_empty_complete_scope_not_false_positive():
    r=gate(vp(),scope(complete=True))
    assert r["first_unclosed_gate"]=="producer_no_authenticated_occurrences"

def test_producer_records_still_require_real_room_owner():
    r=gate(vp(status="resolved"),scope(complete=True,records=(R(record_id="source-1",code="WFPB",viewport_id="v9"),)))
    assert r["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert r["producer_occurrence_record_ids"]==["source-1"]
    assert r["new_room_material_ownership_claim"] is False
    assert r["new_metric_quantity_claim"] is False


def test_conflicted_or_candidate_source_scope_never_authenticates_stale_occurrences():
    from pb_migration_contracts import EvidenceResolutionStatus
    for status in (
        EvidenceResolutionStatus.CONFLICT,
        EvidenceResolutionStatus.CANDIDATE,
        EvidenceResolutionStatus.ABSTAINED,
    ):
        r=gate(
            vp(),scope(complete=True, records=(R(record_id="stale", code="GRID"),),
                       status=status)
        )
        assert r["first_unclosed_gate"]=="producer_source_occurrence_scope_not_corroborated"
        assert r["producer_occurrence_record_ids"]==["stale"]
        assert r["producer_authenticated_record_ids"]==[]
        assert r["new_room_material_ownership_claim"] is False
        assert r["new_metric_quantity_claim"] is False


def test_producer_enum_corroboration_only_counts_authentic_records():
    from pb_migration_contracts import EvidenceResolutionStatus
    r=gate(
        vp(),
        scope(
            complete=True,
            records=(R(record_id="source-record",code="FPB",viewport_id="v9"),),
            status=EvidenceResolutionStatus.CORROBORATED,
        ),
    )
    assert r["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert r["producer_authenticated_record_ids"]==["source-record"]
    assert r["new_metric_quantity_claim"] is False
    for not_rcp in (vp(kind="schedule"),vp(status="unsupported",box=None)):
        row=gate(not_rcp,scope(complete=True,records=(R(record_id="x",code="FPB"),)))
        assert row["producer_authenticated_record_ids"]==[]


def test_rcp_viewport_must_have_finite_positive_native_bbox():
    from pb_migration_contracts import EvidenceResolutionStatus
    valid_scope=scope(
        complete=True,
        status=EvidenceResolutionStatus.CORROBORATED,
        records=(R(record_id="native-record",code="FPB",viewport_id="v9"),),
    )
    for bad_bbox in (
        None,
        (),
        (0, 0, 0, 20),
        (0, 0, 5, -1),
        (float("nan"), 0, 20, 20),
        (0, float("inf"), 20, 20),
        ("untrusted", 0, 20, 20),
    ):
        row=gate(vp(box=bad_bbox),valid_scope)
        assert row["first_unclosed_gate"]=="source_rcp_viewport_unresolved"
        assert row["producer_authenticated_record_ids"]==[]
        assert row["new_metric_quantity_claim"] is False


def test_rcp_proposed_source_records_never_authenticate_original_view():
    from pb_migration_contracts import EvidenceResolutionStatus
    # Synthetic resolved scopes for isolated cross-view lineage testing;
    # the actual page9 original remains unsupported in production.
    original=R(
        view_id="view_p9_2",view_type="reflected_ceiling_plan",
        status="resolved",bounding_box=(0.0,0.0,120.0,90.0),
    )
    proposed=R(
        view_id="view_p9_5",view_type="reflected_ceiling_plan",
        status="resolved",bounding_box=(150.0,0.0,300.0,90.0),
    )
    proposed_record=R(
        viewport_id="view_p9_5",record_id="proposed-source-occurrence",
        code="FPB",
    )
    producer_scope=scope(
        complete=True,records=(proposed_record,),
        status=EvidenceResolutionStatus.CORROBORATED,
    )
    wrong=gate(original,producer_scope)
    assert wrong["first_unclosed_gate"]=="producer_occurrence_viewport_lineage_mismatch"
    assert wrong["producer_occurrence_record_ids"]==["proposed-source-occurrence"]
    assert wrong["producer_authenticated_record_ids"]==[]
    assert wrong["new_room_material_ownership_claim"] is False
    assert wrong["new_metric_quantity_claim"] is False
    right=gate(proposed,producer_scope)
    assert right["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert right["producer_authenticated_record_ids"]==["proposed-source-occurrence"]


def test_rcp_missing_or_mixed_viewport_provenance_does_not_count_as_authentic():
    trusted=R(record_id="owned",code="FPB",viewport_id="v9")
    mismatched=R(record_id="other",code="FPB",viewport_id="different-view")
    missing=R(record_id="no-view",code="FPB")
    for records in ((trusted,mismatched),(missing,),(trusted,missing)):
        row=gate(vp(),scope(complete=True,records=records))
        assert row["first_unclosed_gate"]=="producer_occurrence_viewport_lineage_mismatch"
        assert row["producer_authenticated_record_ids"]==[]
        assert row["new_metric_quantity_claim"] is False


def test_source_page_ownership_prevents_rcp_occurrence_cross_sheet_attribution():
    from pb_migration_contracts import EvidenceResolutionStatus
    # A resolved RCP exercises the later exact source-page ownership
    # gate. An unproven derived viewport correctly stops earlier.
    viewport=R(
        view_id="view_p9_5", view_type="reflected_ceiling_plan",
        status="resolved", bounding_box=(1,2,9,20), page_number=9,
    )
    wrong_sheet=R(record_id="record-p10",code="FPB",
                  viewport_id="view_p9_5",page_id="10")
    wrong=gate(viewport,scope(
        complete=True, records=(wrong_sheet,),
        status=EvidenceResolutionStatus.CORROBORATED,
    ))
    assert wrong["first_unclosed_gate"]=="producer_occurrence_source_page_mismatch"
    assert wrong["producer_authenticated_record_ids"]==[]
    same_sheet=R(record_id="record-p9",code="FPB",
                 viewport_id="view_p9_5",page_id="9")
    right=gate(viewport,scope(
        complete=True,records=(same_sheet,),
        status=EvidenceResolutionStatus.CORROBORATED,
    ))
    assert right["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert right["producer_authenticated_record_ids"]==["record-p9"]
    assert right["new_metric_quantity_claim"] is False
    missing_page=R(record_id="record-no-page",code="FPB",viewport_id="view_p9_5")
    assert gate(viewport,scope(complete=True,records=(missing_page,)))[
        "producer_authenticated_record_ids"
    ] == []


def test_duplicate_material_occurrence_record_ids_cannot_double_count_source():
    first=R(record_id="source-duplicate",code="FPB",viewport_id="v9")
    repeated=R(record_id="source-duplicate",code="FPB",viewport_id="v9")
    got=gate(vp(),scope(complete=True,records=(first,repeated)))
    assert got["first_unclosed_gate"]=="producer_occurrence_identity_ambiguous"
    assert got["producer_occurrence_record_ids"]==[
        "source-duplicate", "source-duplicate",
    ]
    assert got["producer_authenticated_record_ids"]==[]
    assert got["new_room_material_ownership_claim"] is False
    assert got["new_metric_quantity_claim"] is False

    unique=R(record_id="different",code="FPB",viewport_id="v9")
    right=gate(vp(),scope(complete=True,records=(first,unique)))
    assert right["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert right["producer_authenticated_record_ids"]==[
        "source-duplicate", "different",
    ]


def test_derived_rcp_requires_actual_producer_partition_authority():
    from pb_migration_contracts import EvidenceResolutionStatus
    source=scope(
        complete=True,
        status=EvidenceResolutionStatus.CORROBORATED,
        records=(R(viewport_id="v9", record_id="receipt", code="FPB"),),
    )
    unproven=vp(status="derived")
    assert gate(unproven,source)["first_unclosed_gate"]=="source_rcp_viewport_unresolved"
    assert gate(unproven,source)["producer_authenticated_record_ids"]==[]
    # A complete source-owned title grid is an actual producer gate,
    # not a free-form status flag or an unverified title alone.
    authenticated=R(
        view_id="v9", view_type="reflected_ceiling_plan",
        status="derived", bounding_box=(1,2,9,20),
        boundary_source="title_partition",
        provenance={"partition_mode":"columnar_title_grid","grid_validated":True},
    )
    proven=gate(authenticated,source)
    assert proven["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert proven["producer_authenticated_record_ids"]==["receipt"]
    unauthenticated=R(**{**vars(authenticated),
                        "provenance":{"partition_mode":"columnar_title_grid",
                                      "grid_validated":False}})
    assert gate(unauthenticated,source)["producer_authenticated_record_ids"]==[]


def test_rcp_view_type_enum_matches_producer_string_authority():
    from pb_drawing_evidence_binding import DrawingViewType
    rcp=vp(kind=DrawingViewType.REFLECTED_CEILING_PLAN)
    row=gate(rcp,scope(complete=True,records=(
        R(record_id="source-rcp",viewport_id="v9",code="FPB"),)))
    assert row["source_view_type"]=="reflected_ceiling_plan"
    assert row["first_unclosed_gate"]=="producer_authenticated_occurrences_require_room_owner_before_quantity"
    assert row["new_metric_quantity_claim"] is False


def test_source_scope_complete_must_be_strict_boolean_true():
    from pb_migration_contracts import EvidenceResolutionStatus
    for fake_complete in ("False", "true", 1, object()):
        r=gate(vp(),scope(
            complete=fake_complete,
            status=EvidenceResolutionStatus.CORROBORATED,
            records=(R(viewport_id="v9",record_id="source",code="FPB"),),
        ))
        assert r["first_unclosed_gate"]=="producer_source_occurrence_universe_incomplete"
        assert r["producer_authenticated_record_ids"]==[]
    good=gate(vp(),scope(complete=True, records=(
        R(viewport_id="v9",record_id="source",code="FPB"),)))
    assert good["producer_authenticated_record_ids"]==["source"]


def test_missing_source_occurrence_material_code_remains_unverified():
    for bad in (None, "", "   ", 73):
        record=R(viewport_id="v9",record_id="source",code=bad)
        row=gate(vp(),scope(complete=True,records=(record,)))
        assert row["first_unclosed_gate"]=="producer_occurrence_material_code_missing"
        assert row["producer_authenticated_record_ids"]==[]
        assert row["new_room_material_ownership_claim"] is False
    row=gate(vp(),scope(complete=True,records=(
        R(viewport_id="v9",record_id="source",code="FPB"),)))
    assert row["producer_authenticated_record_ids"]==["source"]
