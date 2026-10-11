"""Every targeted opening stays visible, including unavailable source gates."""
import hashlib
from types import SimpleNamespace as NS

import pytest

from pb_live_wall_opening_authority_composition import LiveOpeningHostTrace, LiveOpeningHostFrameTrace
from pb_migration_contracts import EvidenceResolutionStatus as Status
from tools import diag_gptmax_raster_flank_ownership as diagnostic


def trace(identity="opening", *, host=None, reason="raster_source_band_left_source_primitive_unmapped"):
    return LiveOpeningHostTrace(opening_identity_id=identity,
        representative_observation_id="obs-"+identity,page_id="3",status=Status.ABSTAINED,
        reason_codes=(reason,),record_id=None,host_wall_id=host,member_wall_candidate_ids=())


def wall():
    return NS(scope_complete=True,equivalence=object(),document_id="doc",revision_id="rev",
              source_sha256="a"*64,snapshot_id="snap",page_id="3")


@pytest.mark.parametrize("gate",["wall","existence","geometry","identity","support"])
def test_unavailable_source_openings_are_returned_as_abstained_rows(monkeypatch,gate):
    scope=wall()
    opening=NS(record_id="opening",page_id="3",document_id="doc",revision_id="rev",
        source_sha256="a"*64,snapshot_id="snap",source_observation_ids=("g17",))
    receipt=NS(status=Status.ABSTAINED,observation=None)
    visibility=NS(resolve_raster_opening_primitive=lambda selector:receipt)
    result=NS(status=Status.CORROBORATED,existence_record=opening)
    authority=NS(prove_existence=lambda selector:result,source_visibility_authority=lambda:visibility)
    monkeypatch.setattr(diagnostic,"_opening_geometry",lambda *args:object())
    if gate=="wall": scope.scope_complete=False
    elif gate=="existence": result.status=Status.ABSTAINED
    elif gate=="geometry": monkeypatch.setattr(diagnostic,"_opening_geometry",lambda *args:None)
    elif gate=="identity": opening.record_id="different-opening"
    row=diagnostic._opening_row(trace(),authority,scope)
    assert row["source_audit_abstained"] is True
    assert row["opening_identity_id"]=="opening"
    assert row["first_observed_failure"] is not None
    assert row["flank_audit"] is None


def test_top_level_runtime_preserves_every_target_and_excludes_abstained_frames(monkeypatch):
    data=b"synthetic-producer-source"
    digest=hashlib.sha256(data).hexdigest()
    published=NS(revision=NS(document_id="doc",revision_id="rev",source_sha256=digest),
                 snapshot=NS(snapshot_id="snap"))
    class Producer:
        def __init__(self,**kwargs): pass
        def ingest_native_pdf_bytes(self,**kwargs): return published
        def published_snapshot_for_revision(self,*args): return published
    frame=lambda record:LiveOpeningHostFrameTrace(opening_identity_id="z",
        status=Status.ABSTAINED,reason_codes=(),record_id=record,host_wall_id=None,
        whole_wall_candidate_ids=())
    composition=NS(opening_bindings=(trace("z"),trace("a"),trace("hosted",host="host"),
        trace("other",reason="no_authenticated_host_wall_band")),
        host_frames=(frame("original-frame"),frame(None)),physical_opening_authority=object(),
        physical_wall_candidate_authority=NS(resolve_scope=lambda selector:wall()))
    monkeypatch.setattr(diagnostic,"SourceVisibilityProducer",Producer)
    monkeypatch.setattr(diagnostic,"compose_live_wall_opening_authority",lambda **kwargs:composition)
    def row(t,*args):
        return {"opening_identity_id":t.opening_identity_id,"source_audit_abstained":t.opening_identity_id=="a"}
    monkeypatch.setattr(diagnostic,"_opening_row",row)
    report=diagnostic.original_raster_flank_report(data,page_id="3",expected_source_sha=digest)
    assert [r["opening_identity_id"] for r in report["opening_rows"]]==["a","z"]
    assert report["targeted_opening_count"]==2
    assert report["audited_opening_count"]==report["abstained_opening_count"]==1
    assert report["summary"]=={"physical_existence_claims":4,"host_bindings":1,"host_frames":1}
    assert len(report["opening_bindings"])==4 and len(report["host_frames"])==2
    assert report["primitive_safety_cap"]==20000
    assert not report["host_publication_allowed"] and report["benchmark_accuracy"] is None


@pytest.mark.parametrize("page",["0","-1","","٣","not-a-page",3])
def test_bad_source_page_rejects_before_pdf_ingestion(page):
    data=b"not-pdf"
    with pytest.raises(ValueError,match="invalid original source page"):
        diagnostic.original_raster_flank_report(data,page_id=page,
            expected_source_sha=hashlib.sha256(data).hexdigest())


def test_wrong_source_hash_cannot_enter_the_original_pipeline():
    with pytest.raises(ValueError,match="SHA-256 mismatch"):
        diagnostic.original_raster_flank_report(b"fake",page_id="3",expected_source_sha="0"*64)
