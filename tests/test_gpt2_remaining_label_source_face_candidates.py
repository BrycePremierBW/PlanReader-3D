"""Native room text/physical face proximity remains untrusted."""
from types import SimpleNamespace
from tools.diag_gpt2_remaining_label_source_face_candidates import (
    source_label_face_candidates as classify,
)

def face(record_id, polygon):
    return SimpleNamespace(record_id=record_id, polygon_pdf_pts=polygon)

BOX=((0.,0.),(100.,0.),(100.,100.),(0.,100.))

def test_single_source_face_is_spatial_candidate_not_owner():
    row=classify((30.,30.,40.,40.),(face("one",BOX),))
    assert row["first_source_face_gate"]=="single_source_face_spatial_candidate_only"
    assert row["sampled_box_face_record_ids"]==["one"]
    assert row["source_room_label_authenticated"] is False
    assert row["metric_area_published"] is False

def test_competing_nested_faces_fail_closed():
    row=classify((30.,30.,40.,40.),(
        face("outer",BOX),
        face("inner",((20.,20.),(50.,20.),(50.,50.),(20.,50.))),
    ))
    assert row["first_source_face_gate"]=="competing_source_faces_for_full_native_label_samples"
    assert row["sampled_box_face_record_ids"]==["inner","outer"]
    assert row["source_face_to_label_ownership_proven"] is False

def test_center_only_is_insufficient():
    row=classify((80.,40.,120.,60.),(face("one",BOX),))
    assert row["first_source_face_gate"]=="native_label_centre_only_or_split_face_candidate"
    assert row["sampled_box_face_record_ids"]==[]
    assert row["centre_face_record_ids"]==["one"]

def test_outside_source_faces_stays_unowned():
    row=classify((120.,120.,140.,140.),(face("one",BOX),))
    assert row["first_source_face_gate"]=="native_label_outside_source_room_faces"
    assert row["centre_face_record_ids"]==[]

def test_malformed_bbox_or_unusable_face_abstains():
    invalid_boxes=(None,(),(0.,0.,1.),(0.,0.,0.,1.),("bad",0,2,2))
    for bbox in invalid_boxes:
        assert classify(bbox,(face("one",BOX),))["first_source_face_gate"]=="native_label_bbox_unavailable"
    row=classify((10.,10.,20.,20.),(
        face("broken",((0.,0.),)),
        face("unknown",None),
    ))
    assert row["first_source_face_gate"]=="native_label_outside_source_room_faces"
    assert sorted(row["invalid_source_face_record_ids"])==["broken","unknown"]

def test_duplicate_same_face_receipt_not_multiple_physical_owners():
    duplicate=face("face-one",BOX)
    row=classify((30.,30.,40.,40.),(duplicate,duplicate))
    assert row["sampled_box_face_record_ids"]==["face-one"]
    assert row["source_room_label_authenticated"] is False


def test_conflicting_source_face_receipt_geometry_never_owns_native_room_label():
    # Two producer rows under one source receipt cannot be silently collapsed
    # into a single authentic room, even if both geometries contain the label.
    first=face("duplicate-source-id", BOX)
    competing=face("duplicate-source-id",(
        (20.,20.),(80.,20.),(80.,80.),(20.,80.)
    ))
    actual=classify((30.,30.,40.,40.),(first,competing))
    assert actual["first_source_face_gate"]=="source_face_receipt_geometry_conflict"
    assert actual["ambiguous_source_face_record_ids"]==["duplicate-source-id"]
    assert actual["centre_face_record_ids"]==[]
    assert actual["sampled_box_face_record_ids"]==[]
    assert actual["source_room_label_authenticated"] is False
    assert actual["metric_area_published"] is False
    # Exact source record replay is idempotent and stays only a candidate.
    replay=classify((30.,30.,40.,40.),(first,face("duplicate-source-id",BOX)))
    assert replay["first_source_face_gate"]=="single_source_face_spatial_candidate_only"
    assert replay["sampled_box_face_record_ids"]==["duplicate-source-id"]


def test_invalid_source_face_receipts_and_overflowing_native_geometry_abstain():
    for invalid in (None, 73, "", " ", "source-id "):
        row=classify((30.,30.,40.,40.),(
            face(invalid, BOX),
        ))
        assert row["centre_face_record_ids"]==[]
        assert row["sampled_box_face_record_ids"]==[]
        assert not row["source_room_label_authenticated"]
    row=classify((30.,30.,40.,40.),(
        face("overgrown",((10**500,0),(10,0),(10,10))),
    ))
    assert row["first_source_face_gate"]=="native_label_outside_source_room_faces"
    assert row["invalid_source_face_record_ids"]==["overgrown"]
    row=classify((0,0,10**500,10.),(face("one",BOX),))
    assert row["first_source_face_gate"]=="native_label_bbox_unavailable"
