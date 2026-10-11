"""Instrument the source call without mutating graph or environment state."""
from copy import deepcopy
import hashlib
import os

import pytest

from tools import diag_gptmax_w2_short_fragment_retention as diagnostic


def test_source_wrapper_observes_the_actual_graph_and_restores_environment(monkeypatch):
    source_bytes = b"source-owned diagnostic fixture"
    source_report = {"source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                     "summary": {"host_bindings": 0}, "wall_scopes": []}
    audit = {"physical_host_publication_allowed": False,
             "original_positive_source_short_fragments": []}
    graph = {"nodes": [], "edges": [], "adjacency": {},
             "short_source_fragment_retention_audit": audit}
    original_graph = deepcopy(graph)
    calls = []

    def build_graph(segments, **kwargs):
        calls.append((deepcopy(segments), kwargs))
        assert os.environ["GPTMAX_W2_SHORT_SOURCE_AUDIT"] == "1"
        return graph

    def source_face_report(data, *, page_ids):
        assert data == source_bytes and page_ids == ("3",)
        assert diagnostic.wall_authority.build_wall_graph_for_viewport(
            [{"id": "owned-source"}], gap_snap_tolerance_pt=2.5) is graph
        return source_report

    monkeypatch.setenv("GPTMAX_W2_SHORT_SOURCE_AUDIT", "prior-value")
    monkeypatch.setattr(diagnostic.wall_authority, "build_wall_graph_for_viewport", build_graph)
    monkeypatch.setattr(diagnostic, "source_face_report", source_face_report)
    result = diagnostic.short_fragment_source_report(source_bytes, page_ids=("3",))
    assert result["source_report"] is source_report
    assert len(calls) == len(result["w2_graph_audits"]) == 1
    assert result["w2_graph_audits"][0]["short_source_fragment_retention_audit"] is audit
    assert graph == original_graph
    assert os.environ["GPTMAX_W2_SHORT_SOURCE_AUDIT"] == "prior-value"
    assert diagnostic.wall_authority.build_wall_graph_for_viewport is build_graph
    assert result["host_count_quantity_publication_allowed"] is False
    assert result["physical_equivalence_proven"] is False
    assert result["benchmark_accuracy"] is None


@pytest.mark.parametrize("call_graph", [True, False])
def test_missing_actual_trace_is_unavailable_and_restores_instrumentation(monkeypatch, call_graph):
    def build_graph(segments):
        return {"nodes": [], "edges": []}

    def source_face_report(data, *, page_ids):
        if call_graph:
            diagnostic.wall_authority.build_wall_graph_for_viewport([])
        return {}

    monkeypatch.delenv("GPTMAX_W2_SHORT_SOURCE_AUDIT", raising=False)
    monkeypatch.setattr(diagnostic.wall_authority, "build_wall_graph_for_viewport", build_graph)
    monkeypatch.setattr(diagnostic, "source_face_report", source_face_report)
    with pytest.raises(RuntimeError, match="unavailable|no observable"):
        diagnostic.short_fragment_source_report(b"source", page_ids=("3",))
    assert "GPTMAX_W2_SHORT_SOURCE_AUDIT" not in os.environ
    assert diagnostic.wall_authority.build_wall_graph_for_viewport is build_graph
