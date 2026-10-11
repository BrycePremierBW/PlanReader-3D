"""GPT3 provisional evidence may never masquerade as a source-closed quantity."""
import pytest
from test_source_closed_run_export import quantity, trace
from pb_quantity_takeoff_adapter import (
    CommercialMeasurementAuthority,
    MissingCommercialAuthorityError,
    quantity_evidence_to_takeoff_output_row,
    quantity_status_not_publishable,
)
from pb_source_closed_run_export import seal_source_closed_quantity


@pytest.mark.parametrize("status", [
    "raw", "candidate", "partial", "blocked", "abstained",
    "unresolved", "unsupported", "pending", "shadow", "conflict",
    "source_conflict",
])
def test_provisional_source_quantities_cannot_reach_commercial_rows(status):
    q = quantity(status=status)
    source = trace()
    sealed = seal_source_closed_quantity(q, trace=source)
    assert sealed.value == 13.270425  # preserve the evidence; do not invent zero
    assert not sealed.lineage_ok
    assert "quantity_status_not_publishable" in sealed.lineage_reason_codes
    assert quantity_status_not_publishable(status)
    with pytest.raises(MissingCommercialAuthorityError, match="nonpublishable"):
        quantity_evidence_to_takeoff_output_row(
            q, trace=source, authority=CommercialMeasurementAuthority(method="direct_evidence"),
        )


@pytest.mark.parametrize("status", ["firm", "corroborated"])
def test_firm_source_statuses_remain_eligible(status):
    q = quantity(status=status)
    source = trace()
    assert seal_source_closed_quantity(q, trace=source).lineage_ok
    assert not quantity_status_not_publishable(status)
    row = quantity_evidence_to_takeoff_output_row(
        q, trace=source, authority=CommercialMeasurementAuthority(method="direct_evidence"),
    )
    assert row is not None
    assert row["quantity"] == 13.270425
    assert row["quantity_id"] == "qty-1"


def test_real_abstention_keeps_its_missing_numeric_value():
    q = quantity(status="abstained", value=None, abstained=True,
                 blocking_reasons=("not_source_proven",))
    sealed = seal_source_closed_quantity(q, trace=trace())
    assert sealed.abstained and sealed.value is None


@pytest.mark.parametrize(("metadata_override", "reason"), [
    ({"shadow_only": True}, "shadow_only_quantity"),
    ({"commercial_projection_allowed": False}, "commercial_projection_forbidden"),
    ({"shadow_only": True, "commercial_projection_allowed": False}, "shadow_only_quantity"),
])
def test_shadow_and_explicitly_forbidden_source_evidence_cannot_be_sealed_as_valid(
    metadata_override, reason
):
    initial=quantity()
    metadata={**initial.metadata, **metadata_override}
    q=quantity(metadata=metadata)
    sealed=seal_source_closed_quantity(q,trace=trace())
    assert not sealed.abstained and sealed.value==13.270425
    assert not sealed.lineage_ok
    assert reason in sealed.lineage_reason_codes
    with pytest.raises(MissingCommercialAuthorityError):
        quantity_evidence_to_takeoff_output_row(
            q,trace=trace(),
            authority=CommercialMeasurementAuthority(method="direct_evidence"),
        )


def test_explicit_positive_projection_metadata_and_nonshadow_remain_valid():
    q=quantity(metadata={**quantity().metadata,
                         "shadow_only": False, "commercial_projection_allowed": True})
    assert seal_source_closed_quantity(q,trace=trace()).lineage_ok
    row=quantity_evidence_to_takeoff_output_row(
        q,trace=trace(),authority=CommercialMeasurementAuthority(method="direct_evidence")
    )
    assert row and row["quantity_id"]=="qty-1"


@pytest.mark.parametrize("enum_value", [
    __import__("pb_migration_contracts").EvidenceResolutionStatus.RAW,
    __import__("pb_migration_contracts").EvidenceResolutionStatus.CANDIDATE,
    __import__("pb_migration_contracts").EvidenceResolutionStatus.ABSTAINED,
    __import__("pb_migration_contracts").EvidenceResolutionStatus.CONFLICT,
])
def test_provisional_evidence_enum_status_is_never_commercially_firm(enum_value):
    q=quantity(status=enum_value)
    assert quantity_status_not_publishable(enum_value)
    sealed=seal_source_closed_quantity(q,trace=trace())
    assert sealed.lineage_ok is False
    assert "quantity_status_not_publishable" in sealed.lineage_reason_codes
    with pytest.raises(MissingCommercialAuthorityError, match="nonpublishable"):
        quantity_evidence_to_takeoff_output_row(
            q,trace=trace(),
            authority=CommercialMeasurementAuthority(method="direct_evidence"),
        )


def test_corroborated_evidence_enum_remains_eligible():
    from pb_migration_contracts import EvidenceResolutionStatus
    q=quantity(status=EvidenceResolutionStatus.CORROBORATED)
    assert not quantity_status_not_publishable(q.status)
    assert seal_source_closed_quantity(q,trace=trace()).lineage_ok is True



@pytest.mark.parametrize("untrusted_status", [
    "provisional", "review_required", "excluded", "unknown",
    "future_status", "shadow_firm", "firm_pending", "corroborated_but_unresolved",
])
def test_unknown_or_future_statuses_fail_closed_instead_of_self_certifying(untrusted_status):
    q = quantity(status=untrusted_status)
    source = trace()
    assert quantity_status_not_publishable(untrusted_status)
    sealed = seal_source_closed_quantity(q, trace=source)
    assert sealed.lineage_ok is False
    assert "quantity_status_not_publishable" in sealed.lineage_reason_codes
    with pytest.raises(MissingCommercialAuthorityError, match="nonpublishable"):
        quantity_evidence_to_takeoff_output_row(
            q, trace=source,
            authority=CommercialMeasurementAuthority(method="direct_evidence"),
        )


@pytest.mark.parametrize("firm_status", ["firm", "FIRM", "corroborated", "CORROBORATED"])
def test_known_proven_statuses_keep_existing_publication_authority(firm_status):
    q = quantity(status=firm_status)
    source = trace()
    assert not quantity_status_not_publishable(firm_status)
    assert seal_source_closed_quantity(q, trace=source).lineage_ok
    assert quantity_evidence_to_takeoff_output_row(
        q, trace=source,
        authority=CommercialMeasurementAuthority(method="direct_evidence"),
    )["quantity_id"] == "qty-1"
