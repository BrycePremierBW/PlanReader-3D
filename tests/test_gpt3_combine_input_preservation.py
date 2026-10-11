"""Combining signed source runs may never overwrite a producer's receipt."""
from __future__ import annotations

import json

import pytest

import pb_combine_source_closed_runs as cli
from pb_source_closed_run_export import seal_source_closed_run
from test_combine_source_closed_runs_cli import SHA_A, quantity, trace


def _original_source(tmp_path):
    q = quantity("q1", "room-1", SHA_A)
    sealed = seal_source_closed_run(
        [q],
        project_id="project-a",
        traces_by_quantity_id={"q1": trace("room-1", SHA_A)},
    )
    source = tmp_path / "signed-source.json"
    source.write_text(sealed.to_json(), encoding="utf-8")
    return source


def test_cli_rejects_same_output_as_signed_source_without_mutation(tmp_path):
    source = _original_source(tmp_path)
    original = source.read_bytes()
    with pytest.raises(ValueError, match="must not overwrite"):
        cli.main([
            "--project-id", "project-a",
            "--input", str(source), "--output", str(source),
        ])
    assert source.read_bytes() == original
    assert cli.load_verified_sealed_run(source).project_id == "project-a"


def test_cli_rejects_parent_directory_alias_without_mutation(tmp_path):
    folder = tmp_path / "sources"
    folder.mkdir()
    source = _original_source(folder)
    original = source.read_bytes()
    output_alias = folder / ".." / "sources" / "signed-source.json"
    with pytest.raises(ValueError, match="must not overwrite"):
        cli.main(["--input", str(source), "--output", str(output_alias)])
    assert source.read_bytes() == original


def test_cli_rejects_output_symlink_alias_to_signed_source(tmp_path):
    source = _original_source(tmp_path)
    original = source.read_bytes()
    link = tmp_path / "combined.json"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"filesystem cannot create symlinks: {exc}")
    with pytest.raises(ValueError, match="must not overwrite"):
        cli.main(["--input", str(source), "--output", str(link)])
    assert source.read_bytes() == original
    assert link.is_symlink()


def test_cli_still_writes_separate_verified_aggregate(tmp_path):
    source = _original_source(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "combined.json"
    assert cli.main([
        "--project-id", "project-a",
        "--input", str(source), "--output", str(output),
    ]) == 0
    assert source.read_bytes() == original
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["project_id"] == "project-a"
    assert [row["quantity_id"] for row in payload["quantities"]] == ["q1"]
    assert cli.load_verified_sealed_run(output).fingerprint == payload["fingerprint"]


def test_cli_atomic_publication_keeps_previous_receipt_if_rename_fails(tmp_path, monkeypatch):
    source = _original_source(tmp_path)
    output = tmp_path / "combined.json"
    output.write_bytes(source.read_bytes())
    previous = output.read_bytes()
    signed_source = source.read_bytes()

    def fail_rename(_source, _destination):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(cli.os, "replace", fail_rename)
    with pytest.raises(OSError, match="simulated publication failure"):
        cli.main(["--input", str(source), "--output", str(output)])
    assert output.read_bytes() == previous
    assert source.read_bytes() == signed_source
    assert not list(tmp_path.glob(".combined.json.*.tmp"))


def test_cli_atomic_publication_leaves_no_staging_file_on_success(tmp_path):
    source = _original_source(tmp_path)
    output = tmp_path / "combined.json"
    assert cli.main(["--input", str(source), "--output", str(output)]) == 0
    assert cli.load_verified_sealed_run(output).project_id == "project-a"
    assert not list(tmp_path.glob(".combined.json.*.tmp"))
