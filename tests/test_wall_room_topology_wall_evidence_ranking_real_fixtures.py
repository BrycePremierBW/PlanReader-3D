"""Real-drawing regression coverage for pb_wall_room_topology_wall_evidence_
ranking, run against the committed Baghau/Dungicha vector snapshots (see
scripts/export_hosted_opening_vector_fixture.py) rather than the gitignored
source PDFs, so this stays CI-reproducible without any local PDF present.

This never asserts an exact wall/candidate count -- W1-W4's own algorithms
are unmodified but not frozen by this workstream, and a brittle exact-count
assertion would break on any future, unrelated Stage-A/W3/W4 change. It
asserts qualitative, evidence-grounded properties that must hold regardless
of incidental count drift: real noise gets rejected, at least some real
paired-face wall material is recognized, and the pipeline never crashes on
this real, messy geometry (see the id-collision regression in
test_wall_room_topology_wall_evidence_ranking.py for the specific defect
this locks in more broadly)."""
from __future__ import annotations

import json
from pathlib import Path

from pb_migration_contracts import EvidenceResolutionStatus
from pb_vector_geometry_v130 import extract_native_page
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_room_topology_wall_evidence_ranking import (
    REASON_PAIRED_FACE,
    rank_wall_candidates,
)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "hosted_opening_geometry"
_BAGHAU_SNAPSHOT_PATH = _FIXTURES_DIR / "baghau_p36.json"
_DUNGICHA_SNAPSHOT_PATH = _FIXTURES_DIR / "dungicha_p134.json"

_BAGHAU_SCALE_PT_PER_M = 28.3
_DUNGICHA_SCALE_PT_PER_M = 28.35


class _Pt:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _Rect:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.width = x1 - x0
        self.height = y1 - y0


class _FakePage:
    def __init__(self, drawings, rect=None, number=0):
        self._drawings = drawings
        self.rect = rect or _Rect(0, 0, 2000, 2000)
        self.number = number

    def get_drawings(self):
        return self._drawings

    def get_text(self, *_a, **_kw):
        return ""


def _load_snapshot(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _snapshot_page(snapshot: dict) -> _FakePage:
    """Reconstruct a _FakePage from an exported snapshot's raw drawings --
    identical shape to tests/test_hosted_opening_geometry.py's own
    _snapshot_page, so pb_vector_geometry_v130.extract_native_page runs its
    real, unmodified code path against it."""
    drawings = []
    for d in snapshot["drawings"]:
        items = []
        for item in d["items"]:
            op = item[0]
            items.append((op, *[_Pt(x, y) for x, y in item[1:]]))
        drawings.append(
            {
                "color": tuple(d["color"]) if d["color"] is not None else None,
                "fill": tuple(d["fill"]) if d["fill"] is not None else None,
                "width": d["width"],
                "rect": _Rect(*d["rect"]) if d["rect"] is not None else None,
                "items": items,
            }
        )
    page_rect = _Rect(*snapshot["page_rect"])
    return _FakePage(drawings, rect=page_rect, number=snapshot["source"]["pdf_page_0based"])


def _wall_like_fills_from_rects(rects) -> list:
    out = []
    for r in rects:
        fill = r.get("fill")
        if not fill or len(fill) < 3:
            continue
        if max(fill[:3]) > 0.2:
            continue
        x0, y0, x1, y1 = r["bbox"]
        w, h = x1 - x0, y1 - y0
        long_side, short_side = max(w, h), max(min(w, h), 1e-6)
        if long_side < 4.0 or long_side / short_side < 3.0:
            continue
        out.append((x0, y0, x1, y1))
    return out


def _run_pipeline(snapshot_path: Path, *, scale_pt_per_m: float, document_id: str):
    snapshot = _load_snapshot(snapshot_path)
    page = _snapshot_page(snapshot)
    native = extract_native_page(page)
    segments = native["segments"]
    rects = native["rects"]

    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id=document_id, page_id="fixture", viewport_id="vp_fixture"
    )
    walls, edge_map = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_fixture")
    rooms = reconstruct_room_candidates(
        graph, edge_map, document_id=document_id, viewport_id="vp_fixture"
    )
    fills = _wall_like_fills_from_rects(rects)
    ranked = rank_wall_candidates(walls, rooms=rooms, wall_like_fills=fills, scale_pt_per_m=scale_pt_per_m)
    return walls, ranked


def test_baghau_real_geometry_ranks_without_crashing_and_finds_real_walls():
    """Locks in the real-data id-collision crash fix (see the dedicated
    synthetic regression in test_wall_room_topology_wall_evidence_ranking.py)
    against the FULL real Baghau p36 snapshot -- the exact geometry that
    originally crashed this module -- not just a hand-built repro. Also
    asserts the two qualitative properties this whole workstream exists to
    achieve: real noise is rejected (some candidates ABSTAIN) and real wall
    material is still recognized (some candidates carry paired-face
    evidence) -- never an exact count, which would be brittle to unrelated
    W1-W4 changes."""
    walls, ranked = _run_pipeline(
        _BAGHAU_SNAPSHOT_PATH, scale_pt_per_m=_BAGHAU_SCALE_PT_PER_M, document_id="baghau_p36"
    )
    assert len(ranked) == len(walls)
    abstained = [w for w in ranked if w.status == EvidenceResolutionStatus.ABSTAINED]
    evidenced = [w for w in ranked if w.status != EvidenceResolutionStatus.ABSTAINED]
    assert abstained, "expected at least some real noise geometry to be rejected"
    assert evidenced, "expected at least some real wall geometry to be recognized"
    assert any(REASON_PAIRED_FACE in w.supporting_evidence_ids for w in evidenced), (
        "expected at least one real double-line wall face pairing on this floor plan"
    )
    for w in ranked:
        assert len(w.supporting_evidence_ids) == len(set(w.supporting_evidence_ids))
        assert len(w.reason_codes) == len(set(w.reason_codes))


def test_dungicha_real_geometry_ranks_without_crashing_and_finds_real_walls():
    walls, ranked = _run_pipeline(
        _DUNGICHA_SNAPSHOT_PATH, scale_pt_per_m=_DUNGICHA_SCALE_PT_PER_M, document_id="dungicha_p134"
    )
    assert len(ranked) == len(walls)
    abstained = [w for w in ranked if w.status == EvidenceResolutionStatus.ABSTAINED]
    evidenced = [w for w in ranked if w.status != EvidenceResolutionStatus.ABSTAINED]
    assert abstained, "expected at least some real noise geometry to be rejected"
    assert evidenced, "expected at least some real wall geometry to be recognized"
    for w in ranked:
        assert len(w.supporting_evidence_ids) == len(set(w.supporting_evidence_ids))
        assert len(w.reason_codes) == len(set(w.reason_codes))
