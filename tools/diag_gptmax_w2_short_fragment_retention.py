"""Read-only original-PDF W2 fragment trace, with source host report parity.

The wrapper observes the actual physical-wall producer's W2 call. It returns
the unmodified graph and never selects a wall, binds a host or emits a quantity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pb_physical_wall_candidate_authority as wall_authority
from tools.diag_opening_wall_face_preservation import source_face_report


def short_fragment_source_report(source_bytes: bytes, *, page_ids: tuple[str, ...]) -> dict:
    graph_audits = []
    build_graph = wall_authority.build_wall_graph_for_viewport

    def observe_graph(segments, **kwargs):
        graph = build_graph(segments, **kwargs)
        audit = graph.get("short_source_fragment_retention_audit")
        if audit is None:
            raise RuntimeError("actual W2 short-fragment trace unavailable")
        ordinary_graph = {k: v for k, v in graph.items()
                          if k != "short_source_fragment_retention_audit"}
        graph_audits.append({
            "input_source_segment_count": len(segments),
            "input_source_primitive_ids": sorted(str(s["id"]) for s in segments),
            "graph_without_diagnostic_sha256": hashlib.sha256(
                json.dumps(ordinary_graph, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
            "short_source_fragment_retention_audit": audit,
        })
        return graph

    with patch.dict("os.environ", {"GPTMAX_W2_SHORT_SOURCE_AUDIT": "1"}), \
            patch.object(wall_authority, "build_wall_graph_for_viewport", observe_graph):
        source_report = source_face_report(source_bytes, page_ids=page_ids)
    if not graph_audits:
        raise RuntimeError("physical-wall source scope produced no observable W2 graph")
    return {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "selected_geometry_page_ids": page_ids,
        "source_report": source_report,
        "w2_graph_audits": graph_audits,
        "source_evidence_only": True,
        "physical_equivalence_proven": False,
        "host_count_quantity_publication_allowed": False,
        "benchmark_accuracy": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--page-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pages = tuple(sorted(set(args.page_id), key=int))
    report = short_fragment_source_report(args.pdf.read_bytes(), page_ids=pages)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False,
                                      default=lambda value: value.value) + "\n")
    print(json.dumps({"source_sha256": report["source_sha256"],
                      "summary": report["source_report"]["summary"],
                      "audited_w2_graphs": len(report["w2_graph_audits"])}))


if __name__ == "__main__":
    main()
