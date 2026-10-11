"""GPT3 readiness diagnostics must never turn absent production into a score."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.report_full_plan_v2_readiness import diagnostic_report, _source_sha_proof

ROOT = Path("benchmarks/frozen_holdout/full_plan_v2")


def test_missing_production_is_explicitly_unpublished(tmp_path: Path) -> None:
    report = diagnostic_report(ROOT, tmp_path)
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False
    assert len(report["projects"]) == 4
    for project in report["projects"]:
        assert project["produced_file_present"] is False
        assert project["produced_count"] is None
        assert project["coverage_accuracy"] is None
        assert project["precision_adjusted_accuracy"] is None
        assert "production_items_missing" in project["blockers"]
        assert project["source_sha_verified"] is False


def test_duplicate_production_identifiers_cannot_be_hidden(tmp_path: Path) -> None:
    target = tmp_path / "au_qld_maryborough_service_station"
    target.mkdir()
    item = {
        "quantity_id": "duplicate-q",
        "trade_category": "surface",
        "value": 4.0,
        "unit": "m2",
        "object_refs": ["source-object"],
        "lineage_ok": True,
        "abstained": False,
    }
    (target / "produced_items.json").write_text(
        json.dumps([item, item]), encoding="utf-8"
    )
    report = diagnostic_report(ROOT, tmp_path)
    project = next(
        entry for entry in report["projects"]
        if entry["project_id"] == "au_qld_maryborough_service_station"
    )
    assert project["produced_count"] == 2
    assert project["duplicate_quantity_ids"] == ["duplicate-q"]
    assert "duplicate_produced_quantity_ids" in project["blockers"]
    assert project["coverage_accuracy"] is None


def test_empty_production_is_not_a_successful_reconciliation(tmp_path: Path) -> None:
    target = tmp_path / "au_qld_lot16_power"
    target.mkdir()
    (target / "produced_items.json").write_text("[]", encoding="utf-8")
    project = next(
        p for p in diagnostic_report(ROOT, tmp_path)["projects"]
        if p["project_id"] == "au_qld_lot16_power"
    )
    assert project["produced_file_present"] is True
    assert "empty_produced_items_unverified" in project["blockers"]
    assert project["reconciliation_complete"] is False


def test_source_hash_checks_actual_bytes_not_just_filename(tmp_path: Path) -> None:
    folder = tmp_path / "project-x"
    folder.mkdir()
    source = folder / "evidence.pdf"
    source.write_bytes(b"true source")
    manifest = {"source_documents": [{
        "name": "evidence.pdf",
        "size_bytes": len(b"true source"),
        "sha256": hashlib.sha256(b"true source").hexdigest(),
    }]}
    assert _source_sha_proof(manifest, tmp_path, "project-x") == (True, [])
    source.write_bytes(b"fake source")
    verified, reasons = _source_sha_proof(manifest, tmp_path, "project-x")
    assert verified is False
    assert "source_file_sha_mismatch:evidence.pdf" in reasons
    source.unlink()
    verified, reasons = _source_sha_proof(manifest, tmp_path, "project-x")
    assert verified is False
    assert "source_file_missing:evidence.pdf" in reasons


def test_sealed_run_absent_is_explicit_and_unpublished(tmp_path: Path) -> None:
    project = next(p for p in diagnostic_report(ROOT, tmp_path, sealed_root=tmp_path)["projects"]
                   if p["project_id"] == "au_qld_lot16_power")
    assert project["sealed_run_verified"] is False
    assert project["sealed_quantity_count"] is None
    assert "sealed_run_missing" in project["blockers"]
    assert project["coverage_accuracy"] is None


def test_tampered_sealed_run_cannot_claim_verified(tmp_path: Path) -> None:
    from scripts.report_full_plan_v2_readiness import _sealed_run_proof
    folder = tmp_path / "project-x"
    folder.mkdir()
    (folder / "sealed_run.json").write_text('{"project_id":"project-x","quantities":[]}', encoding="utf-8")
    verified, count, blockers = _sealed_run_proof(tmp_path, "project-x", set())
    assert verified is False
    assert count is None
    assert blockers == ["sealed_run_integrity_invalid"]


def test_missing_produced_quantity_id_blocks_readiness_without_crashing(tmp_path: Path) -> None:
    target = tmp_path / "au_qld_lot16_power"
    target.mkdir()
    # A malformed row still belongs in the production audit; it cannot
    # disappear or invent a benchmark identity just because the ID is absent.
    (target / "produced_items.json").write_text(
        json.dumps([{
            "trade_category": "opening", "value": 1.8, "unit": "m2",
            "object_refs": ["physical-opening-1"],
            "lineage_ok": True, "abstained": False,
        }]), encoding="utf-8",
    )
    report = diagnostic_report(ROOT, tmp_path)
    project = next(x for x in report["projects"] if x["project_id"] == "au_qld_lot16_power")
    assert project["produced_file_present"] is True
    assert project["produced_count"] == 1
    assert "produced_quantity_id_missing_or_invalid" in project["blockers"]
    assert project["reconciliation_complete"] is False
    assert project["coverage_accuracy"] is None
    assert project["precision_adjusted_accuracy"] is None
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False


def test_invalid_produced_quantity_id_types_do_not_become_fake_id_strings(tmp_path: Path) -> None:
    target = tmp_path / "au_qld_maryborough_service_station"
    target.mkdir()
    def item(quantity_id):
        return {
            "quantity_id": quantity_id, "trade_category": "surface",
            "value": 4.0, "unit": "m2", "object_refs": ["physical-floor-1"],
            "lineage_ok": True, "abstained": False,
        }
    (target / "produced_items.json").write_text(
        json.dumps([item(None), item(1234), item(" "), item("real-quantity-id")]),
        encoding="utf-8",
    )
    project = next(
        p for p in diagnostic_report(ROOT, tmp_path)["projects"]
        if p["project_id"] == "au_qld_maryborough_service_station"
    )
    assert project["produced_count"] == 4
    assert project["duplicate_quantity_ids"] == []
    assert "produced_quantity_id_missing_or_invalid" in project["blockers"]
    assert "None" not in project["duplicate_quantity_ids"]
    assert project["reconciliation_complete"] is False
    assert project["coverage_accuracy"] is None


def test_invalid_produced_json_cannot_abort_other_projects_or_publish_score(tmp_path: Path) -> None:
    project_dir = tmp_path / "au_qld_lot16_power"
    project_dir.mkdir()
    (project_dir / "produced_items.json").write_text("{not-json", encoding="utf-8")

    report = diagnostic_report(ROOT, tmp_path)
    assert len(report["projects"]) == 4
    lot16 = next(p for p in report["projects"] if p["project_id"] == "au_qld_lot16_power")
    maryborough = next(
        p for p in report["projects"]
        if p["project_id"] == "au_qld_maryborough_service_station"
    )
    assert lot16["produced_file_present"] is True
    assert lot16["produced_count"] is None
    assert lot16["sealed_quantity_count"] is None
    assert lot16["produced_sealed_parity_verified"] is False
    assert "produced_items_invalid_json_or_shape" in lot16["blockers"]
    assert "empty_produced_items_unverified" not in lot16["blockers"]
    assert maryborough["produced_file_present"] is False
    assert "production_items_missing" in maryborough["blockers"]
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False


def test_wrong_produced_document_shape_blocks_project_without_fabricating_count(tmp_path: Path) -> None:
    project_dir = tmp_path / "au_qld_3laurel"
    project_dir.mkdir()
    for invalid in ('{"quantity_id":"fake-list"}', '[{"quantity_id":"q"}, null]', 'null'):
        (project_dir / "produced_items.json").write_text(invalid, encoding="utf-8")
        report = diagnostic_report(ROOT, tmp_path)
        result = next(p for p in report["projects"] if p["project_id"] == "au_qld_3laurel")
        assert "produced_items_invalid_json_or_shape" in result["blockers"]
        assert result["produced_count"] is None
        assert result["lineage_conflict_count"] is None
        assert result["abstention_count"] is None
        assert result["reconciliation_complete"] is False
        assert result["coverage_accuracy"] is None
        assert result["precision_adjusted_accuracy"] is None


def test_duplicate_json_object_keys_cannot_overwrite_production_quantity_identity(tmp_path: Path) -> None:
    target = tmp_path / "au_qld_3laurel"
    target.mkdir()
    (target / "produced_items.json").write_text(
        '[{"quantity_id":"authenticated-id", "quantity_id":"rekeyed-id", '
        '"value":1.0,"unit":"m2","trade_category":"surface"}]',
        encoding="utf-8",
    )
    report = diagnostic_report(ROOT, tmp_path)
    project = next(x for x in report["projects"] if x["project_id"] == "au_qld_3laurel")
    assert project["produced_file_present"] is True
    assert project["produced_count"] is None
    assert "produced_items_invalid_json_or_shape" in project["blockers"]
    assert project["produced_sealed_parity_verified"] is False
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False



def test_unreadable_sealed_run_bytes_are_one_project_blocker_not_suite_crash(tmp_path: Path) -> None:
    sealed_root = tmp_path / "sealed"
    target = sealed_root / "au_qld_lot16_power"
    target.mkdir(parents=True)
    (target / "sealed_run.json").write_bytes(bytes((0xFF, 0xFE, 0xFA)))

    report = diagnostic_report(ROOT, tmp_path / "produced", sealed_root=sealed_root)
    assert len(report["projects"]) == 4
    lot16 = next(p for p in report["projects"] if p["project_id"] == "au_qld_lot16_power")
    maryborough = next(
        p for p in report["projects"]
        if p["project_id"] == "au_qld_maryborough_service_station"
    )
    assert lot16["sealed_run_verified"] is False
    assert lot16["sealed_quantity_count"] is None
    assert "sealed_run_integrity_invalid" in lot16["blockers"]
    assert "sealed_run_missing" in maryborough["blockers"]
    assert lot16["reconciliation_complete"] is False
    assert lot16["coverage_accuracy"] is None
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False



def test_duplicate_json_keys_in_sealed_run_fail_before_fingerprint_validation(tmp_path: Path) -> None:
    from scripts.report_full_plan_v2_readiness import _object

    sealed_root = tmp_path / "sealed"
    target = sealed_root / "au_qld_lot16_power"
    target.mkdir(parents=True)
    path = target / "sealed_run.json"
    # A second apparently well-formed key cannot shadow original project ID.
    path.write_text(
        '{"project_id":"au_qld_lot16_power",'
        '"project_id":"another-project","quantities":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key: project_id"):
        _object(path)

    report = diagnostic_report(ROOT, tmp_path / "produced", sealed_root=sealed_root)
    assert len(report["projects"]) == 4
    lot16 = next(p for p in report["projects"] if p["project_id"] == "au_qld_lot16_power")
    other = next(p for p in report["projects"] if p["project_id"] == "au_qld_maryborough_service_station")
    assert lot16["sealed_run_verified"] is False
    assert lot16["sealed_quantity_count"] is None
    assert "sealed_run_integrity_invalid" in lot16["blockers"]
    assert "sealed_run_missing" in other["blockers"]
    assert lot16["coverage_accuracy"] is None
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False


def test_nested_duplicate_identity_in_sealed_payload_is_rejected(tmp_path: Path) -> None:
    from scripts.report_full_plan_v2_readiness import _object

    target = tmp_path / "sealed.json"
    target.write_text(
        '{"project_id":"au_qld_lot16_power",'
        '"quantities":[{"quantity_id":"q1","quantity_id":"q2"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key: quantity_id"):
        _object(target)


@pytest.mark.parametrize("invalid_number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_nonfinite_numbers_reject_entire_production_document_without_fabricated_count(
    tmp_path: Path, invalid_number: str
) -> None:
    target = tmp_path / "au_qld_lot16_power"
    target.mkdir()
    (target / "produced_items.json").write_text(
        '[{"quantity_id":"source-quantity-1","lineage_ok":true,'
        '"object_refs":["source-opening-1"],"abstained":false,'
        '"value":' + invalid_number + ',"unit":"m2","trade_category":"opening"}]',
        encoding="utf-8",
    )
    report = diagnostic_report(ROOT, tmp_path)
    project = next(
        p for p in report["projects"] if p["project_id"] == "au_qld_lot16_power"
    )
    assert project["produced_file_present"] is True
    assert project["produced_count"] is None
    assert project["produced_sealed_parity_verified"] is False
    assert "produced_items_invalid_json_or_shape" in project["blockers"]
    assert project["coverage_accuracy"] is None
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False


@pytest.mark.parametrize("invalid_number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_nonfinite_numbers_in_sealed_run_fail_integrity_not_other_projects(
    tmp_path: Path, invalid_number: str
) -> None:
    from scripts.report_full_plan_v2_readiness import _object

    sealed_root = tmp_path / "sealed"
    target = sealed_root / "au_qld_lot16_power"
    target.mkdir(parents=True)
    path = target / "sealed_run.json"
    path.write_text(
        '{"project_id":"au_qld_lot16_power","quantities":['
        '{"quantity_id":"source-quantity-1","value":' + invalid_number + '}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-finite JSON"):
        _object(path)

    report = diagnostic_report(ROOT, tmp_path / "produced", sealed_root=sealed_root)
    lot16 = next(
        p for p in report["projects"] if p["project_id"] == "au_qld_lot16_power"
    )
    other = next(
        p for p in report["projects"]
        if p["project_id"] == "au_qld_maryborough_service_station"
    )
    assert lot16["sealed_run_verified"] is False
    assert lot16["sealed_quantity_count"] is None
    assert "sealed_run_integrity_invalid" in lot16["blockers"]
    assert "sealed_run_missing" in other["blockers"]
    assert lot16["coverage_accuracy"] is None
    assert report["score_claim"] is False


def test_nonfinite_manifest_json_is_rejected_before_source_identity_checks(tmp_path: Path) -> None:
    from scripts.report_full_plan_v2_readiness import _object

    for invalid in ("NaN", "Infinity", "-Infinity", "1e999"):
        target = tmp_path / "manifest.json"
        target.write_text('{"source_documents":[{"size_bytes":' + invalid + '}]}',
                          encoding="utf-8")
        with pytest.raises(ValueError, match="non-finite JSON"):
            _object(target)


@pytest.mark.parametrize("sign", ("", "-"))
def test_oversized_json_integer_is_project_blocker_not_suite_crash(
    tmp_path: Path, sign: str
) -> None:
    numeric_token = sign + "1" + "0" * 400
    target = tmp_path / "au_qld_lot16_power"
    target.mkdir()
    (target / "produced_items.json").write_text(
        '[{"quantity_id":"real-source-quantity","lineage_ok":true,'
        '"object_refs":["opening-source-object"],"abstained":false,'
        '"value":' + numeric_token + ',"unit":"m2",'
        '"trade_category":"opening"}]',
        encoding="utf-8",
    )
    report = diagnostic_report(ROOT, tmp_path)
    assert len(report["projects"]) == 4
    lot16 = next(
        x for x in report["projects"]
        if x["project_id"] == "au_qld_lot16_power"
    )
    other = next(
        x for x in report["projects"]
        if x["project_id"] == "au_qld_maryborough_service_station"
    )
    assert lot16["produced_file_present"] is True
    assert lot16["produced_count"] is None
    assert "produced_items_invalid_json_or_shape" in lot16["blockers"]
    assert "production_items_missing" in other["blockers"]
    assert lot16["coverage_accuracy"] is None
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False


@pytest.mark.parametrize("sign", ("", "-"))
def test_oversized_json_integer_in_sealed_run_is_local_integrity_failure(
    tmp_path: Path, sign: str
) -> None:
    from scripts.report_full_plan_v2_readiness import _object

    sealed_root = tmp_path / "sealed"
    target = sealed_root / "au_qld_lot16_power"
    target.mkdir(parents=True)
    (target / "sealed_run.json").write_text(
        '{"project_id":"au_qld_lot16_power",'
        '"quantities":[{"quantity_id":"q",'
        '"value":' + sign + "1" + "0" * 400 + '}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="out-of-range JSON integer"):
        _object(target / "sealed_run.json")
    report = diagnostic_report(ROOT, tmp_path / "produced", sealed_root=sealed_root)
    lot16 = next(
        x for x in report["projects"]
        if x["project_id"] == "au_qld_lot16_power"
    )
    assert lot16["sealed_run_verified"] is False
    assert lot16["sealed_quantity_count"] is None
    assert "sealed_run_integrity_invalid" in lot16["blockers"]
    assert report["score_claim"] is False


def test_realistic_large_json_integer_still_parses_exactly() -> None:
    from scripts.report_full_plan_v2_readiness import _parse_evidence_json
    assert _parse_evidence_json('{"source_numeric_id":12345678901234567890}') == {
        "source_numeric_id": 12345678901234567890
    }


@pytest.mark.parametrize("bad_value", (10 ** 400, -(10 ** 400)))
def test_direct_produced_sealed_parity_huge_integer_abstains_without_crash(
    bad_value: int,
) -> None:
    from types import SimpleNamespace
    from scripts.report_full_plan_v2_readiness import produced_sealed_parity_blockers

    row = SimpleNamespace(
        quantity_id="source-authenticated-q",
        abstained=False,
        lineage_ok=True,
        unit="m2",
        value=12.0,
        object_identity_refs=("physical-source-1",),
    )
    produced = [{
        "quantity_id": "source-authenticated-q",
        "abstained": False,
        "lineage_ok": True,
        "unit": "m2",
        "value": bad_value,
        "object_refs": ["physical-source-1"],
        "trade_category": "opening",
    }]
    assert produced_sealed_parity_blockers(produced, (row,)) == [
        "projection_value_mismatch:source-authenticated-q"
    ]


@pytest.mark.parametrize("failure", (
    FileNotFoundError("sealed file concurrently removed"),
    UnicodeError("sealed file concurrently corrupted"),
    ValueError("sealed payload replaced with malformed JSON"),
))
def test_concurrent_seal_replacement_is_local_parity_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    from scripts import report_full_plan_v2_readiness as module

    sealed_root = tmp_path / "sealed"
    path = sealed_root / "au_qld_lot16_power"
    path.mkdir(parents=True)
    # This internal parity pass follows a successful independent seal proof.
    # It must handle a second-read race, not fabricate complete source parity.
    (path / "sealed_run.json").write_text("{}", encoding="utf-8")

    def changed_seal(_path: Path) -> dict:
        raise failure

    monkeypatch.setattr(module, "_object", changed_seal)
    assert module._sealed_projection_proof(
        sealed_root, "au_qld_lot16_power", [], True
    ) == (False, ["sealed_run_changed_during_parity"])


def test_replaced_seal_cannot_switch_project_during_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from scripts import report_full_plan_v2_readiness as module
    import pb_source_closed_run_export as exporter

    root = tmp_path / "sealed"
    target = root / "au_qld_lot16_power"
    target.mkdir(parents=True)
    (target / "sealed_run.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(module, "_object", lambda _path: {})
    monkeypatch.setattr(
        exporter, "sealed_source_closed_run_from_dict",
        lambda _payload: SimpleNamespace(
            project_id="au_qld_maryborough_service_station", quantities=()
        ),
    )
    assert module._sealed_projection_proof(
        root, "au_qld_lot16_power", [], True
    ) == (False, ["sealed_run_changed_during_parity"])


def test_first_seal_proof_captures_exact_verified_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from scripts import report_full_plan_v2_readiness as module
    import pb_source_closed_run_export as exporter

    project_id = "au_qld_lot16_power"
    target = tmp_path / project_id
    target.mkdir()
    (target / "sealed_run.json").write_text("{}", encoding="utf-8")
    source_sha = "a" * 64
    seal = SimpleNamespace(
        project_id=project_id,
        source_sha256s=(source_sha,),
        quantities=(SimpleNamespace(
            lineage_ok=True,
            abstained=False,
            object_identity_refs=("physical-source-object",),
        ),),
        fingerprint="verified-cryptographic-run-fingerprint",
    )
    monkeypatch.setattr(module, "_object", lambda _path: {})
    monkeypatch.setattr(
        exporter, "sealed_source_closed_run_from_dict", lambda _payload: seal
    )
    fingerprints: list[str] = []
    assert module._sealed_run_proof(
        tmp_path, project_id, {source_sha},
        seal_fingerprint_sink=fingerprints,
    ) == (True, 1, [])
    assert fingerprints == ["verified-cryptographic-run-fingerprint"]


def test_valid_but_swapped_second_seal_is_not_authorized_by_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from scripts import report_full_plan_v2_readiness as module
    import pb_source_closed_run_export as exporter

    project_id = "au_qld_lot16_power"
    target = tmp_path / project_id
    target.mkdir()
    (target / "sealed_run.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "_object", lambda _path: {})
    monkeypatch.setattr(
        exporter, "sealed_source_closed_run_from_dict",
        lambda _payload: SimpleNamespace(
            project_id=project_id, quantities=(),
            fingerprint="other-valid-production-run",
        ),
    )
    assert module._sealed_projection_proof(
        tmp_path, project_id, [], True,
        expected_seal_fingerprint="first-verified-production-run",
    ) == (False, ["sealed_run_changed_during_parity"])


def test_unchanged_signed_seal_fingerprint_can_reach_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from scripts import report_full_plan_v2_readiness as module
    import pb_source_closed_run_export as exporter

    project_id = "au_qld_lot16_power"
    target = tmp_path / project_id
    target.mkdir()
    (target / "sealed_run.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "_object", lambda _path: {})
    monkeypatch.setattr(
        exporter, "sealed_source_closed_run_from_dict",
        lambda _payload: SimpleNamespace(
            project_id=project_id, quantities=(),
            fingerprint="unchanged-production-run",
        ),
    )
    assert module._sealed_projection_proof(
        tmp_path, project_id, [], True,
        expected_seal_fingerprint="unchanged-production-run",
    ) == (True, [])


@pytest.mark.parametrize("structure", ("arrays", "objects"))
def test_overdeep_produced_json_blocks_one_project_not_full_suite(
    tmp_path: Path, structure: str
) -> None:
    from scripts.report_full_plan_v2_readiness import _parse_evidence_json

    if structure == "arrays":
        payload = "[" * 1600 + "0" + "]" * 1600
    else:
        payload = '{"nested":' * 1600 + "0" + "}" * 1600

    with pytest.raises(ValueError, match="JSON nesting exceeds safe parser depth"):
        _parse_evidence_json(payload)

    folder = tmp_path / "au_qld_lot16_power"
    folder.mkdir()
    (folder / "produced_items.json").write_text(payload, encoding="utf-8")
    report = diagnostic_report(ROOT, tmp_path)
    assert len(report["projects"]) == 4
    lot16 = next(
        row for row in report["projects"]
        if row["project_id"] == "au_qld_lot16_power"
    )
    maryborough = next(
        row for row in report["projects"]
        if row["project_id"] == "au_qld_maryborough_service_station"
    )
    assert lot16["produced_file_present"] is True
    assert lot16["produced_count"] is None
    assert "produced_items_invalid_json_or_shape" in lot16["blockers"]
    assert maryborough["produced_file_present"] is False
    assert "production_items_missing" in maryborough["blockers"]
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False


def test_overdeep_sealed_json_is_local_integrity_failure(
    tmp_path: Path,
) -> None:
    sealed_root = tmp_path / "sealed"
    folder = sealed_root / "au_qld_lot16_power"
    folder.mkdir(parents=True)
    nested = "[" * 1600 + "0" + "]" * 1600
    (folder / "sealed_run.json").write_text(
        '{"project_id":"au_qld_lot16_power","quantities":' + nested + "}",
        encoding="utf-8",
    )
    report = diagnostic_report(
        ROOT, tmp_path / "produced", sealed_root=sealed_root
    )
    lot16 = next(
        row for row in report["projects"]
        if row["project_id"] == "au_qld_lot16_power"
    )
    assert lot16["sealed_run_verified"] is False
    assert lot16["sealed_quantity_count"] is None
    assert "sealed_run_integrity_invalid" in lot16["blockers"]
    assert report["score_claim"] is False


def test_modestly_nested_source_json_still_parses_without_value_changes() -> None:
    from scripts.report_full_plan_v2_readiness import _parse_evidence_json

    depth = 24
    payload = "[" * depth + '{"source_qty":13.270425}' + "]" * depth
    actual = _parse_evidence_json(payload)
    for _ in range(depth):
        assert len(actual) == 1
        actual = actual[0]
    assert actual == {"source_qty": 13.270425}


def test_quoted_and_escaped_brackets_do_not_count_as_json_structure() -> None:
    import json
    from scripts.report_full_plan_v2_readiness import _parse_evidence_json

    # The guard must ignore source notes containing drawings, escaped quote
    # text and literal braces instead of mistaking them for nested JSON.
    human_note = ("[{" * 1000) + ' witness: "quoted" \\ geometry' + ("}]" * 1000)
    encoded = json.dumps({"source_note": human_note, "value": 13.270425})
    assert _parse_evidence_json(encoded) == {
        "source_note": human_note, "value": 13.270425
    }


def test_all_four_frozen_reconciliation_buckets_are_unknown_until_evaluated(
    tmp_path: Path,
) -> None:
    # The user-facing count schema must be complete but never invent zero
    # matches/misses or unsupported extras before source-complete evaluation.
    lot16 = tmp_path / "au_qld_lot16_power"
    lot16.mkdir()
    (lot16 / "produced_items.json").write_text(
        json.dumps([{
            "quantity_id": "source-owned-opening-q",
            "trade_category": "opening",
            "value": 1.8,
            "unit": "m2",
            "object_refs": ["source-owned-opening"],
            "lineage_ok": True,
            "abstained": False,
        }]), encoding="utf-8",
    )
    report = diagnostic_report(ROOT, tmp_path)
    assert report["publication_status"] == "UNPUBLISHED"
    assert report["score_claim"] is False
    assert len(report["projects"]) == 4
    expected = (
        "matched_within_tolerance",
        "matched_outside_tolerance",
        "missed",
        "partial",
        "unresolved",
        "unsupported_extra",
    )
    for project in report["projects"]:
        assert project["reconciliation_evaluation_status"] == "NOT_EVALUATED"
        assert project["reconciliation_complete"] is False
        assert project["denominator"] > 0
        assert all(project[key] is None for key in expected)
        assert project["coverage_accuracy"] is None
        assert project["precision_adjusted_accuracy"] is None
    produced = next(
        item for item in report["projects"]
        if item["project_id"] == "au_qld_lot16_power"
    )
    assert produced["produced_count"] == 1
    assert produced["matched_within_tolerance"] is None
    assert produced["missed"] is None


def test_unreadable_original_source_is_local_sha_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    from scripts.report_full_plan_v2_readiness import _source_sha_proof

    project_id = "au_qld_lot16_power"
    folder = tmp_path / project_id
    folder.mkdir()
    failing_source = folder / "OriginalLot16.pdf"
    passing_source = folder / "RealOtherSource.pdf"
    failing_bytes = b"true-original-source-frozen-data"
    passing_bytes = b"independent-source-bytes"
    failing_source.write_bytes(failing_bytes)
    passing_source.write_bytes(passing_bytes)
    docs = [
        {
            "name": name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        for name, payload in (
            ("OriginalLot16.pdf", failing_bytes),
            ("RealOtherSource.pdf", passing_bytes),
        )
    ]
    original_open = Path.open

    def interrupted_original_open(self: Path, *args, **kwargs):
        if self == failing_source:
            raise PermissionError("original source temporarily unavailable")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupted_original_open)
    result, blockers = _source_sha_proof(
        {"source_documents": docs}, tmp_path, project_id
    )
    assert result is False
    assert blockers == ["source_file_unreadable:OriginalLot16.pdf"]

    # A subsequent unchanged original-source read is still verified by its
    # exact frozen SHA, never a guessed size or user-entered value.
    monkeypatch.setattr(Path, "open", original_open)
    assert _source_sha_proof(
        {"source_documents": docs}, tmp_path, project_id
    ) == (True, [])


def test_disappearing_original_source_is_local_sha_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    from scripts.report_full_plan_v2_readiness import _source_sha_proof

    project_id = "au_qld_maryborough_service_station"
    original_pdf = tmp_path / project_id / "MaryboroughOriginal.pdf"
    original_pdf.parent.mkdir()
    payload = b"real-hashed-source"
    original_pdf.write_bytes(payload)
    original_stat = Path.stat

    def interrupted_stat(self: Path, *args, **kwargs):
        if self == original_pdf:
            raise FileNotFoundError("source vanished during stat")
        return original_stat(self, *args, **kwargs)

    # The first source.is_file check itself can reject a missing source.
    monkeypatch.setattr(Path, "stat", interrupted_stat)
    valid, blockers = _source_sha_proof(
        {"source_documents": [{
            "name": original_pdf.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }]}, tmp_path, project_id,
    )
    assert valid is False
    assert blockers in (
        ["source_file_missing:MaryboroughOriginal.pdf"],
        ["source_file_unreadable:MaryboroughOriginal.pdf"],
    )
