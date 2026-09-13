"""Independent #270-before / #273-after ranking validation.

Does not change ranking thresholds, gold, scoring, or commercial wiring.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pb_wall_topology_diagnostics import (
    collect_topology_from_page,
    diagnose_wall_topology,
    document_id_from_path,
)
from pb_wall_topology_ranking_validation import (
    apply_ranking_to_snapshot,
    ranking_svg,
    scoped_wall_like_fills,
    stratified_samples,
    summarize_ranking,
)

DEFAULT_SOURCES = (
    ROOT / "benchmarks" / "sources",
    Path(r"C:\Users\bryce\Documents\PB-PlanReader-3D\benchmarks\sources"),
)

CASES = [
    {
        "name": "Baghau",
        "pdf": "bq_and_drawing_1747803602496.pdf",
        "page": 36,
        "allow_derived": True,
        "viewport_id": "view_p36_4",
        "viewport_bbox": None,
        "scale_pt_per_m": 28.3,
        "alt_bbox": (350.0, 350.0, 950.0, 850.0),
    },
    {
        "name": "Lamu",
        "pdf": "lamu-ishakani-ecd-classrooms-boq.pdf",
        "page": 41,
        "allow_derived": True,
        "viewport_id": "view_p41_1",
        "viewport_bbox": None,
        "scale_pt_per_m": 28.0,
        "alt_bbox": (100.0, 20.0, 750.0, 380.0),
    },
    {
        "name": "Dungicha",
        "pdf": "dungicha_3classrooms.pdf",
        "page": 134,
        "allow_derived": False,
        "viewport_id": None,
        "viewport_bbox": (0.0, 550.0, 900.0, 950.0),
        "scale_pt_per_m": 28.35,
        "alt_bbox": None,
    },
    {
        "name": "KSTVET",
        "pdf": "1727358888238-bq-nd-drawing.pdf",
        "page": 54,
        "allow_derived": True,
        "viewport_id": None,
        "viewport_bbox": None,
        "scale_pt_per_m": 37.24,
        "alt_bbox": (150.0, 300.0, 750.0, 800.0),
    },
]


def _find_pdf(name: str) -> Optional[Path]:
    for root in DEFAULT_SOURCES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _compact(report: Dict[str, Any]) -> Dict[str, Any]:
    counts = report.get("counts") or {}
    dist = report.get("distributions") or {}
    components = report.get("components") or []
    return {
        "source": report.get("source"),
        "counts": {
            "wall_candidates": counts.get("wall_candidates"),
            "isolated_candidates": counts.get("isolated_candidates"),
            "connected_components": counts.get("connected_components"),
            "stage_a_edges": counts.get("stage_a_edges"),
            "room_candidates": counts.get("room_candidates"),
            "largest_component": components[0].get("size") if components else None,
        },
        "candidate_length_pt": dist.get("candidate_length_pt"),
        "opening_host_binding": dist.get("opening_host_binding"),
        "evidence_ranking": dist.get("evidence_ranking"),
    }


def _run_case(spec: Dict[str, Any], *, use_alt_bbox: bool = False) -> Dict[str, Any]:
    pdf_path = _find_pdf(spec["pdf"])
    if pdf_path is None:
        return {"name": spec["name"], "error": f"PDF not found: {spec['pdf']}"}
    bbox = spec["alt_bbox"] if use_alt_bbox else spec["viewport_bbox"]
    viewport_id = None if use_alt_bbox else spec["viewport_id"]
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[spec["page"] - 1]
        before = collect_topology_from_page(
            page,
            page_number=spec["page"],
            document_id=document_id_from_path(pdf_path),
            allow_derived=spec["allow_derived"],
            viewport_id=viewport_id,
            viewport_bbox=bbox,
        )
        fill_bbox = bbox
        if fill_bbox is None and before.viewport_id:
            from pb_wall_topology_diagnostics import list_page_viewports

            for row in list_page_viewports(
                page, page_number=spec["page"], allow_derived=spec["allow_derived"]
            ):
                if row.get("view_id") == before.viewport_id and row.get("bounding_box"):
                    fill_bbox = row["bounding_box"]
                    break
        fills = scoped_wall_like_fills(page, fill_bbox) if fill_bbox is not None else ()
    finally:
        doc.close()

    before_report = diagnose_wall_topology(before)
    if before.fail_closed_reason:
        return {
            "name": spec["name"],
            "mode": "alt_bbox" if use_alt_bbox else "harness_270",
            "fail_closed_reason": before.fail_closed_reason,
            "before": _compact(before_report),
        }

    ranked_unscaled = apply_ranking_to_snapshot(before, wall_like_fills=fills, scale_pt_per_m=None)
    ranked_scaled = apply_ranking_to_snapshot(
        before, wall_like_fills=fills, scale_pt_per_m=spec["scale_pt_per_m"]
    )
    after_report = diagnose_wall_topology(ranked_scaled)
    return {
        "name": spec["name"],
        "mode": "alt_bbox" if use_alt_bbox else "harness_270",
        "viewport_id": before.viewport_id,
        "viewport_authority": before.viewport_authority,
        "fill_count": len(fills),
        "before": _compact(before_report),
        "after_unscaled": summarize_ranking(ranked_unscaled.walls),
        "after_scaled": summarize_ranking(ranked_scaled.walls),
        "after_harness": _compact(after_report),
        "samples": stratified_samples(ranked_scaled.walls, per_bucket=12),
        "svg": ranking_svg(ranked_scaled.walls),
    }


def main() -> int:
    out_dir = ROOT / "_diag_out" / "ranking_validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in CASES:
        print(f"=== {spec['name']} #270 harness ===")
        primary = _run_case(spec, use_alt_bbox=False)
        results.append(primary)
        _print_result(primary)
        if spec.get("alt_bbox") and primary.get("fail_closed_reason"):
            print(f"=== {spec['name']} caller bbox (F.07 unavailable) ===")
            fallback = _run_case(spec, use_alt_bbox=True)
            results.append(fallback)
            _print_result(fallback)
        elif spec.get("alt_bbox") and spec["name"] in {"Baghau", "Lamu"}:
            print(f"=== {spec['name']} #273 region (comparison only) ===")
            alt = _run_case(spec, use_alt_bbox=True)
            results.append(alt)
            _print_result(alt)
    summary_path = out_dir / "summary.json"
    serializable = []
    for result in results:
        row = dict(result)
        svg = row.pop("svg", None)
        name = result.get("name", "unknown")
        mode = result.get("mode", "unknown")
        if svg:
            (out_dir / f"{name.lower()}_{mode}.svg").write_text(svg, encoding="utf-8", newline="\n")
        samples = row.get("samples")
        if samples:
            (out_dir / f"{name.lower()}_{mode}_samples.json").write_text(
                json.dumps(samples, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        serializable.append(row)
    summary_path.write_text(json.dumps(serializable, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {summary_path}")
    return 0


def _print_result(result: Dict[str, Any]) -> None:
    if result.get("error"):
        print(f"  error={result['error']}")
        return
    if result.get("fail_closed_reason"):
        print(f"  fail_closed={result['fail_closed_reason']}")
        return
    before = result["before"]["counts"]
    after = result["after_scaled"]["buckets"]
    print(
        f"  walls={before['wall_candidates']} isolated={before['isolated_candidates']} "
        f"components={before['connected_components']} largest={before['largest_component']}"
    )
    print(
        "  ranked "
        + " ".join(f"{name}={after.get(name, 0)}" for name in (
            "abstained",
            "candidate_single",
            "candidate_multi",
            "ambiguous",
            "corroborated",
        ))
    )
    print("  signals", result["after_scaled"]["signals"])
    print("  signal_sets", result["after_scaled"]["signal_sets"])


if __name__ == "__main__":
    raise SystemExit(main())
