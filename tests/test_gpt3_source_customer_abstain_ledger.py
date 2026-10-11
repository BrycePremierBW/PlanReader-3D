"""GPT3 source handoff preserves abstentions but never makes them takeoff."""
from test_customer_output_verification import sealed_and_rows
from tools.diag_gpt3_source_customer_evidence import build_source_customer_evidence_report


def test_source_customer_report_preserves_abstained_quantity_and_reason():
    sealed, rows = sealed_and_rows()
    report = build_source_customer_evidence_report(sealed.to_dict(), rows)
    assert report["abstained_source_item_count"] == 1
    assert len(report["abstained_source_items"]) == 1
    blocked = report["abstained_source_items"][0]
    assert blocked["quantity_id"] == "qty-abstain"
    assert blocked["value"] is None
    assert blocked["blocking_reasons"] == ["insufficient evidence"]
    assert blocked["source_sha256"] == "a" * 64
    assert blocked["canonical_object_refs"] == ["floor-3"]
    assert blocked["revision_id"] == "rev-3"
    assert [q["quantity_id"] for q in report["source_backed_sealed_items"]] == ["qty-1","qty-2"]
    assert report["quantity_to_customer_parity"]["customer_row_count"] == 2
    assert report["official_coverage_accuracy"] is None
    assert report["official_precision_adjusted_accuracy"] is None
    assert report["input_pdf_sha256_verified"] is False


def test_abstention_ledger_is_deterministic_and_noncommercial():
    sealed, rows = sealed_and_rows()
    first = build_source_customer_evidence_report(sealed.to_dict(), rows)
    second = build_source_customer_evidence_report(sealed.to_dict(), list(reversed(rows)))
    assert first["abstained_source_items"] == second["abstained_source_items"]
    assert first["source_backed_sealed_items"] == second["source_backed_sealed_items"]
    assert all(x["value"] is None for x in first["abstained_source_items"])
    assert not {x["quantity_id"] for x in first["abstained_source_items"]} & {
        x["quantity_id"] for x in first["source_backed_sealed_items"]
    }
