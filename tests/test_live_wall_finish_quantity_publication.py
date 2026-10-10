from __future__ import annotations

from dataclasses import replace

import pytest


from pb_bound_wall_finish_customer_bridge import (
    bound_wall_finish_record_to_takeoff_row,
)
from pb_live_canonical_coverage_registry import collect_live_canonical_coverage
from pb_live_canonical_wall_finish_surface import project_wall_finish_bindings
from pb_live_wall_finish_quantity_publication import (
    publish_bound_wall_finish_quantity,
)
from pb_takeoff_coverage_audit_adapter import build_runtime_coverage_publication
import pb_takeoff_row_contract as takeoff_contract
from tests.test_bound_wall_finish_quantity_authority_v1 import (
    DOC,
    PAGE,
    REV,
    SHA,
    SNAP,
    _binding,
    _finish_authority,
    _net_authority,
    _producer,
    _selector,
)


def _canonical_wall():
    return {
        "canonical_wall_id": "canonical-wall-1",
        "physical_wall_id": "wall-1",
        "document_id": DOC,
        "revision_id": REV,
        "source_sha256": SHA,
        "snapshot_id": SNAP,
        "page_id": PAGE,
        "level_ids": ["L1"],
        "net_area_m2": 12.5,
        "quantity_complete": True,
        "physical_identity_resolved": True,
        "evidence_ids": ["wall-evidence-1"],
    }


def _resolved_record_and_surface():
    binding = _binding("b1", "face-1", "wall-1")
    quantity_result = _producer(
        _finish_authority((binding,)),
        _net_authority({"wall-1": 12.5}),
    ).publish(_selector())
    assert quantity_result.record is not None

    projection = project_wall_finish_bindings(
        canonical_walls=(_canonical_wall(),),
        bindings=(binding,),
    )
    assert len(projection.surfaces) == 1
    return quantity_result.record, projection.surfaces[0]


def test_corroborated_finish_quantity_reuses_exact_canonical_surface_identity():
    record, surface = _resolved_record_and_surface()
    quantity = publish_bound_wall_finish_quantity(record)

    assert record.physical_surface_ids == (surface.physical_surface_id,)
    assert quantity.input_entity_ids == (surface.physical_surface_id,)
    assert quantity.value == 12.5
    assert quantity.unit == "m2"
    assert quantity.status == "corroborated"
    assert quantity.metadata["source_quantity_record_id"] == record.record_id


def test_finish_surface_reaches_published_only_through_exact_quantity_identity():
    record, surface = _resolved_record_and_surface()
    quantity = publish_bound_wall_finish_quantity(record)
    summaries, gaps = collect_live_canonical_coverage(
        objects=(surface,),
        quantities=(quantity,),
        registry_run_scope="wall-finish-live-quantity",
    )

    assert gaps == {}
    pre = build_runtime_coverage_publication(summaries, family_gaps=gaps)
    assert pre["family_reports"]["finish_surface"]["stage_counts"] == {
        "DETECTED": 1,
        "AUTHENTICATED": 1,
        "CANONICALIZED": 1,
        "QUANTIFIED": 1,
        "PUBLISHED": 0,
    }

    row = bound_wall_finish_record_to_takeoff_row(7, record)
    named = dict(zip(takeoff_contract.CORE_FIELDS, row))
    assert quantity.quantity_id in named["source_reference"]
    report = build_runtime_coverage_publication(
        summaries,
        family_gaps=gaps,
        published_takeoff_rows=(named,),
    )
    assert report["family_reports"]["finish_surface"]["stage_counts"] == {
        "DETECTED": 1,
        "AUTHENTICATED": 1,
        "CANONICALIZED": 1,
        "QUANTIFIED": 1,
        "PUBLISHED": 1,
    }


def test_customer_row_value_change_cannot_publish_finish_surface():
    record, surface = _resolved_record_and_surface()
    quantity = publish_bound_wall_finish_quantity(record)
    summaries, gaps = collect_live_canonical_coverage(
        objects=(surface,),
        quantities=(quantity,),
        registry_run_scope="wall-finish-value-guard",
    )
    row = dict(
        zip(
            takeoff_contract.CORE_FIELDS,
            bound_wall_finish_record_to_takeoff_row(7, record),
        )
    )
    row["quantity"] = float(row["quantity"]) + 0.01

    report = build_runtime_coverage_publication(
        summaries,
        family_gaps=gaps,
        published_takeoff_rows=(row,),
    )
    counts = report["family_reports"]["finish_surface"]["stage_counts"]
    assert counts["QUANTIFIED"] == 1
    assert counts["PUBLISHED"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"finish_scope_record_id": ""},
        {"finish_binding_ids": ()},
        {"finish_binding_ids": ("",)},
        {"net_wall_record_ids": ()},
        {"net_wall_record_ids": ("",)},
    ],
)
def test_wall_finish_publisher_rejects_missing_source_receipts(changes):
    record, _surface = _resolved_record_and_surface()
    with pytest.raises(ValueError, match="source lineage receipts"):
        publish_bound_wall_finish_quantity(replace(record, **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"record_id": ""},
        {"document_id": ""},
        {"revision_id": " "},
        {"source_sha256": ""},
        {"snapshot_id": ""},
        {"page_id": ""},
        {"viewport_id": " "},
        {"decision_scope_id": ""},
        {"trade_scope_id": ""},
        {"finish_material": " "},
        {"physical_face_ids": (" ",)},
        {"physical_wall_ids": ()},
        {"physical_wall_ids": (" ",)},
        {"physical_surface_ids": (" ",)},
    ],
)
def test_wall_finish_publisher_rejects_blank_physical_source_identity(changes):
    record, _surface = _resolved_record_and_surface()
    with pytest.raises(ValueError, match="physical/source identity"):
        publish_bound_wall_finish_quantity(replace(record, **changes))

@pytest.mark.parametrize("field", (
    "physical_surface_ids", "physical_face_ids", "physical_wall_ids",
    "finish_binding_ids", "net_wall_record_ids",
))
def test_duplicate_finish_identity_or_receipt_never_publishes(field):
    record, _surface = _resolved_record_and_surface()
    original = getattr(record, field)
    assert original
    replay = replace(record, **{field: (*original, original[0])})
    with pytest.raises(ValueError, match="(physical/source identity|source lineage receipts)"):
        publish_bound_wall_finish_quantity(replay)

@pytest.mark.parametrize("field", (
    "physical_surface_ids", "physical_face_ids", "physical_wall_ids",
    "finish_binding_ids", "net_wall_record_ids",
))
def test_untyped_finish_identity_and_lineage_receipt_never_publishes(field):
    record, _surface = _resolved_record_and_surface()
    original = getattr(record, field)
    assert original
    replay = replace(record, **{field: (*original, 42)})
    with pytest.raises(ValueError):
        publish_bound_wall_finish_quantity(replay)


@pytest.mark.parametrize(
    "bad_area",
    (0.0, -0.5, float("nan"), float("inf"), -float("inf"), True, False, "12.5", None),
)
def test_source_replay_invalid_metric_area_never_reaches_customer_quantity(bad_area):
    record, _surface = _resolved_record_and_surface()
    with pytest.raises(ValueError, match="invalid metric area"):
        publish_bound_wall_finish_quantity(replace(record, quantity_m2=bad_area))


@pytest.mark.parametrize(
    "field",
    ("physical_surface_ids", "physical_face_ids", "physical_wall_ids",
     "finish_binding_ids", "net_wall_record_ids"),
)
@pytest.mark.parametrize("bad_receipt", (None, 42, ("valid-id", []), ("valid-id", {"invalid": True})))
def test_untyped_or_unhashable_finish_receipts_fail_with_value_error(field, bad_receipt):
    record, _surface = _resolved_record_and_surface()
    with pytest.raises(ValueError):
        publish_bound_wall_finish_quantity(replace(record, **{field: bad_receipt}))


def test_finish_binding_cannot_alias_net_wall_or_finish_scope_evidence():
    record, _surface = _resolved_record_and_surface()
    with pytest.raises(ValueError, match="aliased source receipts"):
        publish_bound_wall_finish_quantity(
            replace(record, net_wall_record_ids=(record.finish_binding_ids[0],))
        )
    with pytest.raises(ValueError, match="aliased source receipts"):
        publish_bound_wall_finish_quantity(
            replace(record, finish_scope_record_id=record.finish_binding_ids[0])
        )
