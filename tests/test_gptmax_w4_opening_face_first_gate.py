"""Read-only W4 first-gate diagnostic cannot infer physical/commercial authority."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib

import pytest

from pb_source_visibility_authority import (
    NATIVE_PDF_VISIBLE_SEGMENT,
    RASTER_PDF_VISIBLE_SEGMENT,
)
from pb_wall_room_topology_primitive_lineage import LINEAGE_KEY
from tools import diag_gptmax_w4_opening_face_first_gate as diag


@dataclass(frozen=True)
class Observation:
    observation_kind: str
    source_primitive_ref: str | None


@pytest.mark.parametrize(("kind", "ref", "expected"), [
    (NATIVE_PDF_VISIBLE_SEGMENT, "visible:segment:native-1", "native-1"),
    (RASTER_PDF_VISIBLE_SEGMENT, "visible:raster-1", "raster-1"),
    (NATIVE_PDF_VISIBLE_SEGMENT, "visible:raster-1", None),
    (RASTER_PDF_VISIBLE_SEGMENT, "segment:native-1", None),
    ("ocr_text", "visible:segment:native-1", None),
    (NATIVE_PDF_VISIBLE_SEGMENT, None, None),
])
def test_only_owned_visible_primitive_refs_are_traceable(kind, ref, expected):
    assert diag.raw_id_for_observation(Observation(kind, ref)) == expected


def test_w2_source_lineage_census_is_read_only_deterministic_and_no_host_claim():
    graph = {"edges": [
        {"id": "w2-1", LINEAGE_KEY: {"source_primitive_ids": ["raw-b", "raw-a"]}},
        {"id": "w2-2", LINEAGE_KEY: {"source_primitive_ids": ["raw-a"]}},
        {"id": "w2-3", LINEAGE_KEY: {"source_primitive_ids": []}},
    ]}
    original = deepcopy(graph)
    output = diag.edge_lineage_raw_ids(graph)
    assert dict(output) == {
        "raw-b": ["w2-1"],
        "raw-a": ["w2-1", "w2-2"],
    }
    assert graph == original
    assert diag.edge_lineage_raw_ids(graph) == output


@pytest.mark.parametrize("page", ["", "0", "-1", "1.0", "x", None, 3])
def test_invalid_requested_source_page_fails_before_producer_or_quantity(page, monkeypatch):
    def no_ingest(*args, **kwargs):
        raise AssertionError("source producer invoked before validating page")
    monkeypatch.setattr(diag, "SourceVisibilityProducer", no_ingest)
    with pytest.raises(ValueError, match="invalid original source page"):
        diag.source_face_stage_audit(b"fake pdf", page_id=page)


def test_expected_sha_mismatch_blocks_source_ingest_not_fallback(monkeypatch):
    monkeypatch.setattr(diag, "SourceVisibilityProducer", lambda **kwargs: (
        pytest.fail("source producer called for wrong SHA")))
    source = b"source verification witness"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        diag.source_face_stage_audit(source, page_id="1",
                                     expected_source_sha="0" * 64)
    assert hashlib.sha256(source).hexdigest() != "0" * 64


def test_no_prediction_or_frozen_evaluator_reference_in_diagnostic_source():
    from inspect import getsource
    text = getsource(diag.source_face_stage_audit)
    assert "benchmark_accuracy" in text
    assert '"physical_host_publication_allowed": False' in text
    assert '"opening_count_publication_allowed": False' in text
    assert '"metric_quantity_publication_allowed": False' in text
