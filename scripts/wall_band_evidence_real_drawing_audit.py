"""wall_band_evidence_real_drawing_audit.py -- real-drawing validation for
pb_wall_room_topology_wall_band_evidence, per the mandate's own reporting
categories.

Mandatory vector drawings only: Baghau p36, Lamu p41, Dungicha p134,
KSTVET p54. Ghazi/Murera are excluded -- confirmed raster-scan pages with
no real vector wall geometry (see docs/AI_ENGINEERING_PLAYBOOK.md).

Reports, per project:
  - raw W4 candidates
  - pair hypotheses (all geometrically plausible, before consistency check)
  - thickness modes (locally-consistent pairs, clustered by relative gap
    agreement)
  - consistent wall bands (CORROBORATED -- three independent signals plus a
    resolved thickness)
  - ambiguous bands (CANDIDATE with two independent signals but no scale
    authority, or an inconsistent-gap flag)
  - rejected room-width pairs / frame-glazing pairs / hatch-furniture
    patterns -- reported as a manually-reviewed sample of ISOLATED_LOCAL_PAIR
    and SYMBOL_LIKE verdicts, never asserted from expected values
  - preserved real short returns
  - preserved known real masonry

This never uses benchmark gold, expected quantities, or project identity in
the evidence model itself -- this script exists only to observe and report
what the model, unmodified, produces on real geometry.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict

import fitz

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pb_migration_contracts import EvidenceResolutionStatus
from pb_vector_geometry_v130 import extract_native_page
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_room_topology_wall_band_evidence import (
    REASON_BAND_CONTINUITY,
    REASON_INCONSISTENT_LOCAL_THICKNESS,
    REASON_ISOLATED_LOCAL_PAIR,
    REASON_NO_EVIDENCE,
    REASON_REPEATED_MODE,
    REASON_SYMBOL_LIKE,
    cluster_thickness_modes,
    find_face_pair_hypotheses,
    find_symbol_like_pair_indices,
    modes_with_distinct_occurrences,
    rank_wall_band_evidence,
)

SOURCES_DIR = REPO_ROOT / "benchmarks" / "sources"

PROJECTS = [
    {
        "name": "Baghau",
        "pdf": SOURCES_DIR / "bq_and_drawing_1747803602496.pdf",
        "page_0based": 35,
        "scale_pt_per_m": 28.3,
        "region": (350.0, 350.0, 950.0, 850.0),
    },
    {
        "name": "Lamu",
        "pdf": SOURCES_DIR / "lamu-ishakani-ecd-classrooms-boq.pdf",
        "page_0based": 40,
        "scale_pt_per_m": 28.0,
        "region": (100.0, 20.0, 750.0, 380.0),
    },
    {
        "name": "Dungicha",
        "pdf": SOURCES_DIR / "dungicha_3classrooms.pdf",
        "page_0based": 133,
        "scale_pt_per_m": 28.35,
        "region": (0.0, 550.0, 900.0, 950.0),
    },
    {
        "name": "KSTVET",
        "pdf": SOURCES_DIR / "1727358888238-bq-nd-drawing.pdf",
        "page_0based": 53,
        "scale_pt_per_m": 37.24,
        "region": (150.0, 300.0, 750.0, 800.0),
    },
]


def _overlaps_region(bbox, region) -> bool:
    bx0, by0, bx1, by1 = bbox
    rx0, ry0, rx1, ry1 = region
    return not (bx1 < rx0 or bx0 > rx1 or by1 < ry0 or by0 > ry1)


def _filter_to_region(segments, region):
    if region is None:
        return segments
    return [
        s
        for s in segments
        if _overlaps_region(
            (min(s["x1"], s["x2"]), min(s["y1"], s["y2"]), max(s["x1"], s["x2"]), max(s["y1"], s["y2"])), region
        )
    ]


def audit_one(spec: Dict[str, Any]) -> None:
    pdf_path = spec["pdf"]
    if not pdf_path.exists():
        print(f"SKIP {spec['name']}: source PDF not present at {pdf_path}")
        return
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[spec["page_0based"]]
        native = extract_native_page(page)
    finally:
        doc.close()

    segments = _filter_to_region(native["segments"], spec.get("region"))
    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id=spec["name"], page_id=str(spec["page_0based"]), viewport_id="vp_audit"
    )
    walls, _ = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_audit")

    pairs = find_face_pair_hypotheses(walls)
    consistent_pairs = [p for p in pairs if p.is_locally_consistent]
    inconsistent_pairs = [p for p in pairs if not p.is_locally_consistent]
    modes = cluster_thickness_modes(pairs)
    repeated_mode_indices = modes_with_distinct_occurrences(pairs, modes)
    symbol_like_indices = find_symbol_like_pair_indices(pairs)

    # Positionally aligned with walls, deliberately not a dict keyed by
    # candidate_id -- real geometry can produce two WallCandidates sharing
    # one id (see rank_wall_band_evidence's own docstring), and a dict
    # would silently drop one from this report.
    evidence_list = rank_wall_band_evidence(walls, scale_pt_per_m=spec["scale_pt_per_m"])
    reason_counts = Counter()
    corroborated = []
    ambiguous_candidates = []
    isolated_pairs = []
    symbol_like_walls = []
    short_returns_with_evidence = []
    id_collisions = len(walls) - len({w.candidate_id for w in walls})
    for w, ev in zip(walls, evidence_list):
        for r in ev.reason_codes:
            reason_counts[r] += 1
        length = sum(
            ((w.centerline_pts[i + 1][0] - w.centerline_pts[i][0]) ** 2
             + (w.centerline_pts[i + 1][1] - w.centerline_pts[i][1]) ** 2) ** 0.5
            for i in range(len(w.centerline_pts) - 1)
        )
        if ev.status == EvidenceResolutionStatus.CORROBORATED:
            corroborated.append((w, ev, length))
            if length < 30.0:
                short_returns_with_evidence.append((w, ev, length))
        elif REASON_REPEATED_MODE in ev.reason_codes or REASON_BAND_CONTINUITY in ev.reason_codes:
            ambiguous_candidates.append((w, ev, length))
            if length < 30.0:
                short_returns_with_evidence.append((w, ev, length))
        elif REASON_ISOLATED_LOCAL_PAIR in ev.reason_codes:
            isolated_pairs.append((w, ev, length))
        elif REASON_SYMBOL_LIKE in ev.reason_codes:
            symbol_like_walls.append((w, ev, length))

    print(f"\n=== {spec['name']} (page {spec['page_0based'] + 1}) ===")
    print(f"  raw W4 candidates:              {len(walls)}")
    if id_collisions:
        print(f"  !! W4 candidate_id collisions:  {id_collisions} (pre-existing duplicate-geometry gap, not this module's own defect -- see report)")
    print(f"  pair hypotheses (all):          {len(pairs)}")
    print(f"    locally consistent:           {len(consistent_pairs)}")
    print(f"    locally INCONSISTENT:         {len(inconsistent_pairs)}")
    print(f"  thickness modes found:          {len(modes)}")
    print(f"  pairs in a REPEATED mode:       {len(repeated_mode_indices)}")
    print(f"  pairs flagged SYMBOL-LIKE:      {len(symbol_like_indices)}")
    print(f"  -- per-wall evidence verdict --")
    print(f"  CORROBORATED (3 signals+scale): {len(corroborated)}")
    print(f"  CANDIDATE (2 independent sigs): {len(ambiguous_candidates)}")
    print(f"  CANDIDATE (isolated 1 pair):    {len(isolated_pairs)}")
    print(f"  ABSTAINED (symbol-like):        {len(symbol_like_walls)}")
    print(f"  ABSTAINED (no evidence):        {reason_counts.get(REASON_NO_EVIDENCE, 0)}")
    print(f"  CANDIDATE (inconsistent gap):   {reason_counts.get(REASON_INCONSISTENT_LOCAL_THICKNESS, 0)}")
    print(f"  short (<30pt) walls w/ evidence: {len(short_returns_with_evidence)}")

    if corroborated:
        thicknesses = sorted({round(ev.thickness_m, 3) for _, ev, _ in corroborated if ev.thickness_m})
        print(f"  CORROBORATED thickness values (m): {thicknesses}")

    print("  -- sample of isolated (rejected-from-strong-tier) pairs, first 5 --")
    for w, ev, length in isolated_pairs[:5]:
        gap_m = round(ev.best_pair.mean_gap_pt / spec["scale_pt_per_m"], 3) if ev.best_pair else None
        print(f"    id={w.candidate_id[:18]} len_pt={round(length,1)} gap_m={gap_m}")

    print("  -- sample of symbol-like (rejected) walls, first 5 --")
    for w, ev, length in symbol_like_walls[:5]:
        print(f"    id={w.candidate_id[:18]} len_pt={round(length,1)}")


def main() -> None:
    for spec in PROJECTS:
        audit_one(spec)


if __name__ == "__main__":
    main()
