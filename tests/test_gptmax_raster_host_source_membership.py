"""Original raster source parent membership is NOT a physical host proof."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pb_opening_host_binding_authority import _OpeningGeometry
from tools.diag_gptmax_raster_host_source_membership import (
    nonpublishing_raster_source_w4_membership,
    original_raster_host_ancestry_census,
)


def opening():
    return _OpeningGeometry(
        origin=(0.,0.), axis=(1.,0.), normal=(0.,1.),
        length=10., thickness=4.,
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
    result=nonpublishing_raster_source_w4_membership(rows,data,opening(),page_id="3")
    assert result["diagnostic_local_raster_lines"][0][
        "exact_positive_ancestry_w4_candidate_ids"
    ] == ["same-physical-id"]
    assert not result["opening_count_publication_allowed"]


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
