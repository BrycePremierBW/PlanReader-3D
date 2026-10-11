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
