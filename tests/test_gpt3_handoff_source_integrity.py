"""Fail-closed production handoff gates before source sealing or V2 reporting."""
from dataclasses import replace
import json

import pytest

from test_source_closed_project_handoff import _quantity
from tools import run_source_closed_project_handoff as handoff




def _signed_row_for_fixture(q):
    from types import SimpleNamespace
    return SimpleNamespace(
        quantity_id=q.quantity_id, family=q.family, semantic_key=q.semantic_key,
        value=q.value, unit=q.unit, status=q.status, authority=q.authority,
        confidence=q.confidence, abstained=q.abstained, lineage_ok=True,
        object_identity_refs=tuple(sorted(q.input_entity_ids)),
        evidence_ids=tuple(sorted(q.evidence_ids)),
        blocking_reasons=tuple(sorted(q.blocking_reasons)),
        reason_codes=tuple(sorted(q.reason_codes)),
    )

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
        quantities=(_signed_row_for_fixture(_q("firm")),),to_json=lambda:"{}",
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


def test_original_source_deleted_during_extraction_never_seals(tmp_path,monkeypatch):
    from types import SimpleNamespace
    source=tmp_path/"source.pdf"
    source.write_bytes(b"genuine-original-source")
    output=tmp_path/"out"
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    def disappearing_source(*args,**kwargs):
        source.unlink()
        return SimpleNamespace(
            status="unavailable",reason_codes=(),
            canonical_walls=(),canonical_openings=(),canonical_rooms=(),
            canonical_floors=(),canonical_ceilings=(),canonical_spaces=(),
            opening_quantity_evidence=(),opening_count_quantity_evidence=(),
        )
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",disappearing_source)
    with pytest.raises(RuntimeError,match="source PDF unavailable"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"family_runs").exists()
    assert not (output/"project-a.core.json").exists()
    report=json.loads((output/"production_summary.json").read_text())
    assert report["status"]=="source_unavailable_during_production"
    assert "source_read_failed_during_production" in report["claim_reason_codes"]


@pytest.mark.parametrize("marker",[
    {"shadow_only":"true"},
    {"shadow_only":None},
    {"commercial_projection_allowed":"false"},
    {"commercial_projection_allowed":None},
    {"commercial_projection_allowed":0},
])
def test_nonboolean_publication_permissions_never_count_as_source_authority(marker):
    assert handoff._non_abstained((_q(metadata=marker),))==()


def test_immutable_producer_metadata_cannot_bypass_source_flag_rules():
    from types import MappingProxyType
    q=_q(metadata=MappingProxyType({"is_superseded":True}))
    assert handoff._non_abstained((q,))==()


@pytest.mark.parametrize("code",["source_stale_snapshot","quantity_superseded","wall_host_conflict"])
def test_firm_status_with_stale_or_conflicting_reason_is_not_published(code):
    assert handoff._non_abstained((_q(reason_codes=(code,)),))==()



@pytest.mark.parametrize("sealed_ids", [
    ("qty-forged",),
    ("q-floor","qty-extra-unpublished"),
    (),
])
def test_source_publisher_to_family_seal_quantity_id_bijection(sealed_ids,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    source=tmp_path/"source.pdf"
    source.write_bytes(b"original-verified-source")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    claim=_core_opening_claim()
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",
                        lambda *_args,**_kwargs:claim)
    monkeypatch.setattr(handoff,"seal_live_opening_area_claim_run",
        lambda *_args,**_kwargs:SimpleNamespace(
            run_id="sealed-mutated",
            source_sha256s=(sha,),
            quantities=tuple(
                SimpleNamespace(quantity_id=qid,abstained=False,lineage_ok=True)
                for qid in sealed_ids
            ),
            to_json=lambda:"{}",
        ))
    output=tmp_path/"out"
    with pytest.raises(RuntimeError,match="sealed quantities differ from authenticated publisher receipts"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"family_runs").exists()
    assert not (output/"project-a.core.json").exists()
    report=json.loads((output/"production_summary.json").read_text())
    assert report["status"]=="family_quantity_identity_conflict"
    assert "family_quantity_identity_conflict:opening_area" in report["claim_reason_codes"]


@pytest.mark.parametrize("abstained,lineage_ok",[(True,True),(False,False)])
def test_unpublishable_sealed_row_cannot_ride_firm_family_count(abstained,lineage_ok,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    source=tmp_path/"source.pdf"
    source.write_bytes(b"original-verified-source")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",
                        lambda *_args,**_kwargs:_core_opening_claim())
    monkeypatch.setattr(handoff,"seal_live_opening_area_claim_run",
        lambda *_args,**_kwargs:SimpleNamespace(
            run_id="invalid-firm",source_sha256s=(sha,),to_json=lambda:"{}",
            quantities=(SimpleNamespace(
                quantity_id="q-floor",abstained=abstained,lineage_ok=lineage_ok,
            ),),
        ))
    output=tmp_path/"out"
    with pytest.raises(RuntimeError,match="sealed quantities differ"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"family_runs").exists()



@pytest.mark.parametrize(("field","different"), [
    ("value",99.0),
    ("unit","ea"),
    ("family","unexpected-family"),
    ("semantic_key","forged-semantic"),
    ("authority","unverified"),
    ("confidence",0.5),
    ("object_identity_refs",("other-object",)),
    ("evidence_ids",("forged-evidence",)),
    ("status","candidate"),
])
def test_sealed_quantity_content_cannot_change_under_same_publisher_id(
    field,different,tmp_path,monkeypatch
):
    from types import SimpleNamespace
    import hashlib
    source=tmp_path/"source.pdf"
    source.write_bytes(b"original-verified-source")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",
                        lambda *_args,**_kwargs:_core_opening_claim())
    row=_signed_row_for_fixture(_q("firm"))
    setattr(row,field,different)
    monkeypatch.setattr(handoff,"seal_live_opening_area_claim_run",
        lambda *_args,**_kwargs:SimpleNamespace(
            run_id="misrepresented-producer",
            source_sha256s=(sha,),quantities=(row,),to_json=lambda:"{}",
        ))
    output=tmp_path/"out"
    with pytest.raises(RuntimeError,match="sealed quantities differ from authenticated publisher receipts"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"family_runs").exists()
    summary=json.loads((output/"production_summary.json").read_text())
    assert summary["status"]=="family_quantity_identity_conflict"



def test_combination_conflict_cannot_leave_partially_published_family_seals(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import hashlib
    source=tmp_path/"source.pdf"
    source.write_bytes(b"original-verified-source")
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(handoff,"_source_page_scopes",lambda _:((0,),(),1))
    monkeypatch.setattr(handoff,"collect_live_physical_net_wall_claim",
                        lambda *_args,**_kwargs:_core_opening_claim())
    monkeypatch.setattr(handoff,"seal_live_opening_area_claim_run",
        lambda *_args,**_kwargs:SimpleNamespace(
            run_id="individually-valid",source_sha256s=(sha,),
            quantities=(_signed_row_for_fixture(_q("firm")),),
            to_json=lambda:"{}",
        ))

    def cannot_combine(*args,**kwargs):
        raise RuntimeError("overlapping sealed physical claim")
    monkeypatch.setattr(handoff,"combine_source_closed_runs",cannot_combine)
    output=tmp_path/"out"
    with pytest.raises(RuntimeError,match="overlapping sealed physical claim"):
        handoff.generate_project_handoff(
            pdf_path=source,project_id="project-a",workspace_id=1,
            output_dir=output,family_group="core",
        )
    assert not (output/"family_runs").exists()
    assert not (output/"project-a.core.json").exists()
    summary=json.loads((output/"production_summary.json").read_text())
    assert summary["status"]=="sealed_project_combination_failed"
    assert "sealed_project_combination_error:RuntimeError" in summary["claim_reason_codes"]
