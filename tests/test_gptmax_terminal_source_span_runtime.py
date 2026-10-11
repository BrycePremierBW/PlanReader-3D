"""Runtime source association observes original producer objects without promotion."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import os

import pytest

from tools import diag_gptmax_terminal_source_span_shadow as diagnostic


@dataclass(frozen=True)
class Wall:
    candidate_id: str = "wall_alpha"
    viewport_id: str = "source-page-one"
    face_a_segment_ids: tuple = ("edge_surviving",)


@dataclass(frozen=True)
class Identity:
    wall_candidate_id: str = "wall_alpha"
    viewport_id: str = "source-page-one"
    candidate_identity_id: str = "wall2_existing_source_candidate"
    source_primitive_ids: tuple = ("source_positive",)
    edge_ids: tuple = ("edge_surviving",)
    status: str = "corroborated"


def install_source_call(monkeypatch, corruption=None):
    source = b"original source owned runtime fixture"
    walls, identities = [Wall()], {"wall_alpha": Identity()}
    if corruption == "producer_collision":
        walls.append(Wall(face_a_segment_ids=("distinct_split_source_edge",)))
    graph = {
        "nodes": [{"id": 0, "x": 0., "y": 0.}, {"id": 1, "x": 10., "y": 0.}],
        "edges": [{"id": "edge_surviving", "a": 0, "b": 1,
                   "x1": 0., "y1": 0., "x2": 10., "y2": 0.,
                   diagnostic.wall_authority.LINEAGE_KEY: {"source_primitive_ids": ["source_positive"]}}],
        "short_source_fragment_retention_audit": {
            "original_positive_source_short_fragments": [{
                "source_split_fragment_id": "split_lost",
                "positive_source_primitive_id": "source_positive",
                "w2_observation": "SNAP_COLLAPSED", "snapped_endpoint_node_ids": [1, 1],
                "original_source_geometry_pt": [10., 0., 11.25, 0.],
            }],
        },
    }
    outputs = {}

    def build(segments):
        assert os.environ["GPTMAX_W2_SHORT_SOURCE_AUDIT"] == "1"
        assert segments == [{"id": "source_positive"}]
        return graph

    def collect(actual_walls, actual_graph):
        assert actual_walls is walls and actual_graph is graph
        return identities

    def source_report(data, *, page_ids):
        assert data == source and page_ids == ("1",)
        actual_graph = diagnostic.wall_authority.build_wall_graph_for_viewport([{"id": "source_positive"}])
        if corruption == "duplicate_graph":
            diagnostic.wall_authority.build_wall_graph_for_viewport([{"id": "source_positive"}])
        if corruption == "unobserved_graph":
            actual_graph = deepcopy(graph)
        if corruption != "missing_identity_call":
            observed = diagnostic.wall_authority.collect_physical_wall_identities(walls, actual_graph)
            assert observed is identities
        if corruption == "duplicate_identity_call":
            diagnostic.wall_authority.collect_physical_wall_identities(walls, actual_graph)
        scope = {
            "document_id": "original-source-document", "source_sha256": hashlib.sha256(source).hexdigest(),
            "page_id": "1", "revision_id": "original-revision", "snapshot_id": "original-snapshot",
            "decision_scope_id": "source-page-one", "records": [{
                "wall_candidate_id": "wall_alpha", "wall_candidate": asdict(walls[0]),
                "physical_identity": asdict(identities["wall_alpha"]),
                "source_edge_fragments": ({
                    "edge_id": "edge_surviving", "geometry": (0., 0., 10., 0.),
                    "source_primitive_ids": ("source_positive",),
                },),
            }],
        }
        report = {
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "selected_geometry_page_ids": ("1",), "primitive_safety_cap": 20_000,
            "revision_id": "original-revision", "snapshot_id": "original-snapshot",
            "source_decode_coverage": {"document_id": "original-source-document", "revision_id": "original-revision"},
            "source_owned_wall_scope_results": [scope],
            "summary": {"physical_existence_claims": 0, "host_bindings": 0, "host_frames": 0},
        }
        if corruption == "producer_collision":
            second = deepcopy(scope["records"][0])
            second["wall_candidate"] = asdict(walls[1])
            scope["records"].append(second)
        if corruption == "report_source":
            report["source_sha256"] = "0" * 64
        elif corruption == "cap":
            report["primitive_safety_cap"] = 25_000
        elif corruption == "selected_pages":
            report["selected_geometry_page_ids"] = ("2",)
        elif corruption == "coverage_revision":
            report["source_decode_coverage"]["revision_id"] = "foreign"
        elif corruption in {"document_id", "source_sha256", "revision_id", "snapshot_id", "page_id"}:
            scope[corruption] = "foreign"
        elif corruption == "missing_scope":
            report["source_owned_wall_scope_results"] = []
        elif corruption == "duplicate_scope":
            report["source_owned_wall_scope_results"].append(deepcopy(scope))
        elif corruption == "duplicate_record":
            scope["records"].append(deepcopy(scope["records"][0]))
        elif corruption == "foreign_record":
            scope["records"][0]["wall_candidate_id"] = "wall_elsewhere"
        elif corruption == "changed_identity":
            scope["records"][0]["physical_identity"]["candidate_identity_id"] = "wall2_foreign"
        elif corruption == "changed_source_geometry":
            scope["records"][0]["source_edge_fragments"][0]["geometry"] = (0., 0., 9., 0.)
        outputs["source_report"] = report
        return report

    monkeypatch.setenv("GPTMAX_W2_SHORT_SOURCE_AUDIT", "prior-value")
    monkeypatch.setattr(diagnostic.wall_authority, "build_wall_graph_for_viewport", build)
    monkeypatch.setattr(diagnostic.wall_authority, "collect_physical_wall_identities", collect)
    monkeypatch.setattr(diagnostic, "source_face_report", source_report)
    return source, graph, walls, identities, outputs, build, collect


def test_actual_producer_call_and_scope_linkage_never_replace_graph_identity_or_report(monkeypatch):
    source, graph, walls, identities, outputs, build, collect = install_source_call(monkeypatch)
    before = deepcopy((graph, walls, identities))
    result = diagnostic.terminal_source_span_shadow_report(source, page_ids=("1",))
    assert (graph, walls, identities) == before
    assert result["source_report"] is outputs["source_report"]
    assert diagnostic.wall_authority.build_wall_graph_for_viewport is build
    assert diagnostic.wall_authority.collect_physical_wall_identities is collect
    assert os.environ["GPTMAX_W2_SHORT_SOURCE_AUDIT"] == "prior-value"
    row = result["source_assembly_call_previews"][0]
    assert row["same_producer_graph_and_identity_call_observed"] is True
    assert row["original_scope_records_match_observed_call"] is True
    assert row["source_scope_provenance"]["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert len(row["terminal_source_path_preview"]["source_path_previews"]) == 1
    assert result["physical_equivalence_proven"] is False
    assert result["graph_identity_host_frame_quantity_mutation_allowed"] is False
    assert result["benchmark_accuracy"] is None


@pytest.mark.parametrize("corruption", [
    "duplicate_graph", "unobserved_graph", "missing_identity_call", "duplicate_identity_call",
    "report_source", "cap", "selected_pages", "document_id", "coverage_revision", "source_sha256", "revision_id", "snapshot_id",
    "page_id", "missing_scope", "duplicate_scope", "duplicate_record", "foreign_record",
    "changed_identity", "changed_source_geometry",
])
def test_missing_duplicate_or_foreign_runtime_association_fails_closed_and_restores_state(monkeypatch, corruption):
    source, graph, walls, identities, outputs, build, collect = install_source_call(monkeypatch, corruption)
    before = deepcopy((graph, walls, identities))
    with pytest.raises(RuntimeError):
        diagnostic.terminal_source_span_shadow_report(source, page_ids=("1",))
    assert (graph, walls, identities) == before
    assert diagnostic.wall_authority.build_wall_graph_for_viewport is build
    assert diagnostic.wall_authority.collect_physical_wall_identities is collect
    assert os.environ["GPTMAX_W2_SHORT_SOURCE_AUDIT"] == "prior-value"


def test_identical_repeated_producer_candidate_rows_keep_original_multiplicity():
    """Never silently suppress producer duplicates during source receipt comparison."""
    walls = [Wall(), Wall()]
    identities = {"wall_alpha": Identity()}
    graph = {"edges": [{
        "id": "edge_surviving", "x1": 0., "y1": 0., "x2": 10., "y2": 0.,
        diagnostic.wall_authority.LINEAGE_KEY: {
            "source_primitive_ids": ["source_positive"],
        },
    }]}
    before = deepcopy((walls, identities, graph))
    unique = diagnostic._records_from_original_call(walls[:1], identities, graph)
    observed = diagnostic._records_from_original_call(walls, identities, graph)
    assert observed == unique + unique
    assert len(observed) == 2
    assert (walls, identities, graph) == before


def test_conflicting_duplicate_producer_candidate_cannot_be_normalized():
    walls = [Wall(), Wall(face_a_segment_ids=("a_different_source_edge",))]
    graph = {"edges": [{
        "id": "edge_surviving", "x1": 0., "y1": 0., "x2": 10., "y2": 0.,
        diagnostic.wall_authority.LINEAGE_KEY: {
            "source_primitive_ids": ["source_positive"],
        },
    }]}
    before = deepcopy((walls, graph))
    rows = diagnostic._records_from_original_call(
        walls, {"wall_alpha": Identity()}, graph)
    assert len(rows) == 2
    assert rows[0]["wall_candidate"] != rows[1]["wall_candidate"]
    assert (walls, graph) == before


def test_realistic_conflicting_candidate_id_quarantines_entire_scope(monkeypatch):
    source, graph, walls, identities, outputs, build, collect = install_source_call(
        monkeypatch, "producer_collision")
    before = deepcopy((graph, walls, identities))
    result = diagnostic.terminal_source_span_shadow_report(source, page_ids=("1",))
    assert result["source_report"] is outputs["source_report"]
    assert result["quarantined_source_scope_count"] == 1
    row = result["source_assembly_call_previews"][0]
    assert row["quarantined_collision_candidate_ids"] == ["wall_alpha"]
    assert row["source_scope_collision_quarantined"] is True
    assert row["original_identity_count"] == 2
    preview = row["terminal_source_path_preview"]
    assert preview["source_path_previews"] == []
    assert preview["disposition_counts"] == {
        "source_identity_collision_scope_quarantined": 1}
    assert preview["host_count_quantity_publication_allowed"] is False
    assert result["benchmark_accuracy"] is None
    assert (graph, walls, identities) == before
    assert diagnostic.wall_authority.build_wall_graph_for_viewport is build
    assert diagnostic.wall_authority.collect_physical_wall_identities is collect


def test_foreign_or_missing_identity_not_silently_reconciled():
    with pytest.raises(RuntimeError, match="foreign or missing"):
        diagnostic._records_from_original_call(
            [Wall()], {"wall_beta": Identity()}, {"edges": []})
