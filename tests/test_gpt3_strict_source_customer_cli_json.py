"""GPT3 source/customer evidence CLI requires unambiguous JSON receipts."""
import json
import pytest
from test_customer_output_verification import sealed_and_rows
from tools.diag_gpt3_source_customer_evidence import main


def execute(tmp_path,monkeypatch,sealed_text,rows_text):
    seal=tmp_path/"sealed.json"
    rows=tmp_path/"rows.json"
    out=tmp_path/"report.json"
    seal.write_text(sealed_text,encoding="utf-8")
    rows.write_text(rows_text,encoding="utf-8")
    monkeypatch.setattr("sys.argv",["diag","--sealed-run",str(seal),"--customer-rows",str(rows),"--output",str(out)])
    main()
    return json.loads(out.read_text(encoding="utf-8"))


def test_cli_rejects_duplicate_nested_sealed_quantity_id(tmp_path,monkeypatch):
    signed,rows=sealed_and_rows()
    forged=signed.to_json().replace(
        '"quantity_id": "qty-1"',
        '"quantity_id": "forged", "quantity_id": "qty-1"',1,
    )
    with pytest.raises(ValueError,match="duplicate source/customer JSON key: quantity_id"):
        execute(tmp_path,monkeypatch,forged,json.dumps(rows))


def test_cli_rejects_duplicate_customer_quantity_id(tmp_path,monkeypatch):
    signed,rows=sealed_and_rows()
    serialized=json.dumps(rows)
    assert '"quantity_id": "qty-1"' in serialized
    serialized=serialized.replace(
        '"quantity_id": "qty-1"',
        '"quantity_id": "forged", "quantity_id": "qty-1"',1,
    )
    with pytest.raises(ValueError,match="duplicate source/customer JSON key: quantity_id"):
        execute(tmp_path,monkeypatch,signed.to_json(),serialized)


def test_cli_rejects_nonfinite_customer_quantity(tmp_path,monkeypatch):
    signed,rows=sealed_and_rows()
    rows[0]["quantity"]=float("nan")
    with pytest.raises(ValueError,match="non-finite source/customer JSON number"):
        execute(tmp_path,monkeypatch,signed.to_json(),json.dumps(rows))


def test_cli_rejects_nonfinite_sealed_confidence(tmp_path,monkeypatch):
    signed,rows=sealed_and_rows()
    text=signed.to_json()
    assert '"confidence": 0.99' in text
    corrupted=text.replace('"confidence": 0.99','"confidence": Infinity',1)
    with pytest.raises(ValueError,match="non-finite source/customer JSON number"):
        execute(tmp_path,monkeypatch,corrupted,json.dumps(rows))


def test_original_signed_source_and_customer_rows_remain_reportable(tmp_path,monkeypatch):
    signed,rows=sealed_and_rows()
    report=execute(tmp_path,monkeypatch,signed.to_json(),json.dumps(rows))
    assert report["quantity_to_customer_parity"]["valid_quantity_count"]==2
    assert report["official_frozen_evaluator_status"]=="UNPUBLISHED"
    assert report["official_coverage_accuracy"] is None
