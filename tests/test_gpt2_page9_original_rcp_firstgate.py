import pytest
from tools.diag_gpt2_page9_original_rcp_firstgate import audit

def test_wrong_source_sha_must_fail_before_viewport_detection():
    with pytest.raises(ValueError,match="source_sha_mismatch"):
        audit(b"unrelated source bytes")

def test_source_page_universe_must_be_31(monkeypatch):
    from tools import diag_gpt2_page9_original_rcp_firstgate as module
    import hashlib
    monkeypatch.setattr(module, "SOURCE_SHA", hashlib.sha256(b"test").hexdigest())
    import fitz
    doc = fitz.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()
    monkeypatch.setattr(module, "SOURCE_SHA", hashlib.sha256(payload).hexdigest())
    with pytest.raises(ValueError, match="source_page_universe_mismatch"):
        audit(payload)


def test_gpt2_rcp_nearest_original_vector_frame_never_grants_ownership():
    from tools.diag_gpt2_page9_original_rcp_firstgate import (
        _nearest_native_frames_to_title,
    )
    source_title=(0.,0.,10.,10.)
    frames=(
        (14.,0.,24.,10.),
        (10.,0.,20.,10.),
        (200.,200.,300.,300.),
    )
    rows=_nearest_native_frames_to_title(source_title,frames)
    assert len(rows)==3
    assert [r["title_to_frame_native_distance_pdf_pts"] for r in rows]==[
        0.0,4.0,268.700577
    ]
    assert all(r["original_vector_frame_not_title_owned"] for r in rows)


def test_gpt2_rcp_nearby_native_frame_unavailable_when_geometry_bad():
    from tools.diag_gpt2_page9_original_rcp_firstgate import (
        _nearest_native_frames_to_title,
    )
    assert _nearest_native_frames_to_title(None,())==[]
    assert _nearest_native_frames_to_title((0,0,0,10),((0,0,5,5),))==[]
    assert _nearest_native_frames_to_title((0,0,10,10),(
        (1,1,float("nan"),5),(1,1,0,5),("bad",1,2,3)
    ))==[]
