"""Original sealed-run JSON must not hide signed identities via duplicate keys."""
import pytest
import pb_combine_source_closed_runs as combiner
from test_combine_source_closed_runs_cli import quantity,trace,SHA_A
from pb_source_closed_run_export import seal_source_closed_run


def signed_source_json():
    q=quantity("q1","room-1",SHA_A)
    run=seal_source_closed_run([q],project_id="project-a",
                               traces_by_quantity_id={"q1":trace("room-1",SHA_A)})
    return run.to_json()


def test_duplicate_top_level_project_id_is_not_last_write_wins(tmp_path):
    original=signed_source_json()
    assert '"project_id": "project-a"' in original
    forged=original.replace(
        '"project_id": "project-a"',
        '"project_id": "other-project", "project_id": "project-a"',1
    )
    file=tmp_path/"duplicate-project.json"
    file.write_text(forged,encoding="utf-8")
    with pytest.raises(ValueError,match="duplicate sealed JSON key: project_id"):
        combiner.load_verified_sealed_run(file)


def test_nested_source_identity_cannot_be_duplicated(tmp_path):
    original=signed_source_json()
    forged=original.replace(
        '"quantity_id": "q1"',
        '"quantity_id": "other-quantity", "quantity_id": "q1"',1
    )
    file=tmp_path/"duplicate-quantity.json"
    file.write_text(forged,encoding="utf-8")
    with pytest.raises(ValueError,match="duplicate sealed JSON key: quantity_id"):
        combiner.combine_sealed_run_files([file])


def test_nonfinite_json_constant_rejected_before_seal_loader(tmp_path):
    source=signed_source_json()
    assert '"value": 10.0' in source
    forged=source.replace('"value": 10.0','"value": NaN',1)
    file=tmp_path/"nonfinite.json"
    file.write_text(forged,encoding="utf-8")
    with pytest.raises(ValueError,match="non-finite sealed JSON number"):
        combiner.load_verified_sealed_run(file)


def test_exact_original_json_roundtrip_unchanged(tmp_path):
    file=tmp_path/"good.json"
    file.write_text(signed_source_json(),encoding="utf-8")
    sealed=combiner.load_verified_sealed_run(file)
    assert sealed.project_id=="project-a"
    assert len(sealed.quantities)==1
    assert sealed.quantities[0].quantity_id=="q1"
