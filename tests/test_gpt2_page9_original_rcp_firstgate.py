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


def test_gpt2_source_viewport_type_token_matches_string_and_producer_enum():
    from tools.diag_gpt2_page9_original_rcp_firstgate import _producer_token
    from pb_drawing_evidence_binding import DrawingViewType
    from enum import Enum

    class Status(Enum):
        RESOLVED="resolved"

    assert _producer_token(DrawingViewType.REFLECTED_CEILING_PLAN)==(
        "reflected_ceiling_plan"
    )
    assert _producer_token("reflected_ceiling_plan")=="reflected_ceiling_plan"
    assert _producer_token(Status.RESOLVED)=="resolved"
    assert _producer_token(None)==""
    assert _producer_token(73)==""


def test_gpt2_original_and_proposed_rcp_title_anchors_cannot_cross_bind():
    from tools.diag_gpt2_page9_original_rcp_firstgate import _title_identity

    assert _title_identity("REFLECTED CEILING PLAN", "Reflected  Ceiling Plan")
    assert not _title_identity(
        "ORIGINAL REFLECTED CEILING PLAN", "PROPOSED REFLECTED CEILING PLAN"
    )
    assert not _title_identity("", "REFLECTED CEILING PLAN")
    assert not _title_identity(None, "REFLECTED CEILING PLAN")
    assert not _title_identity("RCP", 3)
