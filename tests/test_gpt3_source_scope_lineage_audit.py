"""Unsigned source-scope claims never become verified V2 sealing authority."""
from pb_migration_contracts import QuantityEvidence
from test_source_closed_run_export import quantity, trace
from tools.diag_gpt3_source_scope_lineage import audit_source_scope_receipts


def _audit(q, t):
    return audit_source_scope_receipts([q], {q.quantity_id: t})


def test_no_source_scope_metadata_is_unavailable_not_inferred_from_source_sha():
    q=quantity()
    report=_audit(q,trace())
    row=report["quantities"][0]
    assert row["snapshot_id"] is None
    assert row["decision_scope_id"] is None
    assert row["first_failing_gate"]=="SNAPSHOT_SOURCE_OWNERSHIP_INCOMPLETE"
    assert not row["source_signed_scope_verified"]
    assert not report["signed_scope_verification_complete"]


def test_two_matching_unsigned_scope_receipts_do_not_authenticate_new_v1_fingerprint():
    q=quantity(metadata={**quantity().metadata,
        "evidence_snapshot_id":"snapshot-original",
        "decision_scope_id":"scope-room-current"})
    source=trace(metadata={
        "source_snapshot_id":"snapshot-original",
        "decision_scope_id":"scope-room-current"})
    report=_audit(q,source)
    row=report["quantities"][0]
    assert row["receipt_consistency"]=="MATCHING_UNSIGNED_METADATA"
    assert row["snapshot_id"]=="snapshot-original"
    assert row["decision_scope_id"]=="scope-room-current"
    assert row["reason_codes"]==["V1_SCOPE_NOT_SIGNED"]
    assert report["matching_but_unsigned"]==1
    assert report["signed_scope_verification_complete"] is False


def test_disagreeing_real_source_snapshot_receipts_are_reported_as_conflict():
    q=quantity(metadata={**quantity().metadata,
        "source_snapshot_id":"snapshot-old","decision_scope_id":"scope-a"})
    t=trace(metadata={"source_snapshot_id":"snapshot-new","decision_scope_id":"scope-a"})
    row=_audit(q,t)["quantities"][0]
    assert row["snapshot_id"] is None
    assert row["first_failing_gate"]=="SNAPSHOT_RECEIPTS_DISAGREE"
    assert row["receipt_consistency"]=="UNBOUND"


def test_same_source_sha_does_not_override_unowned_decision_scope():
    q=quantity(metadata={**quantity().metadata,
        "source_snapshot_id":"snapshot-a","decision_scope_id":"scope-a"})
    t=trace(metadata={"source_snapshot_id":"snapshot-a","decision_scope_id":"scope-b"})
    row=_audit(q,t)["quantities"][0]
    assert row["decision_scope_id"] is None
    assert "DECISION_SCOPE_RECEIPTS_DISAGREE" in row["reason_codes"]
    assert not row["source_signed_scope_verified"]


def test_conflicting_snapshot_aliases_cannot_implicitly_elect_one_identity():
    q=quantity(metadata={**quantity().metadata,
        "snapshot_id":"snapshot-old","evidence_snapshot_id":"snapshot-new",
        "decision_scope_id":"scope-a"})
    t=trace(metadata={"snapshot_id":"snapshot-new","decision_scope_id":"scope-a"})
    row=_audit(q,t)["quantities"][0]
    assert row["snapshot_id"] is None
    assert "SNAPSHOT_RECEIPT_MALFORMED_OR_CONFLICTING" in row["reason_codes"]


def test_missing_trace_and_disjoint_family_items_report_independent_blockers():
    a=quantity(quantity_id="qa",family="floor_area")
    b=quantity(quantity_id="qb",family="opening_count")
    report=audit_source_scope_receipts([b,a],{"qb":trace()})
    assert [q["quantity_id"] for q in report["quantities"]]==["qa","qb"]
    assert report["quantities"][0]["first_failing_gate"]=="SOURCE_TRACE_MISSING"
    assert report["status"]=="DIAGNOSTIC_UNPUBLISHED"
    assert report["unbound_or_conflicting"]==2


def test_unsigned_snapshot_claim_cannot_override_mismatched_revision():
    q=quantity(metadata={**quantity().metadata,"revision_id":"rev-forged",
        "source_snapshot_id":"snapshot-a","decision_scope_id":"scope-a"})
    t=trace(metadata={"source_snapshot_id":"snapshot-a","decision_scope_id":"scope-a"})
    row=_audit(q,t)["quantities"][0]
    assert "REVISION_RECEIPTS_DISAGREE" in row["reason_codes"]
    assert not row["source_signed_scope_verified"]
