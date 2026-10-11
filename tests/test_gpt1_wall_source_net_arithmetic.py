"""GPT1 Q03 wall quantity arithmetic must remain source/physical-wall owned."""
from __future__ import annotations

from dataclasses import replace

import pytest

from pb_live_external_net_wall_publication import (
    LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH,
    LIVE_EXTERNAL_NET_WALL_NET_UNRESOLVED,
    compose_live_external_net_wall_publication,
)
from pb_migration_contracts import EvidenceResolutionStatus
from pb_net_wall_boolean_union_authority import (
    NetWallBooleanUnionAuthority,
    NetWallBooleanUnionResult,
    _AUTHORITY_SEAL,
)
from tests.test_live_external_net_wall_publication import TARGET, _chain


def output(gross, net, role):
    return compose_live_external_net_wall_publication(
        gross_wall_composition=gross,
        net_wall_composition=net,
        whole_wall_role_composition=role,
        target_scope_id=TARGET,
    )


def mutate_net_record(net, **changes):
    selector = net.net_wall_selectors[("wall-A", TARGET)]
    original = net.net_wall_authorities["1"].resolve(selector)
    assert original.record is not None
    forged = replace(original.record, **changes)
    mapping = dict(net.net_wall_authorities)
    mapping["1"] = NetWallBooleanUnionAuthority({
        selector.key: NetWallBooleanUnionResult(
            status=EvidenceResolutionStatus.CORROBORATED,
            reason_codes=("original-source-replay",),
            record=forged,
        ),
    }, _seal=_AUTHORITY_SEAL)
    return replace(net, net_wall_authorities=mapping)


def test_original_wall_gross_15_less_real_void_2_5_is_net_12_5():
    gross, net, roles = _chain()
    result = output(gross, net, roles)
    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.quantity_evidence is not None
    assert result.quantity_evidence.value == 12.5


@pytest.mark.parametrize("page_id", ["other-page", "", "99"])
def test_gross_wall_trace_cannot_be_replayed_at_foreign_page(page_id):
    gross, net, roles = _chain()
    candidate = replace(gross.traces[0], page_id=page_id)
    result = output(replace(gross, traces=(candidate, *gross.traces[1:])), net, roles)
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH in result.reason_codes
    assert result.quantity_evidence is None


def test_gross_wall_trace_cannot_borrow_another_decision_scope():
    gross, net, roles = _chain()
    candidate = replace(gross.traces[0], decision_scope_id="foreign-decision-scope")
    result = output(replace(gross, traces=(candidate, *gross.traces[1:])), net, roles)
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None


def test_gross_wall_trace_cannot_replay_foreign_gross_record_id():
    gross, net, roles = _chain()
    candidate = replace(gross.traces[0], gross_record_id="gross-from-another-wall")
    result = output(replace(gross, traces=(candidate, *gross.traces[1:])), net, roles)
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert result.quantity_evidence is None


@pytest.mark.parametrize("bad_net", [True, False, 16.0])
def test_net_wall_does_not_publish_boolean_or_greater_than_gross(bad_net):
    gross, net, roles = _chain(net_a=bad_net)
    result = output(gross, net, roles)
    assert result.quantity_evidence is None
    assert result.status in (EvidenceResolutionStatus.CONFLICT, EvidenceResolutionStatus.ABSTAINED)


@pytest.mark.parametrize(("field", "value"), [
    ("gross_area_m2", 16.0),
    ("void_union_area_m2", 1.5),
    ("void_union_area_m2", -1.0),
    ("void_union_area_m2", True),
])
def test_source_net_gross_and_void_receipts_must_reconcile(field, value):
    gross, net, roles = _chain()
    altered = mutate_net_record(net, **{field: value})
    result = output(gross, altered, roles)
    assert result.quantity_evidence is None
    assert result.status is EvidenceResolutionStatus.CONFLICT
    assert LIVE_EXTERNAL_NET_WALL_LINEAGE_MISMATCH in result.reason_codes


def test_valid_full_wall_void_preserves_zero_net_instead_of_inventing_unsupported_area():
    gross, net, roles = _chain(net_a=0.0)
    result = output(gross, net, roles)
    assert result.status is EvidenceResolutionStatus.CORROBORATED
    assert result.quantity_evidence is not None
    assert result.quantity_evidence.value == 0.0
