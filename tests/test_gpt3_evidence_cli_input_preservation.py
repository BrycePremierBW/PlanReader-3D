"""Signed GPT3 source/customer inputs are never valid report output targets."""
from __future__ import annotations

import json
import sys

import pytest

from test_customer_output_verification import sealed_and_rows
from tools import diag_gpt3_source_customer_evidence as cli


def _sources(tmp_path):
    sealed, rows = sealed_and_rows()
    sealed_path = tmp_path / "sealed.json"
    rows_path = tmp_path / "rows.json"
    sealed_path.write_text(sealed.to_json(), encoding="utf-8")
    rows_path.write_text(json.dumps(rows), encoding="utf-8")
    return sealed_path, rows_path


def _invoke(monkeypatch, sealed_path, rows_path, output):
    monkeypatch.setattr(sys, "argv", [
        "source-customer-diagnostic",
        "--sealed-run", str(sealed_path),
        "--customer-rows", str(rows_path),
        "--output", str(output),
    ])
    cli.main()


@pytest.mark.parametrize("alias", ["sealed", "customer"])
def test_output_cannot_overwrite_signed_evidence_input(tmp_path, monkeypatch, alias):
    sealed_path, rows_path = _sources(tmp_path)
    target = sealed_path if alias == "sealed" else rows_path
    originals = (sealed_path.read_bytes(), rows_path.read_bytes())
    with pytest.raises(ValueError, match="must not overwrite"):
        _invoke(monkeypatch, sealed_path, rows_path, target)
    assert (sealed_path.read_bytes(), rows_path.read_bytes()) == originals


def test_output_symlink_to_source_is_rejected(tmp_path, monkeypatch):
    sealed_path, rows_path = _sources(tmp_path)
    output = tmp_path / "report-alias.json"
    try:
        output.symlink_to(sealed_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"filesystem does not support symlinks: {exc}")
    original = sealed_path.read_bytes()
    with pytest.raises(ValueError, match="must not overwrite"):
        _invoke(monkeypatch, sealed_path, rows_path, output)
    assert sealed_path.read_bytes() == original
    assert output.is_symlink()


def test_failure_to_publish_diagnostic_leaves_existing_report_unmodified(tmp_path, monkeypatch):
    sealed_path, rows_path = _sources(tmp_path)
    output = tmp_path / "report.json"
    output.write_text("prior valid report data", encoding="utf-8")
    previous = output.read_bytes()
    originals = (sealed_path.read_bytes(), rows_path.read_bytes())

    def simulated_rename_failure(*_args):
        raise OSError("simulated report publication failure")

    monkeypatch.setattr(cli.os, "replace", simulated_rename_failure)
    with pytest.raises(OSError, match="simulated report publication failure"):
        _invoke(monkeypatch, sealed_path, rows_path, output)
    assert output.read_bytes() == previous
    assert (sealed_path.read_bytes(), rows_path.read_bytes()) == originals
    assert not list(tmp_path.glob(".report.json.*.tmp"))


def test_report_writes_successfully_without_staging_residue(tmp_path, monkeypatch):
    sealed_path, rows_path = _sources(tmp_path)
    output = tmp_path / "report.json"
    _invoke(monkeypatch, sealed_path, rows_path, output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["official_frozen_evaluator_status"] == "UNPUBLISHED"
    assert report["quantity_to_customer_parity"]["valid_quantity_count"] == 2
    assert not list(tmp_path.glob(".report.json.*.tmp"))
