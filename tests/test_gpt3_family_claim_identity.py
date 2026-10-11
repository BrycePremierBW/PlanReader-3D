"""Production customer output identity cannot alias across quantity families."""
import pytest
import pb_quantity_takeoff_adapter as adapter
from test_quantity_takeoff_adapter import quantity, source_trace, figured


def output(quantities):
    traces = {q.quantity_id: source_trace(
        canonical_entity_ids=q.input_entity_ids,
        evidence_ids=q.evidence_ids,
    ) for q in quantities}
    auths = {q.quantity_id: figured() for q in quantities}
    return adapter.quantities_to_takeoff_output_rows(
        quantities, traces_by_quantity_id=traces, authorities_by_quantity_id=auths,
    )


def test_same_semantic_and_object_is_allowed_for_distinct_quantity_families():
    first=quantity(quantity_id="qty-floor",family="floor_area",semantic_key="room.area")
    second=quantity(quantity_id="qty-ceiling",family="ceiling_area",semantic_key="room.area")
    rows=output([first,second])
    assert [r["quantity_id"] for r in rows] == ["qty-floor","qty-ceiling"]
    assert [r["quantity_family"] for r in rows] == ["floor_area","ceiling_area"]


def test_distinct_measurement_families_preserve_original_source_order():
    first=quantity(quantity_id="qty-ceiling",family="ceiling_area",semantic_key="room.area")
    second=quantity(quantity_id="qty-floor",family="floor_area",semantic_key="room.area")
    assert [r["quantity_id"] for r in output([first,second])] == ["qty-ceiling","qty-floor"]


@pytest.mark.parametrize("other_family",["wall_area","WALL_AREA","wall-area"])
def test_same_family_semantic_and_physical_identity_still_rejects_duplicate(other_family):
    a=quantity(quantity_id="qty-a",family="wall_area",semantic_key="room.area")
    b=quantity(quantity_id="qty-b",family=other_family,semantic_key="room.area")
    with pytest.raises(adapter.CommercialTakeoffConflictError,match="duplicate emitted"):
        output([a,b])


def test_same_quantity_id_across_distinct_families_cannot_create_two_customer_rows():
    a=quantity(quantity_id="qty-reused",family="floor_area",semantic_key="floor.area")
    b=quantity(quantity_id="qty-reused",family="ceiling_area",semantic_key="ceiling.area")
    with pytest.raises(adapter.CommercialTakeoffConflictError,match="duplicate commercial QuantityEvidence ID"):
        output([a,b])


def test_same_quantity_id_across_distinct_semantics_also_rejected():
    a=quantity(quantity_id="qty-reused",semantic_key="wall.area")
    b=quantity(quantity_id="qty-reused",semantic_key="wall.length")
    with pytest.raises(adapter.CommercialTakeoffConflictError,match="duplicate commercial QuantityEvidence ID"):
        output([a,b])


def test_same_family_same_semantic_disjoint_physical_identities_still_project():
    a=quantity(quantity_id="qty-a",family="wall_area",input_entity_ids=("wall-a",))
    b=quantity(quantity_id="qty-b",family="wall_area",input_entity_ids=("wall-b",))
    assert [r["quantity_id"] for r in output([a,b])] == ["qty-a","qty-b"]
