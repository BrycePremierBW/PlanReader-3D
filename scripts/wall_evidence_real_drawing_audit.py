"""wall_evidence_real_drawing_audit.py -- real-drawing noise census and
before/after validation for pb_wall_room_topology_wall_evidence_ranking.

Runs the actual, unmodified W1-W4 pipeline (Stage A -> junction
classification -> wall assembly -> W5 room-face reconstruction) against
real floor-plan pages, exactly as the production topology stack would,
then reissues the resulting WallCandidate population through the new
generic evidence-ranking module. Reports counts only -- never classifies
using benchmark expected values, never adjusts thresholds to hit a target.

Usage (from the repository root, with real PDFs present locally in
benchmarks/sources/ -- gitignored, never committed):

    python scripts/wall_evidence_real_drawing_audit.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pb_vector_geometry_v130 import extract_native_page
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_room_faces import reconstruct_room_candidates
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_room_topology_wall_evidence_ranking import (
    REASON_CONNECTED,
    REASON_FILL_SUPPORTED,
    REASON_PAIRED_FACE,
    REASON_ROOM_BOUNDARY,
    rank_wall_candidates,
)
from pb_migration_contracts import EvidenceResolutionStatus

SOURCES_DIR = REPO_ROOT / "benchmarks" / "sources"

PROJECTS = [
    {
        "name": "Baghau",
        "pdf": SOURCES_DIR / "bq_and_drawing_1747803602496.pdf",
        "page_0based": 35,
        "scale_pt_per_m": 28.3,
        # Reuses this session's own already-vetted floor-plan capture
        # region (scripts/export_hosted_opening_vector_fixture.py) rather
        # than the whole physical sheet -- a large arch-D sheet also
        # carries a title block, revision table, and unrelated content far
        # from this classroom's own floor plan, and W2's own
        # build_wall_graph_for_viewport is explicitly a per-viewport
        # operation, not a whole-sheet one.
        "region": (350.0, 350.0, 950.0, 850.0),
    },
    {
        "name": "Lamu",
        "pdf": SOURCES_DIR / "lamu-ishakani-ecd-classrooms-boq.pdf",
        "page_0based": 40,
        "scale_pt_per_m": 28.0,
        # Generously margined around the real window/door jamb coordinates
        # tests/test_hosted_opening_geometry.py already exercises for this
        # page (viewport_bbox=(190,95,660,220) and (190,270,660,300)).
        "region": (100.0, 20.0, 750.0, 380.0),
    },
    {
        "name": "Dungicha",
        "pdf": SOURCES_DIR / "dungicha_3classrooms.pdf",
        "page_0based": 133,
        "scale_pt_per_m": 28.35,
        # Matches tests/fixtures/hosted_opening_geometry/dungicha_p134.json's
        # own committed capture_region_pdf_pt exactly.
        "region": (0.0, 550.0, 900.0, 950.0),
    },
    {
        "name": "Ghazi",
        "pdf": SOURCES_DIR / "1739211305954-tender-document-for-construction-of-science-laboratory-at-ghazi-primary-school.pdf",
        "page_0based": 166,
        "scale_pt_per_m": None,
        "region": None,  # whole page: only 76 segments total (raster scan, see project_raster_vs_vector_drawings memory)
    },
    {
        "name": "KSTVET",
        "pdf": SOURCES_DIR / "1727358888238-bq-nd-drawing.pdf",
        "page_0based": 53,
        "scale_pt_per_m": 37.24,
        # Generously margined around the real jamb coordinates
        # tests/test_hosted_opening_geometry.py exercises for this page
        # (viewport_bbox=(260,375,650,410) and (260,390,280,705)).
        "region": (150.0, 300.0, 750.0, 800.0),
    },
    {
        "name": "Murera",
        "pdf": SOURCES_DIR / "1785347143869-bqs-drawings.pdf",
        "page_0based": 221,
        "scale_pt_per_m": None,
        "region": None,  # whole page: only 7 segments total (raster scan, see project_raster_vs_vector_drawings memory)
    },
]


def _wall_like_fills_from_rects(rects: List[Dict[str, Any]]) -> List[Tuple[float, float, float, float]]:
    """Restate the same near-black, thin-and-long fill heuristic this
    codebase already uses independently in pb_hosted_opening_geometry.py
    and pb_wall_fill_internal_partition_evidence.py -- not imported across
    modules that do not share an architecture, per established convention."""
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


def _length_pt(pts) -> float:
    import math
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def _overlaps_region(bbox: Tuple[float, float, float, float], region: Tuple[float, float, float, float]) -> bool:
    bx0, by0, bx1, by1 = bbox
    rx0, ry0, rx1, ry1 = region
    return not (bx1 < rx0 or bx0 > rx1 or by1 < ry0 or by0 > ry1)


def _filter_to_region(items: List[Dict[str, Any]], region: Optional[Tuple[float, float, float, float]], bbox_of) -> List[Dict[str, Any]]:
    if region is None:
        return items
    return [item for item in items if _overlaps_region(bbox_of(item), region)]


def audit_one(spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pdf_path = spec["pdf"]
    if not pdf_path.exists():
        print(f"SKIP {spec['name']}: source PDF not present at {pdf_path}")
        return None
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[spec["page_0based"]]
        native = extract_native_page(page)
    finally:
        doc.close()

    region = spec.get("region")
    segments = _filter_to_region(
        native["segments"],
        region,
        lambda s: (min(s["x1"], s["x2"]), min(s["y1"], s["y2"]), max(s["x1"], s["x2"]), max(s["y1"], s["y2"])),
    )
    rects = _filter_to_region(native["rects"], region, lambda r: tuple(r["bbox"]))
    raw_segment_count = len(segments)

    graph = build_wall_graph_for_viewport(segments)
    junctions, relationships = classify_junctions(
        graph, document_id=spec["name"], page_id=str(spec["page_0based"]), viewport_id="vp_audit"
    )
    walls, edge_map = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_audit")
    rooms = reconstruct_room_candidates(
        graph, edge_map, document_id=spec["name"], viewport_id="vp_audit", source_page=spec["page_0based"]
    )

    fills = _wall_like_fills_from_rects(rects)
    ranked = rank_wall_candidates(
        walls,
        rooms=rooms,
        wall_like_fills=fills,
        scale_pt_per_m=spec["scale_pt_per_m"],
    )

    counts = {
        "abstained": 0,
        "candidate_single": 0,
        "candidate_multi": 0,
        "candidate_ambiguous": 0,
        "corroborated": 0,
    }
    lengths_abstained = []
    lengths_promoted = []
    paired_ct = fill_ct = room_ct = connected_ct = 0
    for w in ranked:
        length = _length_pt(w.centerline_pts)
        if w.status == EvidenceResolutionStatus.ABSTAINED:
            counts["abstained"] += 1
            lengths_abstained.append(length)
            continue
        lengths_promoted.append(length)
        if w.status == EvidenceResolutionStatus.CORROBORATED:
            counts["corroborated"] += 1
        elif "conflicting_paired_face_thickness_estimates" in w.reason_codes:
            counts["candidate_ambiguous"] += 1
        elif len(w.supporting_evidence_ids) >= 2 or w.supporting_evidence_ids[0].startswith(REASON_PAIRED_FACE + ":"):
            counts["candidate_multi"] += 1
        else:
            counts["candidate_single"] += 1
        if REASON_PAIRED_FACE in w.supporting_evidence_ids:
            paired_ct += 1
        if REASON_FILL_SUPPORTED in w.supporting_evidence_ids:
            fill_ct += 1
        if REASON_ROOM_BOUNDARY in w.supporting_evidence_ids:
            room_ct += 1
        if REASON_CONNECTED in w.supporting_evidence_ids:
            connected_ct += 1

    result = {
        "name": spec["name"],
        "page_1based": spec["page_0based"] + 1,
        "raw_segments": raw_segment_count,
        "old_wall_candidates": len(walls),
        "rooms": len(rooms),
        "junctions": len(junctions),
        "counts": counts,
        "paired_face_ct": paired_ct,
        "fill_supported_ct": fill_ct,
        "room_boundary_ct": room_ct,
        "connected_ct": connected_ct,
        "median_length_abstained": round(statistics.median(lengths_abstained), 2) if lengths_abstained else None,
        "median_length_promoted": round(statistics.median(lengths_promoted), 2) if lengths_promoted else None,
        "min_length_promoted": round(min(lengths_promoted), 2) if lengths_promoted else None,
    }
    return result


def main() -> None:
    results = []
    for spec in PROJECTS:
        r = audit_one(spec)
        if r is None:
            continue
        results.append(r)
        print(f"\n=== {r['name']} (page {r['page_1based']}) ===")
        print(f"  raw segments:          {r['raw_segments']}")
        print(f"  old WallCandidates:    {r['old_wall_candidates']}")
        print(f"  room candidates:       {r['rooms']}")
        print(f"  junctions:             {r['junctions']}")
        print(f"  -- new ranking --")
        print(f"  ABSTAINED:             {r['counts']['abstained']}")
        print(f"  CANDIDATE (1 signal):  {r['counts']['candidate_single']}")
        print(f"  CANDIDATE (2+ signal): {r['counts']['candidate_multi']}")
        print(f"  CANDIDATE (ambiguous): {r['counts']['candidate_ambiguous']}")
        print(f"  CORROBORATED:          {r['counts']['corroborated']}")
        print(f"  paired-face signal:    {r['paired_face_ct']}")
        print(f"  fill-supported signal: {r['fill_supported_ct']}")
        print(f"  room-boundary signal:  {r['room_boundary_ct']}")
        print(f"  connected signal:      {r['connected_ct']}")
        print(f"  median length (abstained/promoted): {r['median_length_abstained']} / {r['median_length_promoted']}")
        print(f"  min length promoted:   {r['min_length_promoted']}")

    print("\n=== SUMMARY ===")
    for r in results:
        total = r["old_wall_candidates"]
        abstained = r["counts"]["abstained"]
        pct = (abstained / total * 100.0) if total else 0.0
        print(f"{r['name']:10s} {total:5d} candidates -> {abstained:5d} abstained ({pct:.1f}%), "
              f"{total - abstained:5d} evidenced")


if __name__ == "__main__":
    main()
