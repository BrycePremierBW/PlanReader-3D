"""Source-native finish occurrence first failures never assign room finishes."""
from types import SimpleNamespace as S
from pb_migration_contracts import EvidenceResolutionStatus

from tools.diag_gpt2_floor_finish_occurrence_firstgate import (
    inspect_floor_finish_occurrence_first_gates as inspect,
)


def view(**extra):
    return S(**dict(
        view_id="view_p7_2",view_type="floor_plan",
        status="resolved",bounding_box=(0.,0.,100.,100.),**extra
    ))


def rec(**extra):
    r=dict(
        record_id="receipt-1",source_sha256="sha",page_id="7",
        viewport_id="view_p7_2",code="FT2",source_evidence_id="source-ev",
        definition_record_id="schedule-definition-1",
        source_text_observation_ids=("obs-1",),
        bbox_pdf_pts=(20.,20.,25.,25.)
    )
    r.update(extra)
    return S(**r)


def run(records, **kw):
    return inspect(S(
        records=tuple(records),status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True
    ),view(),sha="sha",page_id="7",**kw)


def test_exact_source_occurrence_is_not_room_finish_attribution():
    row=run((rec(),))
    assert row["first_failure_counts"]=={
        "material_occurrence_authenticated_room_owner_unresolved":1
    }
    assert not row["room_finish_ownership_published"]
    assert not row["floor_finish_quantity_published"]


def test_duplicate_text_receipt_across_two_occurrences_remains_ambiguous():
    row=run((rec(),rec(record_id="receipt-2",definition_record_id="other")))
    assert row["ambiguous_source_text_observation_ids"]==["obs-1"]
    assert row["first_failure_counts"]=={
        "material_occurrence_observation_receipt_ambiguous":2
    }
    assert not row["floor_finish_quantity_published"]


def test_stale_scope_and_native_bbox_are_never_reinterpreted_as_room():
    for edit,reason in (
        ({"source_sha256":"foreign"},"material_occurrence_source_scope_conflict"),
        ({"page_id":"9"},"material_occurrence_source_scope_conflict"),
        ({"viewport_id":"v9"},"material_occurrence_source_scope_conflict"),
        ({"bbox_pdf_pts":(120.,120.,125.,125.)},
         "material_occurrence_outside_source_floor_viewport"),
        ({"bbox_pdf_pts":(float("nan"),0.,3.,4.)},
         "material_occurrence_native_bbox_unavailable"),
        ({"definition_record_id":None},
         "material_occurrence_definition_receipt_unavailable"),
    ):
        row=run((rec(**edit),))
        assert row["first_failure_counts"]=={reason:1}
        assert not row["room_finish_ownership_published"]


def test_unresolved_floor_plan_cannot_promote_source_occurrence():
    row=inspect(S(
        records=(rec(),),status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True
    ), S(
        view_id="view_p7_2",view_type="floor_plan",status="unsupported",
        bounding_box=None,
    ),sha="sha",page_id="7")
    assert row["first_failure_counts"]=={
        "source_floor_plan_viewport_unresolved":1
    }
    assert not row["floor_finish_quantity_published"]


def test_incomplete_material_scope_first_fails_even_with_valid_occurrence():
    for status,complete in (
        (EvidenceResolutionStatus.ABSTAINED,False),
        (EvidenceResolutionStatus.CORROBORATED,False),
    ):
        row=inspect(
            S(records=(rec(),),status=status,scope_complete=complete),
            view(),sha="sha",page_id="7",
        )
        assert row["first_failure_counts"]=={
            "material_occurrence_scope_unresolved":1
        }
        assert not row["room_finish_ownership_published"]
        assert not row["floor_finish_quantity_published"]


def test_gpt2_source_floor_material_viewport_supports_native_enum_values():
    from enum import Enum
    from tools.diag_gpt2_floor_finish_occurrence_firstgate import (
        _source_token,
    )
    class Status(Enum):
        RESOLVED="resolved"
        UNSUPPORTED="unsupported"
    class View(Enum):
        FLOOR="floor_plan"
        RCP="reflected_ceiling_plan"
    assert _source_token(Status.RESOLVED)=="resolved"
    assert _source_token(View.FLOOR)=="floor_plan"
    assert _source_token(13) is None
    source=S(
        records=(rec(),),status=EvidenceResolutionStatus.CORROBORATED,
        scope_complete=True,
    )
    accepted=inspect(source,S(
        view_id="view_p7_2",view_type=View.FLOOR,status=Status.RESOLVED,
        bounding_box=(0.,0.,100.,100.),
    ),sha="sha",page_id="7")
    assert accepted["first_failure_counts"]=={
        "material_occurrence_authenticated_room_owner_unresolved":1
    }
    assert not accepted["room_finish_ownership_published"]
    for kind,status in ((View.RCP,Status.RESOLVED),(View.FLOOR,Status.UNSUPPORTED)):
        invalid=inspect(source,S(
            view_id="view_p7_2",view_type=kind,status=status,
            bounding_box=(0.,0.,100.,100.),
        ),sha="sha",page_id="7")
        assert invalid["first_failure_counts"]=={
            "source_floor_plan_viewport_unresolved":1
        }
        assert not invalid["floor_finish_quantity_published"]
