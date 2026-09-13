"""Real-drawing regression coverage for pb_wall_room_topology_wall_band_evidence,
run against the committed Baghau/Dungicha vector snapshots (see
scripts/export_hosted_opening_vector_fixture.py) rather than the gitignored
source PDFs, so this stays CI-reproducible without any local PDF present.

Asserts qualitative, evidence-grounded properties -- never an exact count
(W1-W4's own algorithms are unmodified but not frozen by this workstream) --
and, critically, never treats "reached CORROBORATED" as unconditionally
correct: it also asserts the model's own stated independence invariants
still hold on real, messy geometry (no wall reaches CORROBORATED without a
resolved thickness_m, and every CORROBORATED wall's own reason codes name
at least two of the model's distinct signal families, never room-boundary
or bare connectivity, which this module does not compute at all)."""
from __future__ import annotations

import json
from pathlib import Path

from pb_migration_contracts import EvidenceResolutionStatus
from pb_vector_geometry_v130 import extract_native_page
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_room_topology_wall_band_evidence import (
    REASON_BAND_CONTINUITY,
    REASON_REPEATED_MODE,
    REASON_SCALE_PLAUSIBLE,
    rank_wall_band_evidence,
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


def _run_pipeline(snapshot_path: Path, *, scale_pt_per_m: float, document_id: str):
    snapshot = _load_snapshot(snapshot_path)
    page = _snapshot_page(snapshot)
    native = extract_native_page(page)
    segments = native["segments"]

    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id=document_id, page_id="fixture", viewport_id="vp_fixture"
    )
    walls, _ = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_fixture")
    evidence = rank_wall_band_evidence(walls, scale_pt_per_m=scale_pt_per_m)
    return walls, evidence


def test_baghau_real_geometry_never_crashes_and_respects_independence_invariants():
    walls, evidence = _run_pipeline(
        _BAGHAU_SNAPSHOT_PATH, scale_pt_per_m=_BAGHAU_SCALE_PT_PER_M, document_id="baghau_p36"
    )
    # evidence is positionally aligned with walls (see rank_wall_band_evidence's
    # own docstring: real geometry can produce two WallCandidates sharing one
    # candidate_id -- confirmed on this exact real Dungicha-shaped case below
    # -- so this equality is itself the regression check for that defect,
    # not a formality).
    assert len(evidence) == len(walls)

    corroborated = [ev for ev in evidence if ev.status == EvidenceResolutionStatus.CORROBORATED]
    assert corroborated, "expected at least one real double-line wall run to reach CORROBORATED"
    for ev in corroborated:
        assert ev.thickness_m is not None, "CORROBORATED must always carry a resolved thickness_m"
        assert REASON_SCALE_PLAUSIBLE in ev.reason_codes
        # At least one of the two genuinely independent structural signals
        # (never room-boundary or bare connectivity -- this module computes
        # neither) must also be present.
        assert REASON_REPEATED_MODE in ev.reason_codes or REASON_BAND_CONTINUITY in ev.reason_codes

    for ev in evidence:
        assert len(ev.supporting_evidence_ids) == len(set(ev.supporting_evidence_ids))
        assert len(ev.reason_codes) == len(set(ev.reason_codes))


def test_dungicha_real_geometry_never_crashes_and_respects_independence_invariants():
    walls, evidence = _run_pipeline(
        _DUNGICHA_SNAPSHOT_PATH, scale_pt_per_m=_DUNGICHA_SCALE_PT_PER_M, document_id="dungicha_p134"
    )
    # Regression: this real page contains two genuinely duplicate Stage-A
    # edges (the same 2-point line traced twice) that collide onto one
    # candidate_id even after the shape-fingerprint identity fix, since both
    # really are the same straight line. A dict-keyed return would silently
    # drop one; the positionally-aligned list this module returns cannot.
    assert len(evidence) == len(walls)

    corroborated = [ev for ev in evidence if ev.status == EvidenceResolutionStatus.CORROBORATED]
    for ev in corroborated:
        assert ev.thickness_m is not None
        assert REASON_SCALE_PLAUSIBLE in ev.reason_codes
        assert REASON_REPEATED_MODE in ev.reason_codes or REASON_BAND_CONTINUITY in ev.reason_codes

    for ev in evidence:
        assert len(ev.supporting_evidence_ids) == len(set(ev.supporting_evidence_ids))
        assert len(ev.reason_codes) == len(set(ev.reason_codes))
