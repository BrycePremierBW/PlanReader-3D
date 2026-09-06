"""tests/geometry/test_finish_tags_and_schedules.py — Tests for finish tag mapping and paint scope disposition."""
from pb_geometry_takeoff_model import classify_finish_tag


def test_external_cladding_tags_included():
    for tag in ["EC01", "EC02", "EC03", "EC04", "ec01", " EC02 "]:
        record = classify_finish_tag(tag)
        assert record.scope_disposition == "included"
        assert record.paintable_status == "PAINTABLE_INCLUDED"

    for tag in ["EC1", "EC2", "EC3", "EC4"]:
        record = classify_finish_tag(tag)
        assert record.scope_disposition == "included"
        assert record.paintable_status == "PAINTABLE_INCLUDED"


def test_external_finishes_and_paint_tags():
    for tag in ["XF01", "XF02", "XF03", "XP01"]:
        record = classify_finish_tag(tag)
        assert record.scope_disposition == "included"
        assert record.paintable_status == "PAINTABLE_INCLUDED"


def test_internal_plasterboard_tags():
    for tag in ["P", "PB01", "PB02", "PB04", "PB05", "SHD"]:
        record = classify_finish_tag(tag)
        assert record.scope_disposition == "included"
        assert record.paintable_status == "PAINTABLE_INCLUDED"


def test_provisional_render_tag():
    record = classify_finish_tag("RBL")
    assert record.scope_disposition == "provisional"
    assert record.paintable_status == "PROVISIONAL_RENDER"
    assert "provisional" in record.notes.lower()


def test_excluded_trade_and_factory_tags():
    # Sealants, screeds, pre-painted timber, colorbond, aluminium joinery
    for tag in ["SL", "SCR", "PPT", "COLORBOND", "ALUM"]:
        record = classify_finish_tag(tag)
        assert record.scope_disposition == "excluded"
        assert record.paintable_status == "EXCLUDED_FACTORY"


def test_keyword_heuristics_for_excluded_finishes():
    # Powdercoat, colorbond roof, gutters, glazing
    for desc in ["COLORBOND ROOF", "METAL GUTTER", "FASCIA CAPPING", "POWDERCOATED SCREEN", "ANODISED LOUVRE", "DOUBLE GLAZING"]:
        record = classify_finish_tag(desc)
        assert record.scope_disposition == "excluded"
        assert record.paintable_status == "EXCLUDED_FACTORY"


def test_unknown_tag_fails_closed_to_review_required():
    for tag in ["UNKNOWN_SPECIAL_99", "CUSTOM_ACID_ETCH", "SPEC_XYZ"]:
        record = classify_finish_tag(tag)
        assert record.scope_disposition == "review_required"
        assert record.paintable_status == "REVIEW_REQUIRED"
        assert "estimator" in record.notes.lower()
