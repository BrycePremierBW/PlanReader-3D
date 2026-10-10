"""Original raster source parent membership is NOT a physical host proof."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from pb_opening_host_binding_authority import _OpeningGeometry
from pb_live_wall_opening_authority_composition import LiveOpeningHostTrace, LiveOpeningHostFrameTrace
from pb_migration_contracts import EvidenceResolutionStatus
from tools.diag_gptmax_raster_host_source_membership import (
    nonpublishing_raster_source_w4_membership,
    original_raster_host_ancestry_census,
)


def opening():
    return _OpeningGeometry(
        origin=(0.,0.), axis=(1.,0.), normal=(0.,1.),
        length=10., thickness=4.,
    )


def source_binding_trace(host_wall_id, *, index=0, reason_codes=()):
    return LiveOpeningHostTrace(
        opening_identity_id=f"opening-{index}", representative_observation_id=f"observation-{index}",
        page_id="3", status=EvidenceResolutionStatus.CORROBORATED if host_wall_id else EvidenceResolutionStatus.ABSTAINED,
        reason_codes=reason_codes, record_id=f"binding-{index}" if host_wall_id else None,
        host_wall_id=host_wall_id, member_wall_candidate_ids=(),
    )


def source_frame_trace(record_id, *, index=0):
    return LiveOpeningHostFrameTrace(
        opening_identity_id=f"opening-{index}",
        status=EvidenceResolutionStatus.CORROBORATED if record_id else EvidenceResolutionStatus.ABSTAINED,
        reason_codes=(), record_id=record_id,
        host_wall_id="host-a" if record_id else None, whole_wall_candidate_ids=(),
    )


def record(id, source_ids, *, usable=True, source_edges=()):
    return SimpleNamespace(
        wall_candidate_id=id,
        physical_identity=SimpleNamespace(
            source_primitive_ids=tuple(source_ids), usable=usable,
        ),
        source_edge_fragments=tuple(
            SimpleNamespace(edge_id=edge_id, source_primitive_ids=tuple(parents))
            for edge_id, parents in source_edges
        ),
    )


def test_positive_exact_source_ancestry_is_never_local_wall_host_authority():
    rows = [
        record("w4-src-a", ["source-a", "source-common"]),
        record("w4-src-b", ["source-b", "source-common"]),
        record("w4-unusable", ["source-unusable"], usable=False),
    ]
    raw = {
        "source-a": (-5.,-1.,0.,-1.),
        "source-b": (10.,1.,14.,1.),
        "source-common": (-3.,0.,14.,0.),
        "source-unusable": (0.,0.,1.,0.),
        "orphan-source": (0.,1.,1.,1.),
        "off-axis-source": (0.,0.,0.,4.),
        "far-source": (50.,0.,60.,0.),
    }
    original = deepcopy(raw)
    report = nonpublishing_raster_source_w4_membership(
        rows, raw, opening(), page_id="3"
    )
    assert raw == original
    evidence={r["source_primitive_id"]:r for r in report["diagnostic_local_raster_lines"]}
    assert evidence["source-common"]["exact_positive_ancestry_w4_candidate_ids"] == [
        "w4-src-a", "w4-src-b"
    ]
    assert evidence["source-a"]["exact_positive_ancestry_w4_candidate_ids"] == ["w4-src-a"]
    assert evidence["source-unusable"]["exact_positive_ancestry_w4_candidate_ids"] == []
    assert evidence["orphan-source"]["exact_positive_ancestry_w4_candidate_ids"] == []
    assert "off-axis-source" not in evidence
    assert "far-source" not in evidence
    assert report["original_source_stage_counts"]["line_not_parallel_to_opening"] == 1
    assert report["original_source_stage_counts"]["line_outside_aperture_local_band"] == 1
    assert report["unusable_identity_source_parent_count"] == 1
    assert not report["local_host_contact_proven"]
    assert not report["physical_equivalence_proven"]
    assert not report["host_publication_allowed"]
    assert not report["opening_count_publication_allowed"]
    assert not report["metric_quantity_publication_allowed"]
    assert report["benchmark_accuracy"] is None


@pytest.mark.parametrize("line", [
    (float("nan"), 0., 1., 0.), (0., float("inf"),1.,0.),
    (0.,0.,1.), ("invalid",0.,1.,0.),
])
def test_bad_original_source_geometry_does_not_create_candidate_ancestry(line):
    result=nonpublishing_raster_source_w4_membership(
        [record("source-owned", ["source"])], {"source":line},
        opening(), page_id="3",
    )
    assert result["original_source_stage_counts"] == {"invalid_source_geometry":1}
    assert result["diagnostic_local_raster_lines"] == []
    assert not result["host_publication_allowed"]


def test_original_w2_source_edge_witnesses_preserve_shared_parent_ambiguity():
    records=[
        record("w4-a", ["common", "only-a"],
               source_edges=(("split-2296", ["common", "only-a"]),)),
        record("w4-b", ["common"],
               source_edges=(("split-9744", ["common"]),)),
        record("w4-c", ["common"],
               source_edges=(("split-9744", ["common"]),)),
    ]
    original=deepcopy(records)
    result=nonpublishing_raster_source_w4_membership(
        records, {"common": (-2.,0.,13.,0.)}, opening(), page_id="3"
    )
    row=result["diagnostic_local_raster_lines"][0]
    assert row["exact_positive_ancestry_w4_candidate_ids"]==[
        "w4-a", "w4-b", "w4-c"
    ]
    assert row["actual_w2_source_edges_by_w4_candidate"]==[
        {"wall_candidate_id":"w4-a","source_edge_id":"split-2296"},
        {"wall_candidate_id":"w4-b","source_edge_id":"split-9744"},
        {"wall_candidate_id":"w4-c","source_edge_id":"split-9744"},
    ]
    assert records==original
    assert not row["locally_authenticated_host"]
    assert not result["host_publication_allowed"]
    assert not result["opening_count_publication_allowed"]


def test_source_parent_without_w2_edge_witness_is_not_silently_fabricated():
    result=nonpublishing_raster_source_w4_membership(
        [record("w4-with-ancestry", ["positive-parent"])],
        {"positive-parent":(-1.,0.,11.,0.)}, opening(), page_id="3"
    )
    row=result["diagnostic_local_raster_lines"][0]
    assert row["exact_positive_ancestry_w4_candidate_ids"]==[
        "w4-with-ancestry"
    ]
    assert row["actual_w2_source_edges_by_w4_candidate"]==[]
    assert not row["locally_authenticated_host"]


def test_duplicate_ancestry_parent_not_counted_as_two_openings_or_host():
    rows=[record("same-physical-id", ["parent", "parent"])]
    data={"parent": (-1.,0.,1.,0.)}
    original = deepcopy((rows, data))
    with pytest.raises(ValueError, match="source primitive parent inventory"):
        nonpublishing_raster_source_w4_membership(rows,data,opening(),page_id="3")
    assert (rows, data) == original


def test_diagnostic_cannot_accept_a_wrong_original_pdf_sha():
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        original_raster_host_ancestry_census(
            b"not-the-original-pdf", page_id="3", expected_source_sha="0"*64,
        )


@pytest.mark.parametrize("page", ["", "-1", "3a", "0"])
def test_bad_original_source_page_rejected_before_processing(page):
    import hashlib
    data=b"fake-input-is-not-a-PDF"
    with pytest.raises(ValueError, match="invalid page"):
        original_raster_host_ancestry_census(
            data, page_id=page,
            expected_source_sha=hashlib.sha256(data).hexdigest(),
        )


def test_w2_source_edge_parent_not_in_w4_identity_is_quarantined_as_contradiction():
    w4 = record(
        "w4-physical-id", ["legitimate-parent"],
        source_edges=(("split-positive", ["legitimate-parent"]),
                      ("split-foreign", ["foreign-parent"])),
    )
    report = nonpublishing_raster_source_w4_membership(
        [w4], {
            "legitimate-parent": (-1.,0.,1.,0.),
            "foreign-parent": (-1.,0.,1.,0.),
        }, opening(), page_id="3"
    )
    by_parent = {
        row["source_primitive_id"]: row
        for row in report["diagnostic_local_raster_lines"]
    }
    assert by_parent["legitimate-parent"][
        "actual_w2_source_edges_by_w4_candidate"
    ] == [{"wall_candidate_id":"w4-physical-id",
           "source_edge_id":"split-positive"}]
    assert by_parent["foreign-parent"][
        "exact_positive_ancestry_w4_candidate_ids"
    ] == []
    assert by_parent["foreign-parent"][
        "actual_w2_source_edges_by_w4_candidate"
    ] == []
    assert report["source_edge_parent_identity_contradiction_count"] == 1
    assert report["source_edge_parent_identity_contradictions"] == [{
        "wall_candidate_id": "w4-physical-id",
        "source_edge_id": "split-foreign",
        "unowned_source_parent_id": "foreign-parent",
    }]
    assert not report["local_host_contact_proven"]
    assert not report["host_publication_allowed"]
    assert not report["metric_quantity_publication_allowed"]


@pytest.mark.parametrize("changes", [
    {"axis": (2., 0.)}, {"normal": (1., 0.)}, {"normal": (0., 0.)},
    {"origin": (float("nan"), 0.)}, {"origin": (0.,)},
    {"length": 0.}, {"thickness": -1.}, {"length": float("inf")},
])
def test_invalid_aperture_basis_cannot_make_geometry_look_local(changes):
    with pytest.raises(ValueError, match="aperture coordinate basis"):
        nonpublishing_raster_source_w4_membership(
            [record("w4-a", ["parent"])], {"parent":(-1.,0.,11.,0.)},
            replace(opening(), **changes), page_id="3",
        )


@pytest.mark.parametrize("line,aperture,reason", [
    ((-1.7e308,0.,1.7e308,0.), opening(), "invalid_source_geometry"),
    ((1.7e308,0.,1.7e308,1.), replace(opening(), origin=(-1.7e308,0.),
        axis=(0.,1.), normal=(-1.,0.)), "nonfinite_source_projection"),
    ((0.,1.7e308,1.,1.7e308), opening(), "nonfinite_source_projection"),
    ((0.,0.,0.,0.), opening(), "invalid_source_geometry"),
])
def test_finite_source_points_cannot_emit_overflowed_local_axis(line, aperture, reason):
    report = nonpublishing_raster_source_w4_membership(
        [record("w4-a", ["parent"])], {"parent":line}, aperture, page_id="3",
    )
    assert report["diagnostic_local_raster_lines"] == []
    assert report["original_source_stage_counts"] == {reason:1}
    json.dumps(report, allow_nan=False)
    assert not report["host_publication_allowed"]


def test_colliding_w4_addresses_cannot_union_two_competing_source_records():
    rows = [record("shared-id", ["parent-a"]), record("shared-id", ["parent-b"]),
            record("independent", ["parent-a"])]
    original = deepcopy(rows)
    source = {"parent-a":(-1.,0.,11.,0.), "parent-b":(-1.,1.,11.,1.)}
    forward = nonpublishing_raster_source_w4_membership(rows, source, opening(), page_id="3")
    reversed_report = nonpublishing_raster_source_w4_membership(
        tuple(reversed(rows)), source, opening(), page_id="3")
    assert forward == reversed_report
    by_parent = {r["source_primitive_id"]:r for r in forward["diagnostic_local_raster_lines"]}
    assert by_parent["parent-a"]["exact_positive_ancestry_w4_candidate_ids"] == ["independent"]
    assert by_parent["parent-b"]["exact_positive_ancestry_w4_candidate_ids"] == []
    assert forward["quarantined_w4_candidate_addresses"] == [{
        "wall_candidate_id":"shared-id", "source_record_count":2,
        "source_parent_ids_by_record":[["parent-a"],["parent-b"]],
    }]
    assert rows == original
    assert not forward["physical_equivalence_proven"]


def test_contradictory_shared_w2_edge_address_is_quarantined_for_every_owner():
    rows = [record("w4-a", ["parent-a"], source_edges=(("same-edge",["parent-a"]),)),
            record("w4-b", ["parent-b"], source_edges=(("same-edge",["parent-b"]),))]
    source = {"parent-a":(-1.,0.,11.,0.), "parent-b":(-1.,1.,11.,1.)}
    result = nonpublishing_raster_source_w4_membership(rows,source,opening(),page_id="3")
    assert result["conflicting_w2_source_edge_addresses"] == ["same-edge"]
    assert all(row["actual_w2_source_edges_by_w4_candidate"] == []
               for row in result["diagnostic_local_raster_lines"])
    assert not result["local_host_contact_proven"]


@pytest.mark.parametrize("identifier", [None, "", " ", 123])
def test_missing_candidate_id_cannot_be_stringified_into_positive_ancestry(identifier):
    with pytest.raises(ValueError, match="candidate address"):
        nonpublishing_raster_source_w4_membership(
            [record(identifier,["parent"])], {"parent":(-1.,0.,11.,0.)},
            opening(),page_id="3",
        )


def geometric_record(cid, parent, eid, geometry):
    row = record(cid, [parent], source_edges=((eid,[parent]),))
    row.source_edge_fragments[0].geometry = geometry
    return row


def test_long_parent_keeps_remote_and_local_w2_fragments_separately_observable():
    rows = [geometric_record("local", "parent", "local-edge", (-3.,0.,0.,0.)),
            geometric_record("remote", "parent", "remote-edge", (70.,0.,80.,0.))]
    original = deepcopy(rows)
    report = nonpublishing_raster_source_w4_membership(
        rows,{"parent":(-5.,0.,100.,0.)},opening(),page_id="3")
    evidence = report["diagnostic_local_raster_lines"][0]
    geometry = {r["wall_candidate_id"]:r
                for r in evidence["w2_source_fragment_geometry_by_w4_candidate"]}
    assert evidence["exact_positive_ancestry_w4_candidate_ids"] == ["local","remote"]
    assert geometry["local"]["within_aperture_diagnostic_band"]
    assert not geometry["remote"]["within_aperture_diagnostic_band"]
    assert geometry["local"]["distance_from_fragment_axis_endpoints_to_aperture_ends_pt"] == [0.,10.]
    assert geometry["remote"]["distance_from_fragment_axis_endpoints_to_aperture_ends_pt"] == [70.,60.]
    assert all(r["source_parent_contains_w2_fragment_geometry"] for r in geometry.values())
    assert all(not r["physical_contact_proven"] for r in geometry.values())
    assert rows == original


@pytest.mark.parametrize("geometry,disposition", [
    (None,"invalid_source_geometry"), ((0.,0.,1.),"invalid_source_geometry"),
    ((0.,0.,0.,0.),"invalid_source_geometry"),
    ((0.,0.,0.,3.),"line_not_parallel_to_opening"),
])
def test_invalid_w2_fragment_geometry_remains_unavailable_despite_positive_parent(geometry, disposition):
    report = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", geometry)],
        {"parent":(-1.,0.,11.,0.)},opening(),page_id="3")
    observation = report["diagnostic_local_raster_lines"][0][
        "w2_source_fragment_geometry_by_w4_candidate"][0]
    assert observation["geometry_disposition"] == disposition
    assert "within_aperture_diagnostic_band" not in observation
    assert not observation["physical_contact_proven"]


def test_local_fragment_without_raw_parent_containment_is_not_source_continuity():
    report = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", (-3.,0.,0.,0.))],
        {"parent":(-1.,0.,11.,0.)}, opening(),page_id="3")
    observation = report["diagnostic_local_raster_lines"][0][
        "w2_source_fragment_geometry_by_w4_candidate"][0]
    assert observation["within_aperture_diagnostic_band"]
    assert not observation["source_parent_contains_w2_fragment_geometry"]
    assert not observation["physical_contact_proven"]


def test_fragment_locality_is_preserved_by_quarter_rotation_and_translation():
    line = (-3.,0.,0.,0.)
    parent = (-5.,0.,100.,0.)
    def transform_line(value):
        return (100.-value[1],200.+value[0],100.-value[3],200.+value[2])
    ordinary = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", line)],
        {"parent":parent},opening(),page_id="3")
    shifted = nonpublishing_raster_source_w4_membership(
        [geometric_record("w4", "parent", "edge", transform_line(line))],
        {"parent":transform_line(parent)},
        replace(opening(),origin=(100.,200.),axis=(0.,1.),normal=(-1.,0.)),page_id="3")
    left = ordinary["diagnostic_local_raster_lines"][0]["w2_source_fragment_geometry_by_w4_candidate"][0]
    right = shifted["diagnostic_local_raster_lines"][0]["w2_source_fragment_geometry_by_w4_candidate"][0]
    for key in ("aperture_axis_span_pt", "aperture_normal_offset_pt",
                "within_aperture_diagnostic_band", "source_parent_contains_w2_fragment_geometry",
                "distance_from_fragment_axis_endpoints_to_aperture_ends_pt"):
        assert left[key] == right[key]


def test_original_source_audit_counts_frame_receipts_and_retains_abstained_attempts(monkeypatch):
    import hashlib
    import tools.diag_gptmax_raster_host_source_membership as diagnostic

    data = b"source-bytes-for-composition-boundary-regression"
    digest = hashlib.sha256(data).hexdigest()
    revision = SimpleNamespace(revision_id="source-revision", document_id="source-document",
                               source_sha256=digest)
    published = SimpleNamespace(revision=revision,
                                snapshot=SimpleNamespace(snapshot_id="source-snapshot"))
    class SourceProducer:
        def __init__(self, **kwargs):
            pass
        def ingest_native_pdf_bytes(self, **kwargs):
            assert kwargs["source_bytes"] == data
            assert kwargs["page_ids"] == ("3",)
            return published
        def published_snapshot_for_revision(self, revision_id):
            assert revision_id == revision.revision_id
            return published

    composition = SimpleNamespace(
        physical_wall_candidate_authority=SimpleNamespace(
            resolve_scope=lambda selector: SimpleNamespace(scope_complete=True, equivalence=object())
        ),
        physical_opening_authority=object(),
        opening_bindings=[
            source_binding_trace("host-a"),
            source_binding_trace("host-b",index=1),
            source_binding_trace(None,index=2,reason_codes=("no_authenticated_host_wall_band",)),
        ],
        host_frames=[source_frame_trace("authenticated-frame"),
                     source_frame_trace(None,index=1), source_frame_trace(None,index=2)],
    )
    original = deepcopy(composition.host_frames)
    monkeypatch.setattr(diagnostic,"SourceVisibilityProducer",SourceProducer)
    monkeypatch.setattr(diagnostic,"compose_live_wall_opening_authority",lambda **kwargs:composition)
    report = diagnostic.original_raster_host_ancestry_census(
        data,page_id="3",expected_source_sha=digest)
    assert report["source_original_opening_count"] == 3
    assert report["source_original_host_count"] == 2
    assert report["source_original_frame_count"] == 1
    assert report["source_original_frame_trace_count"] == 3
    assert composition.host_frames == original
    assert report["opening_bindings"][0]["host_wall_id"] == "host-a"
    assert report["host_frames"][1]["status"] == "abstained"
    assert report["primitive_safety_cap"] == 20_000
    assert not report["host_publication_allowed"]
    assert not report["opening_count_publication_allowed"]
    assert not report["metric_quantity_publication_allowed"]


def test_original_frame_count_excludes_abstained_frame_traces(monkeypatch):
    import hashlib
    import tools.diag_gptmax_raster_host_source_membership as diagnostic

    data=b"source-producer-fixture"
    digest=hashlib.sha256(data).hexdigest()
    revision=SimpleNamespace(document_id="doc",revision_id="rev",source_sha256=digest)
    published=SimpleNamespace(revision=revision,snapshot=SimpleNamespace(snapshot_id="snap"))
    class Producer:
        def __init__(self,**kwargs): pass
        def ingest_native_pdf_bytes(self,**kwargs): return published
        def published_snapshot_for_revision(self,revision_id): return published
    wall=SimpleNamespace(scope_complete=True,equivalence=object(),records=())
    composition=SimpleNamespace(
        physical_wall_candidate_authority=SimpleNamespace(resolve_scope=lambda selector:wall),
        physical_opening_authority=object(),opening_bindings=(),
        host_frames=(source_frame_trace("source-proven-frame"),
                     source_frame_trace(None,index=1),source_frame_trace(None,index=2)),
    )
    monkeypatch.setattr(diagnostic,"SourceVisibilityProducer",Producer)
    monkeypatch.setattr(diagnostic,"compose_live_wall_opening_authority",lambda **kwargs:composition)
    report=original_raster_host_ancestry_census(data,page_id="3",expected_source_sha=digest)
    assert report["source_original_frame_count"]==1
    assert report["source_original_frame_trace_count"]==3
    assert report["host_publication_allowed"] is False

@pytest.mark.parametrize("source_ids", [
    ("valid-source", "valid-source"),
    ("valid-source", ""),
    ("valid-source", "   "),
    ("valid-source", None),
])
def test_invalid_w4_source_parent_inventory_never_grants_ancestry(source_ids):
    with pytest.raises(ValueError, match="invalid W4 source primitive parent inventory"):
        nonpublishing_raster_source_w4_membership(
            [record("w4-a", source_ids)],
            {"valid-source": (-5., -1., 0., -1.)},
            opening(), page_id="3",
        )


@pytest.mark.parametrize("edge_id", ("", "   ", None))
def test_missing_w2_source_edge_identity_never_grants_ancestry(edge_id):
    row = record(
        "w4-a", ("valid-source",),
        source_edges=((edge_id, ("valid-source",)),),
    )
    with pytest.raises(ValueError, match="missing W2 source edge identity"):
        nonpublishing_raster_source_w4_membership(
            [row],
            {"valid-source": (-5., -1., 0., -1.)},
            opening(), page_id="3",
        )


def test_source_snap_loss_is_retained_separately_from_surviving_w2_edge_authority():
    row = geometric_record("w4", "parent", "surviving", (-4.,0.,-1.,0.))
    row.source_snap_collapsed_fragments = (SimpleNamespace(
        edge_id="lost-fragment", source_primitive_ids=("parent",),
        geometry=(-1.,0.,0.,0.), reason_code="both_endpoints_snapped_to_same_node"),)
    original = deepcopy(row)
    result = nonpublishing_raster_source_w4_membership(
        [row], {"parent":(-4.,0.,0.,0.)},opening(),page_id="3")
    evidence = result["diagnostic_local_raster_lines"][0]
    assert evidence["actual_w2_source_edges_by_w4_candidate"] == [
        {"wall_candidate_id":"w4", "source_edge_id":"surviving"}]
    loss = evidence["w2_snap_loss_geometry_by_associated_w4_candidate"][0]
    assert loss["source_edge_id"] == "lost-fragment"
    assert loss["w2_disposition"] == "SNAP_COLLAPSED_NOT_SURVIVING_EDGE"
    assert loss["within_aperture_diagnostic_band"]
    assert loss["distance_from_fragment_axis_endpoints_to_aperture_ends_pt"] == [0.,10.]
    assert not loss["surviving_w2_edge"]
    assert not loss["wall_continuity_proven"]
    assert not loss["physical_contact_proven"]
    assert row == original


@pytest.mark.parametrize("corruption", ["already_surviving", "foreign_parent"])
def test_contradictory_source_snap_loss_never_becomes_an_opening_flank(corruption):
    row = geometric_record("w4", "parent", "surviving", (-4.,0.,-1.,0.))
    row.source_snap_collapsed_fragments = (SimpleNamespace(
        edge_id="surviving" if corruption == "already_surviving" else "lost-fragment",
        source_primitive_ids=("foreign" if corruption == "foreign_parent" else "parent",),
        geometry=(-1.,0.,0.,0.), reason_code="both_endpoints_snapped_to_same_node"),)
    with pytest.raises(ValueError, match="snap-loss"):
        nonpublishing_raster_source_w4_membership(
            [row], {"parent":(-4.,0.,0.,0.)},opening(),page_id="3")
