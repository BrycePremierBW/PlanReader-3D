"""Sealed-run physical claims must be disjoint, not merely unequal sets."""
import pytest

from pb_source_closed_run_export import (
    SourceClosedRunConflictError, seal_source_closed_run, combine_source_closed_runs,
)
from test_source_closed_run_export import quantity, trace


def source_run(qid, identities, *, family="room_area", semantic="room.area", value=13.0):
    evidence=(f"evidence-{qid}",)
    qty=quantity(
        quantity_id=qid, family=family, semantic_key=semantic,
        value=value, input_entity_ids=identities, evidence_ids=evidence,
    )
    evidence_trace=trace(canonical_entity_ids=identities, evidence_ids=evidence)
    return seal_source_closed_run(
        [qty], project_id="project-a", traces_by_quantity_id={qid:evidence_trace}
    )


@pytest.mark.parametrize("first,second", [
    (("wall-a","wall-b"),("wall-b","wall-c")),
    (("floor-1",),("floor-1","floor-2")),
    (("ceiling-1","ceiling-2"),("ceiling-1",)),
])
def test_partial_source_identity_overlap_fails_cross_family_run_composition(first, second):
    first_run=source_run("qty-first",first)
    second_run=source_run("qty-second",second)
    with pytest.raises(SourceClosedRunConflictError,match="conflicting sealed physical claim"):
        combine_source_closed_runs([first_run,second_run])


def test_partial_overlap_rejected_when_same_sealing_call():
    q1=quantity(quantity_id="qty-a",semantic_key="room.area",value=10.0,
                input_entity_ids=("floor-a","floor-common"),evidence_ids=("ev-a",))
    q2=quantity(quantity_id="qty-b",semantic_key="room.area",value=20.0,
                input_entity_ids=("floor-b","floor-common"),evidence_ids=("ev-b",))
    with pytest.raises(SourceClosedRunConflictError,match="overlapping source identity"):
        seal_source_closed_run(
            [q1,q2],project_id="project-a",
            traces_by_quantity_id={
                "qty-a":trace(canonical_entity_ids=q1.input_entity_ids,evidence_ids=q1.evidence_ids),
                "qty-b":trace(canonical_entity_ids=q2.input_entity_ids,evidence_ids=q2.evidence_ids),
            },
        )


def test_identical_source_set_and_same_value_remains_duplicate_not_distinct():
    a=source_run("qty-a",("room-x","room-y"))
    b=source_run("qty-b",("room-y","room-x"))
    with pytest.raises(SourceClosedRunConflictError,match="duplicate sealed physical claim"):
        combine_source_closed_runs([a,b])


def test_disjoint_identities_with_same_semantic_key_remain_valid():
    a=source_run("qty-a",("room-a","room-b"))
    b=source_run("qty-b",("room-c","room-d"))
    final=combine_source_closed_runs([a,b])
    assert {x.quantity_id for x in final.quantities}=={"qty-a","qty-b"}


def test_same_object_may_have_distinct_quantity_families_and_semantics():
    a=source_run("qty-a",("room-a",),family="floor_area")
    b=source_run("qty-b",("room-a",),family="ceiling_area")
    final=combine_source_closed_runs([a,b])
    assert len(final.quantities)==2


def test_source_overlapping_abstention_does_not_create_false_commercial_duplicate():
    from pb_migration_contracts import QuantityEvidence
    a=source_run("qty-firm",("floor-a",))
    blocked=quantity(
        quantity_id="qty-abstained", semantic_key="room.area",
        input_entity_ids=("floor-a",), evidence_ids=("ev-blocked",),
        value=None,abstained=True,status="abstained",
        blocking_reasons=("no_source_metric_area",),
    )
    b=seal_source_closed_run([blocked],project_id="project-a",
        traces_by_quantity_id={"qty-abstained":trace(canonical_entity_ids=("floor-a",),
                                                      evidence_ids=("ev-blocked",))})
    final=combine_source_closed_runs([a,b])
    assert len(final.quantities)==2
    assert sum(not q.abstained for q in final.quantities)==1


@pytest.mark.parametrize("bad_id",["", " ", " floor-a", "floor-a "])
def test_malformed_quantity_parent_id_is_not_a_source_closed_identity(bad_id):
    from pb_source_closed_run_export import seal_source_closed_quantity
    q=quantity(quantity_id="qty-malformed", input_entity_ids=(bad_id,))
    source=trace(canonical_entity_ids=(bad_id,))
    result=seal_source_closed_quantity(q,trace=source)
    assert not result.lineage_ok
    assert "quantity_identity_malformed" in result.lineage_reason_codes


@pytest.mark.parametrize("bad_evidence",["", " ", " ev-room-1", "ev-room-1 "])
def test_malformed_source_evidence_receipt_breaks_signed_lineage(bad_evidence):
    from pb_source_closed_run_export import seal_source_closed_quantity
    q=quantity(quantity_id="qty-malformed",evidence_ids=(bad_evidence,))
    source=trace(evidence_ids=(bad_evidence,))
    result=seal_source_closed_quantity(q,trace=source)
    assert not result.lineage_ok
    assert "source_trace_identity_malformed" in result.lineage_reason_codes


def test_good_original_source_ids_remain_sealable_after_malformed_rejection():
    from pb_source_closed_run_export import seal_source_closed_quantity
    q=quantity()
    result=seal_source_closed_quantity(q,trace=trace())
    assert result.lineage_ok
    assert result.lineage_reason_codes==()
