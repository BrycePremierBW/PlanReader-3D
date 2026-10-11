"""Fail-closed production handoff gates before source sealing or V2 reporting."""
from dataclasses import replace
import json

import pytest

from test_source_closed_project_handoff import _quantity
from tools import run_source_closed_project_handoff as handoff


def _q(status="firm", **overrides):
    return replace(_quantity("q-floor", "floor_area"), status=status, **overrides)


@pytest.mark.parametrize("valid", ["firm", "corroborated"])
def test_only_authenticated_positive_source_states_enter_handoff(valid):
    q=_q(valid)
    assert handoff._non_abstained((q,))==(q,)


@pytest.mark.parametrize("nonpublishable", [
    "candidate", "provisional", "partial", "pending", "unresolved",
    "unsupported", "abstained", "stale", "conflict", "shadow",
])
def test_numeric_nonfirm_quantity_never_becomes_sealable(nonpublishable):
    assert handoff._non_abstained((_q(nonpublishable),))==()


def test_source_reason_conflict_blocks_even_corroborated_quantity():
    assert handoff._non_abstained((_q("corroborated",reason_codes=("source_conflict",)),))==()


def test_non_abstained_quantity_with_unclosed_source_blocker_is_omitted():
    assert handoff._non_abstained((_q(blocking_reasons=("source_unavailable",)),))==()


@pytest.mark.parametrize("marker", [
    {"shadow_only":True},
    {"commercial_projection_allowed":False},
    {"is_stale":True},
    {"is_superseded":True},
    {"is_superseded":"true"},
])
def test_noncommercial_and_stale_source_metadata_does_not_get_sealed(marker):
    assert handoff._non_abstained((_q(metadata=marker),))==()


def test_explicit_original_current_flags_do_not_suppress_firm():
    q=_q(metadata={"shadow_only":False, "commercial_projection_allowed":True,
                   "is_stale":False,"is_superseded":False})
    assert handoff._non_abstained((q,))==(q,)


@pytest.mark.parametrize("bad_workspace", [True,False,0,-1,1.5,1.0,"1",None])
def test_invalid_workspace_never_enters_production_handoff(tmp_path,bad_workspace):
    source=tmp_path/"source.pdf"
    source.write_bytes(b"source")
    output=tmp_path/"out"
    with pytest.raises(ValueError,match="workspace_id"):
        handoff.generate_project_handoff(pdf_path=source,project_id="project-1",
                                         workspace_id=bad_workspace,output_dir=output)
    assert not output.exists()


@pytest.mark.parametrize("unsafe", [
    "../escape", "subdir/id", "subdir\\id", ".", "..", " id", "id ", "",
    "bad\nproject", "bad:project", None, 123, True,
])
def test_bad_project_id_cannot_address_another_handoff(tmp_path,unsafe):
    source=tmp_path/"source.pdf"
    source.write_bytes(b"source")
    output=tmp_path/"out"
    with pytest.raises(ValueError,match="filename-safe source identity"):
        handoff.generate_project_handoff(pdf_path=source,project_id=unsafe,
                                         workspace_id=1,output_dir=output)
    assert not output.exists()


def test_source_bytes_replaced_during_extraction_never_produce_a_seal(tmp_path,monkeypatch):
    source=tmp_path/"source.pdf"
    source.write_bytes(b"original-authenticated-source")
    output=tmp_path/"out"
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda path: ((0,),(),1))

    class Claim:
        status="abstained"
        reason_codes=()
        canonical_walls=()
        canonical_openings=()
        canonical_rooms=()
        canonical_floors=()
        canonical_ceilings=()
        canonical_spaces=()
        floor_finish_quantity_evidence=()
        opening_quantity_evidence=()
        opening_count_quantity_evidence=()

    def replacement(*args,**kwargs):
        source.write_bytes(b"modified-source-after-original-sha")
        return Claim()

    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",replacement)
    with pytest.raises(RuntimeError,match="source PDF SHA changed"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-1",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"project-1.json").exists()
    assert not (output/"family_runs").exists()
    report=json.loads((output/"production_summary.json").read_text())
    assert report["status"]=="source_changed_during_production"
    assert "source_sha_changed" in report["claim_reason_codes"]
    assert report["combined_run_file"] is None



def _core_opening_claim():
    from types import SimpleNamespace
    return SimpleNamespace(
        status=SimpleNamespace(value="corroborated"),reason_codes=(),
        canonical_walls=(),canonical_openings=(),canonical_rooms=(),
        canonical_floors=(),canonical_ceilings=(),canonical_spaces=(),
        opening_quantity_evidence=(_q("firm"),),
        opening_count_quantity_evidence=(),
    )


def test_family_with_extra_source_digest_does_not_leave_seal_files(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    source=tmp_path/"source.pdf"
    source.write_bytes(b"genuine-original-source")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    claimed=_core_opening_claim()
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",
                        lambda *_args,**_kwargs:claimed)
    monkeypatch.setattr(handoff,"seal_live_opening_area_claim_run",
        lambda *_args,**_kwargs:SimpleNamespace(
            run_id="forged-two-source-run",
            source_sha256s=(sha,"b"*64),
            quantities=(),to_json=lambda:"{}",
        ))
    output=tmp_path/"out"
    with pytest.raises(RuntimeError,match="conflicting source SHA envelope"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"family_runs").exists()
    assert not (output/"project-a.core.json").exists()
    summary=json.loads((output/"production_summary.json").read_text())
    assert summary["status"]=="source_envelope_conflict"
    assert "sealed_source_envelope_conflict:opening_area" in summary["claim_reason_codes"]


def test_combined_source_envelope_conflict_never_writes_project_handoff(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    source=tmp_path/"source.pdf"
    source.write_bytes(b"genuine-original-source")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    claimed=_core_opening_claim()
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",
                        lambda *_args,**_kwargs:claimed)
    run=SimpleNamespace(
        run_id="valid-family",source_sha256s=(sha,),
        quantities=(),to_json=lambda:"{}",
    )
    monkeypatch.setattr(handoff,"seal_live_opening_area_claim_run",
                        lambda *_args,**_kwargs:run)
    monkeypatch.setattr(handoff,"combine_source_closed_runs",
        lambda *_args,**_kwargs:SimpleNamespace(
            run_id="tampered-combination",
            source_sha256s=(sha,"b"*64),
            quantities=(),to_json=lambda:"{}",
        ))
    output=tmp_path/"out"
    with pytest.raises(RuntimeError,match="combined sealed run has conflicting"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"project-a.core.json").exists()
    summary=json.loads((output/"production_summary.json").read_text())
    assert summary["status"]=="source_envelope_conflict"
    assert "combined_source_envelope_conflict" in summary["claim_reason_codes"]
