"""GPT3 cannot silently combine stale and current document source revisions."""
import pytest
from test_source_closed_run_export import quantity, trace, SHA_A, SHA_B
from pb_source_closed_run_export import (
    seal_source_closed_run, combine_source_closed_runs, SourceClosedRunConflictError,
)


def one(qid, entity, *, document="doc-a", revision="rev-a", source=SHA_A):
    q=quantity(
        quantity_id=qid, semantic_key=f"room:{qid}:area",
        input_entity_ids=(entity,), evidence_ids=(f"ev-{qid}",),
        metadata={
            "project_id":"project-a", "document_id":document,
            "source_sha256":source, "revision_id":revision,
        },
    )
    t=trace(
        document_id=document,source_sha256=source,
        revision_id=revision,current_revision_id=revision,
        evidence_ids=(f"ev-{qid}",),canonical_entity_ids=(entity,),
    )
    return q,t


@pytest.mark.parametrize(("rev_two", "sha_two"), [
    ("rev-b", SHA_A),
    ("rev-a", SHA_B),
    ("rev-b", SHA_B),
])
def test_same_document_conflicting_revision_or_hash_never_combines(rev_two,sha_two):
    a,ta=one("qa","room-a")
    b,tb=one("qb","room-b",revision=rev_two,source=sha_two)
    first=seal_source_closed_run([a],project_id="project-a",traces_by_quantity_id={a.quantity_id:ta})
    second=seal_source_closed_run([b],project_id="project-a",traces_by_quantity_id={b.quantity_id:tb})
    with pytest.raises(SourceClosedRunConflictError,match="conflicting sealed source revisions or snapshots"):
        combine_source_closed_runs([first,second])


def test_same_document_mixed_revision_in_one_seal_fails_before_customer_output():
    a,ta=one("qa","room-a")
    b,tb=one("qb","room-b",revision="rev-b")
    with pytest.raises(SourceClosedRunConflictError,match="conflicting sealed source revisions or snapshots"):
        seal_source_closed_run(
            [a,b],project_id="project-a",traces_by_quantity_id={"qa":ta,"qb":tb},
        )


def test_independent_document_revisions_and_source_hashes_are_allowed():
    a,ta=one("qa","room-a")
    b,tb=one("qb","room-b",document="doc-b",revision="rev-b",source=SHA_B)
    result=seal_source_closed_run(
        [a,b],project_id="project-a",traces_by_quantity_id={"qa":ta,"qb":tb},
    )
    assert len(result.quantities)==2
    assert result.source_sha256s==(SHA_A,SHA_B)
    assert result.revision_ids==("rev-a","rev-b")


def test_same_document_same_revision_and_source_multiple_distinct_rooms_allowed():
    a,ta=one("qa","room-a")
    b,tb=one("qb","room-b")
    result=seal_source_closed_run(
        [a,b],project_id="project-a",traces_by_quantity_id={"qa":ta,"qb":tb},
    )
    assert len(result.quantities)==2
    assert result.source_sha256s==(SHA_A,)
    assert result.revision_ids==("rev-a",)
