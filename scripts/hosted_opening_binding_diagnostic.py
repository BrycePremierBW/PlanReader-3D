"""hosted_opening_binding_diagnostic.py -- DIAGNOSTIC ONLY, not wired into
production. Reruns pb_hosted_opening_wall_binding.bind_hosted_opening_to_walls
against the same real drawings, comparing the OLD (unranked, unfiltered) W4
wall population against the NEW population once ABSTAINED noise candidates
are removed by pb_wall_room_topology_wall_evidence_ranking.

Does not touch pb_hosted_opening_geometry.py, PR #269, F.07, or the opening
provenance graph. Does not infer opening identity, height, or quantity --
reports only BOUND/AMBIGUOUS/UNBOUND counts.

Usage:
    python scripts/hosted_opening_binding_diagnostic.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import fitz

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pb_hosted_opening_geometry import resolve_hosted_opening_spans
from pb_hosted_opening_wall_binding import bind_hosted_opening_to_walls
from pb_migration_contracts import EvidenceResolutionStatus
from pb_vector_geometry_v130 import extract_native_page
from pb_wall_room_topology_junction_classifier import classify_junctions
from pb_wall_room_topology_stage_a import build_wall_graph_for_viewport
from pb_wall_room_topology_wall_assembly import assemble_wall_candidates
from pb_wall_room_topology_wall_evidence_ranking import rank_wall_candidates
from scripts.wall_evidence_real_drawing_audit import PROJECTS, _filter_to_region, _wall_like_fills_from_rects

SOURCES_DIR = REPO_ROOT / "benchmarks" / "sources"


def _tally(spans, walls) -> Dict[str, int]:
    counts = {"bound": 0, "ambiguous": 0, "unbound": 0}
    for span in spans:
        binding = bind_hosted_opening_to_walls(span, walls, viewport_id="vp_diag")
        counts[binding.status] += 1
    return counts


def diagnose_one(spec: Dict[str, Any]) -> None:
    pdf_path = spec["pdf"]
    if not pdf_path.exists():
        print(f"SKIP {spec['name']}: source PDF not present at {pdf_path}")
        return
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[spec["page_0based"]]
        native = extract_native_page(page)
        region = spec.get("region")
        segments = _filter_to_region(
            native["segments"],
            region,
            lambda s: (min(s["x1"], s["x2"]), min(s["y1"], s["y2"]), max(s["x1"], s["x2"]), max(s["y1"], s["y2"])),
        )
        rects = _filter_to_region(native["rects"], region, lambda r: tuple(r["bbox"]))

        graph = build_wall_graph_for_viewport(segments)
        junctions, relationships = classify_junctions(
            graph, document_id=spec["name"], page_id=str(spec["page_0based"]), viewport_id="vp_diag"
        )
        old_walls, _ = assemble_wall_candidates(graph, junctions, relationships, viewport_id="vp_diag")

        fills = _wall_like_fills_from_rects(rects)
        ranked = rank_wall_candidates(old_walls, wall_like_fills=fills, scale_pt_per_m=spec["scale_pt_per_m"])
        new_walls = [w for w in ranked if w.status != EvidenceResolutionStatus.ABSTAINED]

        # Same floor-plan viewport region as the wall population above --
        # resolving openings against the whole physical sheet would mix in
        # unrelated content (title block, schedules) exactly like the wall
        # population itself would without region scoping.
        evidence = resolve_hosted_opening_spans(page, viewport_bbox=region, scale_authority=spec["scale_pt_per_m"])
    finally:
        doc.close()

    if evidence.status != "found" or not evidence.openings:
        print(f"\n=== {spec['name']} === no hosted-opening spans found on this page ({evidence.reason})")
        return

    before = _tally(evidence.openings, old_walls)
    after = _tally(evidence.openings, new_walls)
    print(f"\n=== {spec['name']} (page {spec['page_0based'] + 1}) ===")
    print(f"  hosted-opening spans:  {len(evidence.openings)}")
    print(f"  wall population:       {len(old_walls)} (old) -> {len(new_walls)} (new, non-abstained)")
    print(f"  BEFORE: bound={before['bound']} ambiguous={before['ambiguous']} unbound={before['unbound']}")
    print(f"  AFTER:  bound={after['bound']} ambiguous={after['ambiguous']} unbound={after['unbound']}")


def main() -> None:
    for spec in PROJECTS:
        if spec["name"] not in ("Baghau", "Lamu", "Dungicha"):
            continue
        diagnose_one(spec)


if __name__ == "__main__":
    main()
