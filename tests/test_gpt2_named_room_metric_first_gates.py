"""Only real producer-owned room IDs can receive source measurement first gates."""
from types import SimpleNamespace as N

from tools.diag_gpt2_named_room_metric_first_gates import (
    summarize_named_room_metric_first_gates as summarize,
)


def claim(rooms, *, same=(), cross=(), scale=()):
    return N(
        canonical_rooms=tuple(rooms),
        same_view_room_area_first_failure_codes=tuple(same),
        cross_view_room_area_first_failure_codes=tuple(cross),
        physical_scale_first_failure_codes=tuple(scale),
    )


def room(owner, label):
    return N(physical_room_id=owner, room_label=label)


def test_named_room_gates_preserve_exact_source_owned_failure_codes():
    got = summarize(claim(
        (room("source-1", " Freezer "), room("source-2", "Pwd")),
        same=(("source-1", "missing_figured_pair"), ("unlabelled", "reason")),
        cross=(("source-2", "source_cross_view_unavailable"),),
        scale=(("source-1", ("no_scale", "no_documented_dimensions")),),
    ))
    assert got["source_named_room_count"] == 2
    assert got["uniquely_attributable_named_room_count"] == 2
    assert got["named_room_metric_first_failure_codes"]["same_view"] == [{
        "physical_room_id": "source-1", "label": "FREEZER",
        "first_gate": "missing_figured_pair",
    }]
    assert got["named_room_metric_first_failure_codes"]["physical_scale"] == [{
        "physical_room_id": "source-1", "label": "FREEZER",
        "first_gates": ["no_scale", "no_documented_dimensions"],
        "source_reason_receipt_valid": True,
    }]
    assert got["all_source_first_failure_receipt_counts"] == {
        "same_view": 2, "cross_view": 1, "physical_scale": 1,
    }
    assert got["metric_quantity_published"] is False


def test_named_room_gates_abstain_on_duplicate_or_missing_physical_owner():
    got = summarize(claim(
        (room("source-shared", "FREEZER"),
         room("source-shared", "COLD ROOM"),
         room("", "LAUNDRY"),
         room("source-unique", "OFFICE")),
        same=(("source-shared", "ambiguous"), ("source-unique", "source_ok")),
    ))
    assert got["ambiguous_named_physical_room_ids"] == ["", "source-shared"]
    assert got["uniquely_attributable_named_room_count"] == 1
    assert got["named_room_metric_first_failure_codes"]["same_view"] == [{
        "physical_room_id": "source-unique", "label": "OFFICE",
        "first_gate": "source_ok",
    }]
    assert got["all_source_first_failure_receipt_counts"]["same_view"] == 2


def test_malformed_scale_reason_receipt_never_becomes_fake_individual_gates():
    for raw in ("scale_unavailable", None, 0, (), ("",)):
        report = summarize(claim(
            (room("room-1", "FREEZER"),),
            scale=(("room-1", raw),),
        ))
        entries = report["named_room_metric_first_failure_codes"]["physical_scale"]
        assert len(entries) == 1
        assert entries[0]["source_reason_receipt_valid"] is False
        assert entries[0]["first_gates"] in ([], [""])
        assert report["metric_quantity_published"] is False


def test_missing_producer_metric_first_gate_is_not_a_firm_measurement():
    got = summarize(claim(
        (room("source-freezer", "FREEZER"), room("source-pwd", "PWD")),
        same=(("source-freezer", "needs_orthogonal_figured_pair"),),
    ))
    assert got["named_rooms_without_first_failure_receipts"] == [{
        "physical_room_id": "source-pwd", "label": "PWD",
    }]
    assert got["named_room_metric_first_failure_codes"]["cross_view"] == []
    assert got["metric_quantity_published"] is False


def test_competing_or_duplicate_source_metric_first_failure_receipts_abstain():
    row = summarize(claim(
        (room("a", "FREEZER"), room("b", "SALES")),
        same=(("a", "need_figure"), ("a", "scale_ambiguous"),
              ("b", "no_dim"), ("b", "no_dim")),
    ))
    assert row["ambiguous_metric_first_failure_owner_ids"]["same_view"] == ["a"]
    assert row["named_room_metric_first_failure_codes"]["same_view"] == [{
        "physical_room_id": "b", "label": "SALES", "first_gate": "no_dim",
    }]
    assert row["named_rooms_without_first_failure_receipts"] == []
    assert row["all_source_first_failure_receipt_counts"]["same_view"] == 4
    assert row["metric_quantity_published"] is False


def test_none_and_whitespace_metric_gate_reasons_never_become_source_truth():
    for malformed in (None, "", "  ", 77):
        report = summarize(claim(
            (room("room-x", "FREEZER"),), cross=(("room-x", malformed),),
        ))
        assert report["named_room_metric_first_failure_codes"]["cross_view"] == [{
            "physical_room_id": "room-x", "label": "FREEZER",
            "first_gate": "", "source_reason_receipt_valid": False,
        }]
        assert report["metric_quantity_published"] is False


def test_malformed_source_gate_tuple_keeps_count_but_cannot_crash_ledger():
    malformed=(None, "orphan", ("room-a",), ("room-a", "gate", "extra"))
    row=summarize(claim(
        (room("room-a", "FREEZER"),),
        same=(*malformed, ("room-a", "actual_source_gate")),
    ))
    assert row["malformed_source_first_failure_receipt_counts"]["same_view"] == 4
    assert row["all_source_first_failure_receipt_counts"]["same_view"] == 5
    assert row["named_room_metric_first_failure_codes"]["same_view"] == [{
        "physical_room_id":"room-a", "label":"FREEZER",
        "first_gate":"actual_source_gate",
    }]
    assert row["metric_quantity_published"] is False
