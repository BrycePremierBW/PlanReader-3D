#!/usr/bin/env python3
"""Developer-only read-only wall-topology diagnostic CLI.

Runs existing F.07 + W2-W10 APIs and writes a diagnostic report. It does
not change production extraction, scoring, mappings, or wall classification.

    PYTHONPATH=. python tools/audit_wall_topology.py plan.pdf --page 36 --json out.json --markdown out.md

Page numbers are 1-based. The caller supplies page and, when needed,
viewport identity. If a safe floor-plan viewport is unavailable the
harness fail-closes and reports that.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

from pb_wall_topology_diagnostics import (
    collect_topology_from_page,
    diagnose_wall_topology,
    document_id_from_path,
    list_page_viewports,
    report_to_canonical_json,
    report_to_markdown,
    report_to_svg,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to a source PDF supplied by the caller")
    parser.add_argument(
        "--page",
        type=int,
        required=True,
        help="1-based page number. Required; no project default is applied.",
    )
    parser.add_argument("--json", dest="json_path", help="Write canonical diagnostic JSON here")
    parser.add_argument("--markdown", dest="markdown_path", help="Write Markdown report here")
    parser.add_argument("--svg", dest="svg_path", help="Optional SVG overlay path")
    parser.add_argument(
        "--document-id",
        dest="document_id",
        help="Optional document label. Defaults to the PDF basename only.",
    )
    parser.add_argument(
        "--viewport-id",
        dest="viewport_id",
        help="Optional F.07 view_id. If omitted, the first safe floor-plan viewport is used.",
    )
    parser.add_argument(
        "--allow-derived",
        action="store_true",
        help="Permit DERIVED F.07 floor-plan viewports. Off by default (fail-closed).",
    )
    parser.add_argument(
        "--viewport-bbox",
        dest="viewport_bbox",
        help="Caller-supplied page-space box x0,y0,x1,y1. Overrides F.07 when present.",
    )
    parser.add_argument(
        "--list-viewports",
        action="store_true",
        help="List F.07 viewports for the page and exit without running W2-W10.",
    )
    parser.add_argument(
        "--rank-walls",
        action="store_true",
        help="Reissue W4 walls through #273 ranking. Research/shadow only.",
    )
    parser.add_argument(
        "--scale-pt-per-m",
        dest="scale_pt_per_m",
        type=float,
        help="Optional caller-supplied scale for ranking. Never inferred.",
    )
    return parser


def _write_text(path: str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _print_counts(report: dict) -> None:
    source = report.get("source") or {}
    counts = report.get("counts") or {}
    dist = report.get("distributions") or {}
    print(f"document_id={source.get('document_id')}")
    print(f"page_number={source.get('page_number')}")
    print(f"viewport_id={source.get('viewport_id') or '(none)'}")
    print(f"viewport_authority={source.get('viewport_authority')}")
    if source.get("fail_closed_reason"):
        print(f"fail_closed_reason={source['fail_closed_reason']}")
    print(f"raw_primitives={counts.get('raw_primitives', 0)}")
    print(f"scoped_primitives={counts.get('scoped_primitives', 0)}")
    print(f"stage_a_edges={counts.get('stage_a_edges', 0)}")
    print(f"wall_candidates={counts.get('wall_candidates', 0)}")
    print(f"isolated_candidates={counts.get('isolated_candidates', 0)}")
    print(f"connected_components={counts.get('connected_components', 0)}")
    components = report.get("components") or []
    if components:
        print(f"largest_component_size={components[0].get('size')}")
    degrees = dist.get("junction_degree") or {}
    print(
        "junction_degree "
        f"0={degrees.get('0', 0)} 1={degrees.get('1', 0)} "
        f"2={degrees.get('2', 0)} 3+={degrees.get('3+', 0)}"
    )
    rooms = dist.get("room_face_participation") or {}
    print(f"room_face_participation yes={rooms.get('yes', 0)} no={rooms.get('no', 0)}")
    paired = dist.get("paired_face_evidence") or {}
    print(
        "paired_face_evidence "
        f"yes={paired.get('yes', 0)} no={paired.get('no', 0)} "
        f"unavailable={paired.get('unavailable', 0)}"
    )
    hatch = dist.get("fill_hatch_evidence") or {}
    print(
        "fill_hatch_evidence "
        f"stage_a_exclusions={hatch.get('yes', 0)} "
        f"per_candidate_unavailable={hatch.get('unavailable', 0)}"
    )
    binding = dist.get("opening_host_binding") or {}
    print(
        "opening_host_binding "
        f"BOUND={binding.get('BOUND', 0)} AMBIGUOUS={binding.get('AMBIGUOUS', 0)} "
        f"UNBOUND={binding.get('UNBOUND', 0)} not_evaluated={binding.get('not_evaluated', 0)}"
    )
    ranking = dist.get("evidence_ranking") or {}
    buckets = ranking.get("buckets") or {}
    print(
        "evidence_ranking "
        f"w4_unranked={buckets.get('w4_unranked', 0)} "
        f"abstained={buckets.get('abstained', 0)} "
        f"candidate_single={buckets.get('candidate_single', 0)} "
        f"candidate_multi={buckets.get('candidate_multi', 0)} "
        f"ambiguous={buckets.get('ambiguous', 0)} "
        f"corroborated={buckets.get('corroborated', 0)}"
    )
    print("top20_by_junction_degree=" + ",".join(report.get("highest_connectivity_candidate_ids") or []))
    print("top20_by_length=" + ",".join(report.get("longest_candidate_ids") or []))
    print("top20_in_largest_component=" + ",".join(report.get("largest_component_candidate_ids") or []))


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.page < 1:
        print("error: --page must be a 1-based page number", file=sys.stderr)
        return 2
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"error: PDF not found: {pdf_path.name}", file=sys.stderr)
        return 2

    document_id = args.document_id or document_id_from_path(pdf_path)
    doc = fitz.open(str(pdf_path))
    try:
        if args.page > doc.page_count:
            print(
                f"error: page {args.page} is outside document page_count={doc.page_count}",
                file=sys.stderr,
            )
            return 2
        page = doc[args.page - 1]
        caller_bbox = None
        if args.viewport_bbox:
            parts = [item.strip() for item in args.viewport_bbox.split(",")]
            if len(parts) != 4:
                print("error: --viewport-bbox must be x0,y0,x1,y1", file=sys.stderr)
                return 2
            try:
                caller_bbox = [float(item) for item in parts]
            except ValueError:
                print("error: --viewport-bbox values must be numeric", file=sys.stderr)
                return 2
        if args.list_viewports:
            rows = list_page_viewports(
                page, page_number=args.page, allow_derived=args.allow_derived
            )
            print(json.dumps(rows, indent=2, sort_keys=True))
            return 0
        snapshot = collect_topology_from_page(
            page,
            page_number=args.page,
            document_id=document_id,
            allow_derived=args.allow_derived,
            viewport_id=args.viewport_id,
            viewport_bbox=caller_bbox,
        )
        if args.rank_walls and not snapshot.fail_closed_reason:
            from pb_wall_topology_ranking_validation import (
                apply_ranking_to_snapshot,
                scoped_wall_like_fills,
            )

            bbox = caller_bbox
            if bbox is None:
                for row in list_page_viewports(
                    page, page_number=args.page, allow_derived=args.allow_derived
                ):
                    if row.get("view_id") == snapshot.viewport_id and row.get("bounding_box"):
                        bbox = row["bounding_box"]
                        break
            fills = scoped_wall_like_fills(page, bbox) if bbox is not None else ()
            snapshot = apply_ranking_to_snapshot(
                snapshot,
                wall_like_fills=fills,
                scale_pt_per_m=args.scale_pt_per_m,
            )
    finally:
        doc.close()

    report = diagnose_wall_topology(snapshot)
    _print_counts(report)
    if args.json_path:
        _write_text(args.json_path, report_to_canonical_json(report) + "\n")
    if args.markdown_path:
        _write_text(args.markdown_path, report_to_markdown(report))
    if args.svg_path:
        svg = report_to_svg(report)
        if svg is None:
            print("svg=skipped (no drawable candidate geometry)")
        else:
            _write_text(args.svg_path, svg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
